"""Tests for wrag.embedder — embedding abstraction."""

import pytest
from unittest.mock import patch, MagicMock
import numpy as np

from wrag.embedder import LocalEmbedder, OpenAIEmbedder, get_embedder
from wrag.config import Settings


class TestLocalEmbedder:
    def test_dimension(self):
        embedder = LocalEmbedder()
        assert embedder.dimension() == 384

    @patch("wrag.embedder.LocalEmbedder._load_model")
    def test_embed_calls_model(self, mock_load):
        embedder = LocalEmbedder()
        # Mock the model
        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(2, 384).astype(np.float32)
        embedder._model = mock_model

        result = embedder.embed(["hello world", "test text"])
        assert len(result) == 2
        assert len(result[0]) == 384
        mock_model.encode.assert_called_once()

    @patch("wrag.embedder.LocalEmbedder._load_model")
    def test_embed_truncates_long_text(self, mock_load):
        embedder = LocalEmbedder()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(1, 384).astype(np.float32)
        embedder._model = mock_model

        long_text = "x" * 5000
        embedder.embed([long_text])

        # Verify the text was truncated to 2048 chars
        call_args = mock_model.encode.call_args[0][0]
        assert len(call_args[0]) == 2048


class TestOpenAIEmbedder:
    def test_dimension(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            embedder = OpenAIEmbedder(api_key="test-key")
            assert embedder.dimension() == 1536

    def test_requires_api_key(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=True):
            with pytest.raises(ValueError, match="OpenAI API key required"):
                OpenAIEmbedder(api_key="")

    @patch("openai.OpenAI")
    def test_embed_calls_api(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        # Mock response
        mock_item = MagicMock()
        mock_item.embedding = [0.1] * 1536
        mock_response = MagicMock()
        mock_response.data = [mock_item, mock_item]
        mock_client.embeddings.create.return_value = mock_response

        embedder = OpenAIEmbedder(api_key="test-key")
        result = embedder.embed(["hello", "world"])

        assert len(result) == 2
        assert len(result[0]) == 1536
        mock_client.embeddings.create.assert_called_once()


class TestGetEmbedder:
    def test_returns_local_by_default(self):
        settings = Settings(embedding_model="local")
        embedder = get_embedder(settings)
        assert isinstance(embedder, LocalEmbedder)

    def test_returns_openai_when_configured(self):
        settings = Settings(embedding_model="openai", openai_api_key="test-key")
        embedder = get_embedder(settings)
        assert isinstance(embedder, OpenAIEmbedder)

    def test_openai_without_key_raises(self):
        settings = Settings(embedding_model="openai", openai_api_key=None)
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=True):
            with pytest.raises(ValueError):
                get_embedder(settings)
