"""Text helpers shared by ingestion and retrieval: tag stripping, quote matching, BM25 tokens."""
import re
import unicodedata

TAG = re.compile(r"</?(?:mark|sup|sub|br|span|u|b|i)[^>]*>", re.I)
PUNCT_MAP = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "—": "-", "–": "-", "−": "-", " ": " ", " ": " ",
})
STOPWORDS = set("""a an and are as at be by for from has have in is it its of on or that the this to
was were will with which when where what how not can may must should if than then these those""".split())


def strip_tags(text):
    return TAG.sub("", text)


def normalize_for_match(text):
    """Normalize text so a quote can be found in its source regardless of
    case, whitespace, Markdown emphasis and typographic punctuation."""
    text = unicodedata.normalize("NFKC", strip_tags(text)).translate(PUNCT_MAP)
    text = re.sub(r"[*_`#|]", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def is_supported(quote, normalized_source, min_chars=8):
    q = normalize_for_match(quote)
    return len(q) >= min_chars and q in normalized_source


def tokenize(text):
    """BM25 tokens: lowercase words and identifiers (keeps part numbers like AN470)."""
    words = re.findall(r"[a-z0-9]+(?:[-.][a-z0-9]+)*", normalize_for_match(text))
    return [w for w in words if w not in STOPWORDS and len(w) > 1]
