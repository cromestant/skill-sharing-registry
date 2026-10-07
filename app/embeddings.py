"""Pinned embedding model. Server-side embedding is the v0 default:
the registry embeds, so model versioning stays the registry's problem.

Canonical model: BAAI/bge-small-en-v1.5 — ~130MB, CPU-friendly,
384 dimensions. The resolved revision is recorded at startup and served
from GET /v0/models so clients can pin against it.
"""

MODEL_ID = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384

_model = None
_model_revision = None


def _load():
    global _model, _model_revision
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(MODEL_ID, device="cpu")
        # Best-effort revision capture for the models endpoint.
        try:
            info = _model._model_config if hasattr(_model, "_model_config") else None
            _model_revision = getattr(info, "_name_or_path", MODEL_ID)
        except Exception:
            _model_revision = MODEL_ID
    return _model


def embed(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts. Returns L2-normalized vectors."""
    model = _load()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vectors]


def model_info() -> dict:
    _load()  # ensure resolved
    return {
        "model_id": MODEL_ID,
        "revision": _model_revision or MODEL_ID,
        "dim": EMBED_DIM,
        "mode": "server_side_default",
    }
