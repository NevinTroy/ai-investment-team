"""Portfolio network: embeddings, similarity, and 2-D layout.

Embeds every portfolio company using sentence-transformers (all-MiniLM-L6-v2).
Embeddings are cached to committee/network_embeddings.npy so the model only
runs once. Exposes two public functions:

    get_network_data()          → all nodes with 2-D positions
    find_neighbors(sector, summary, top_k=10) → similarity ranked matches
"""

import json
import os
from pathlib import Path
from typing import TypedDict

import numpy as np

# ── paths ───────────────────────────────────────────────────────────────────
_HERE = Path(__file__).parent
_REPO = _HERE.parent
_JSON_PATH = _REPO / "summit_portfolio_companies.json"
_EMB_CACHE = _HERE / "network_embeddings.npy"

# ── lazy singletons ──────────────────────────────────────────────────────────
_companies: list[dict] | None = None
_embeddings: np.ndarray | None = None
_positions_2d: np.ndarray | None = None


def _embed_text(texts: list[str]) -> np.ndarray:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("all-MiniLM-L6-v2")
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=True)


def _companies_to_texts(companies: list[dict]) -> list[str]:
    return [
        f"Sector: {c.get('sector', '')}. Summary: {c.get('summary', '')}"
        for c in companies
    ]


def _load_companies() -> list[dict]:
    with open(_JSON_PATH) as f:
        return json.load(f)


def _pca_2d(embeddings: np.ndarray) -> np.ndarray:
    """Reduce to 2-D with PCA (no sklearn dependency needed for 2 components)."""
    X = embeddings - embeddings.mean(axis=0)
    cov = X.T @ X / len(X)
    _, vecs = np.linalg.eigh(cov)
    # eigh returns ascending eigenvalues; take the last two (largest)
    components = vecs[:, -2:][:, ::-1]
    return X @ components


def _ensure_loaded() -> tuple[list[dict], np.ndarray, np.ndarray]:
    global _companies, _embeddings, _positions_2d

    if _companies is not None:
        return _companies, _embeddings, _positions_2d

    _companies = _load_companies()
    texts = _companies_to_texts(_companies)

    if _EMB_CACHE.exists():
        _embeddings = np.load(_EMB_CACHE)
        if _embeddings.shape[0] != len(_companies):
            _embeddings = None  # stale cache

    if _embeddings is None:
        _embeddings = _embed_text(texts)
        np.save(_EMB_CACHE, _embeddings)

    _positions_2d = _pca_2d(_embeddings)

    return _companies, _embeddings, _positions_2d


def _norm_positions(pos: np.ndarray) -> np.ndarray:
    """Normalise 2-D positions to [0, 1] range."""
    lo, hi = pos.min(axis=0), pos.max(axis=0)
    span = hi - lo
    span[span == 0] = 1.0
    return (pos - lo) / span


class NodeData(TypedDict):
    id: int
    name: str
    sector: str
    summary: str
    location: str
    site: str
    x: float
    y: float


def get_network_data() -> list[NodeData]:
    """Return all portfolio nodes with normalised 2-D positions."""
    companies, _, positions = _ensure_loaded()
    normed = _norm_positions(positions)
    return [
        {
            "id": i,
            "name": c["name"],
            "sector": c.get("sector", ""),
            "summary": c.get("summary", ""),
            "location": c.get("location", ""),
            "site": c.get("site", ""),
            "x": float(normed[i, 0]),
            "y": float(normed[i, 1]),
        }
        for i, c in enumerate(companies)
    ]


class NeighborResult(TypedDict):
    id: int
    name: str
    sector: str
    summary: str
    location: str
    site: str
    similarity: float
    x: float
    y: float


def find_neighbors(
    sector: str,
    summary: str,
    top_k: int = 10,
) -> tuple[list[NeighborResult], tuple[float, float]]:
    """Embed a new company and return its top-k portfolio neighbours.

    Returns (neighbours, (x, y)) where x, y are the new company's normalised
    position in the same PCA space.
    """
    companies, embeddings, positions = _ensure_loaded()

    text = f"Sector: {sector}. Summary: {summary}"
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("all-MiniLM-L6-v2")
    new_emb = model.encode([text], normalize_embeddings=True)[0]

    sims: np.ndarray = embeddings @ new_emb  # cosine sim (embeddings already normalised)

    top_idx = np.argsort(sims)[::-1][:top_k]

    # Project new company into the same PCA space
    X = embeddings - embeddings.mean(axis=0)
    cov = X.T @ X / len(X)
    _, vecs = np.linalg.eigh(cov)
    components = vecs[:, -2:][:, ::-1]
    new_pos_raw = (new_emb - embeddings.mean(axis=0)) @ components

    # Normalise using the same bounds as the existing positions
    lo, hi = positions.min(axis=0), positions.max(axis=0)
    span = hi - lo
    span[span == 0] = 1.0
    new_pos = (new_pos_raw - lo) / span
    new_pos = np.clip(new_pos, 0.0, 1.0)
    normed_all = _norm_positions(positions)

    neighbours: list[NeighborResult] = []
    for idx in top_idx:
        c = companies[idx]
        neighbours.append({
            "id": int(idx),
            "name": c["name"],
            "sector": c.get("sector", ""),
            "summary": c.get("summary", ""),
            "location": c.get("location", ""),
            "site": c.get("site", ""),
            "similarity": float(sims[idx]),
            "x": float(normed_all[idx, 0]),
            "y": float(normed_all[idx, 1]),
        })

    return neighbours, (float(new_pos[0]), float(new_pos[1]))


def precompute() -> None:
    """Force-load and cache embeddings. Call once at server startup."""
    _ensure_loaded()
