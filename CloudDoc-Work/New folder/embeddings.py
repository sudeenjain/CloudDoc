"""Local embeddings through Ollama (default model: nomic-embed-text). Nothing leaves the machine."""
from __future__ import annotations

import logging
import time
from typing import Optional

import httpx
import numpy as np

from config import EMBED_MODEL, EMBED_TIMEOUT, OLLAMA_URL

logger = logging.getLogger("clouddoc.embeddings")


class EmbeddingError(RuntimeError):
    pass


class NullEmbedder:
    """Used when semantic search is disabled (BM25 + synonym expansion only)."""

    model = "none"

    def is_available(self) -> bool:
        return False

    def embed_documents(self, texts: list[str]) -> np.ndarray:  # pragma: no cover - never called
        raise EmbeddingError("Embeddings are disabled.")

    def embed_query(self, text: str) -> np.ndarray:  # pragma: no cover - never called
        raise EmbeddingError("Embeddings are disabled.")


class OllamaEmbedder:
    """Embeds text with a local Ollama embedding model."""

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None,
                 timeout: Optional[float] = None):
        self.base_url = (base_url or OLLAMA_URL).rstrip("/")
        self.model = model or EMBED_MODEL
        self.timeout = float(timeout if timeout is not None else EMBED_TIMEOUT)
        self._avail: Optional[bool] = None
        self._avail_at = 0.0

    # nomic-embed-text expects task prefixes; other models get the text unchanged.
    def _prefixed(self, texts: list[str], kind: str) -> list[str]:
        if "nomic" in self.model.lower():
            prefix = "search_query: " if kind == "query" else "search_document: "
            return [prefix + t for t in texts]
        return texts

    def is_available(self) -> bool:
        """True when Ollama is reachable and the embedding model is pulled (cached for 30 s)."""
        now = time.monotonic()
        if self._avail is not None and now - self._avail_at < 30:
            return self._avail
        ok = False
        try:
            with httpx.Client(timeout=2.0) as client:
                res = client.get(f"{self.base_url}/api/tags")
                if res.status_code == 200:
                    names = [m.get("name", "") for m in res.json().get("models", [])]
                    wanted = self.model.split(":")[0]
                    ok = any(n.split(":")[0] == wanted for n in names)
        except Exception:
            ok = False
        self._avail, self._avail_at = ok, now
        return ok

    def _embed_batch(self, client: httpx.Client, texts: list[str]) -> list[list[float]]:
        res = client.post(f"{self.base_url}/api/embed", json={"model": self.model, "input": texts})
        if res.status_code == 200 and res.json().get("embeddings"):
            return res.json()["embeddings"]
        # Older Ollama versions only have the single-prompt endpoint.
        out = []
        for text in texts:
            r = client.post(f"{self.base_url}/api/embeddings", json={"model": self.model, "prompt": text})
            if r.status_code != 200 or not r.json().get("embedding"):
                raise EmbeddingError(f"Ollama embedding request failed (HTTP {r.status_code}).")
            out.append(r.json()["embedding"])
        return out

    def _embed(self, texts: list[str], kind: str) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        prepared = self._prefixed(texts, kind)
        vectors: list[list[float]] = []
        try:
            with httpx.Client(timeout=self.timeout) as client:
                for i in range(0, len(prepared), 16):
                    vectors.extend(self._embed_batch(client, prepared[i : i + 16]))
        except EmbeddingError:
            raise
        except Exception as exc:
            self._avail = None
            raise EmbeddingError(f"Embedding request failed: {exc}") from exc
        arr = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts, "document")

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([text], "query")[0]
