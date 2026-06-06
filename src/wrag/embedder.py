"""Embedding abstraction — local (sentence-transformers) and optional OpenAI."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wrag.config import Settings


class Embedder(ABC):
    """Base embedding interface."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Encode a batch of texts into embedding vectors."""
        ...

    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding dimension."""
        ...


class LocalEmbedder(Embedder):
    """Offline embedder using sentence-transformers (all-MiniLM-L6-v2)."""

    MODEL_NAME = "all-MiniLM-L6-v2"
    DIMENSION = 384

    def __init__(self):
        self._model = None

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.MODEL_NAME)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._load_model()
        # Truncate very long texts to avoid OOM (model max is 256 tokens, ~512 words)
        truncated = [t[:2048] for t in texts]
        embeddings = self._model.encode(truncated, show_progress_bar=False, normalize_embeddings=True)
        return embeddings.tolist()

    def dimension(self) -> int:
        return self.DIMENSION


class OpenAIEmbedder(Embedder):
    """OpenAI embeddings (text-embedding-3-small)."""

    MODEL_NAME = "text-embedding-3-small"
    DIMENSION = 1536

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "OpenAI API key required. Set OPENAI_API_KEY env var or configure in config.yaml"
            )
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self._api_key)
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        client = self._get_client()
        # OpenAI has batch limit of ~8191 tokens per text and 2048 texts per batch
        truncated = [t[:8000] for t in texts]

        # Batch in groups of 100 to stay within API limits
        all_embeddings: list[list[float]] = []
        batch_size = 100
        for i in range(0, len(truncated), batch_size):
            batch = truncated[i : i + batch_size]
            response = client.embeddings.create(model=self.MODEL_NAME, input=batch)
            all_embeddings.extend([item.embedding for item in response.data])

        return all_embeddings

    def dimension(self) -> int:
        return self.DIMENSION


def get_embedder(settings: "Settings") -> Embedder:
    """Factory: return the configured embedder based on settings."""
    if settings.embedding_model == "openai":
        return OpenAIEmbedder(api_key=settings.openai_api_key)
    return LocalEmbedder()
