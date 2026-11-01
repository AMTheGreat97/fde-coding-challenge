"""OpenRouter client: structured chat completions and embeddings, with pickle caches.

Hosted inference only. Every response is cached by request hash so a rebuild
replays from disk instead of paying again.
"""
import hashlib
import json
import os
import pickle
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODELS = {
    "EMBEDDING_MODEL": "openai/text-embedding-3-small",
    "LLM_MODEL": "openai/gpt-4.1-mini",
    "ANSWER_MODEL": "openai/gpt-4.1",
}
EMBEDDING_DIMS = 1536
RETRYABLE = {408, 429, 500, 502, 503, 504}


class ProviderError(Exception):
    pass


def load_env(path=ROOT / ".env"):
    """Load KEY=VALUE lines from .env into os.environ (existing vars win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            if value.strip():
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def model_name(var):
    return os.environ.get(var) or DEFAULT_MODELS[var]


class PickleCache:
    """A dict persisted to a pickle file, safe to use from several threads."""

    def __init__(self, path, autosave_every=50):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.autosave_every = autosave_every
        self._dirty = 0
        self.data = {}
        if self.path.exists():
            with open(self.path, "rb") as f:
                self.data = pickle.load(f)  # only files written by this pipeline

    def get(self, key):
        with self.lock:
            return self.data.get(key)

    def put(self, key, value):
        with self.lock:
            self.data[key] = value
            self._dirty += 1
            if self._dirty >= self.autosave_every:
                self._save()

    def save(self):
        with self.lock:
            self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            pickle.dump(self.data, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, self.path)
        self._dirty = 0


def _post(path, body, timeout):
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise ProviderError("OPENROUTER_API_KEY is not set")
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.load(response)
            if "error" in result:
                raise ProviderError(f"{path}: {str(result['error'])[:300]}")
            return result
        except urllib.error.HTTPError as e:
            last = ProviderError(f"{path}: HTTP {e.code} {e.read().decode(errors='replace')[:300]}")
            if e.code not in RETRYABLE:
                raise last
        except (urllib.error.URLError, TimeoutError, ProviderError, json.JSONDecodeError) as e:
            last = e if isinstance(e, ProviderError) else ProviderError(f"{path}: {e}")
        time.sleep(2 * 2 ** attempt)
    raise last


def _hash(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def chat_json(messages, schema_name, schema, *, model=None, prompt_version, kind,
              cache=None, max_tokens=4000, timeout=120):
    """Run a strict json_schema chat completion. Returns (parsed_json, record)."""
    model = model or model_name("LLM_MODEL")
    key = _hash({"model": model, "prompt_version": prompt_version, "messages": messages, "schema": schema})
    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            return hit["response_json"], {**hit, "request_sha256": key, "cached": True}
    result = _post("/chat/completions", {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
        "provider": {"require_parameters": True},
        "usage": {"include": True},
    }, timeout)
    choice = result["choices"][0]
    if choice.get("finish_reason") == "length":
        raise ProviderError(f"{kind}: output hit max_tokens={max_tokens}")
    try:
        parsed = json.loads(choice["message"]["content"])
    except (TypeError, json.JSONDecodeError) as e:
        raise ProviderError(f"{kind}: invalid JSON from model: {e}")
    record = {"model": result.get("model", model), "prompt_version": prompt_version, "request_kind": kind,
              "response_json": parsed, "usage": result.get("usage", {}),
              "created_at": datetime.now(timezone.utc).isoformat()}
    if cache is not None:
        cache.put(key, record)
    return parsed, {**record, "request_sha256": key, "cached": False}


def embed(texts, *, model=None, cache=None, batch_size=128, timeout=60):
    """Embed texts; returns an L2-normalized float32 array of shape (len(texts), 1536)."""
    model = model or model_name("EMBEDDING_MODEL")
    keys = [hashlib.sha256(f"{model}\n{t}".encode()).hexdigest() for t in texts]
    vectors = {}
    missing = []
    for k, t in zip(keys, texts):
        hit = cache.get(k) if cache is not None else None
        if hit is not None:
            vectors[k] = hit
        elif k not in vectors:
            missing.append((k, t))
            vectors[k] = None
    for i in range(0, len(missing), batch_size):
        batch = missing[i:i + batch_size]
        result = _post("/embeddings", {"model": model, "input": [t for _, t in batch]}, timeout)
        for item in sorted(result["data"], key=lambda d: d["index"]):
            k = batch[item["index"]][0]
            v = np.asarray(item["embedding"], dtype=np.float32)
            if v.shape != (EMBEDDING_DIMS,):
                raise ProviderError(f"embedding has shape {v.shape}, expected ({EMBEDDING_DIMS},)")
            vectors[k] = v
            if cache is not None:
                cache.put(k, v)
    matrix = np.stack([vectors[k] for k in keys]) if keys else np.zeros((0, EMBEDDING_DIMS), np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return (matrix / np.where(norms == 0, 1, norms)).astype(np.float32)
