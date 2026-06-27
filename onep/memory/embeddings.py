"""Embedding generation reusing the configured LLM provider."""
from __future__ import annotations

import hashlib
import math
import os
import struct
from typing import Sequence


class NullEmbedder:
    """Deterministic hash-based vectors when no embedding provider is available."""
    _instances: dict[int, NullEmbedder] = {}

    def __init__(self, dims: int = 1536):
        self.dims = dims

    @classmethod
    def get(cls, dims: int = 1536) -> NullEmbedder:
        if dims not in cls._instances:
            cls._instances[dims] = cls(dims)
        return cls._instances[dims]

    def embed(self, text: str) -> list[float]:
        # Deterministic hash-based vector so same text gets same vector
        h = int(hashlib.sha256(text.encode()).hexdigest(), 16)
        vec = []
        for i in range(self.dims):
            v = ((h >> (i % 64)) & 1) * 2.0 - 1.0
            vec.append(v / math.sqrt(self.dims))
        return vec


_cache: dict[str, list[float]] = {}


def get_embedding(text: str, model: str = "null") -> list[float]:
    """Generate embedding vector for text. Uses cache. Falls back to hashed null vectors
    when no API key is available."""
    cache_key = f"{model}:{text}"
    if cache_key in _cache:
        return _cache[cache_key]

    provider = _guess_provider(model)
    api_key = os.environ.get(f"{provider.upper()}_API_KEY", "")

    if not api_key or model == "null":
        vec = NullEmbedder.get().embed(text)
        _cache[cache_key] = vec
        return vec

    try:
        from litellm import embedding
        response = embedding(model=model, input=[text])
        vec = response.data[0]["embedding"]
        _cache[cache_key] = vec
        return vec
    except Exception:
        vec = NullEmbedder.get().embed(text)
        _cache[cache_key] = vec
        return vec


def _guess_provider(model: str) -> str:
    if "openai" in model:
        return "openai"
    if "deepseek" in model:
        return "deepseek"
    return "openai"


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def blob_to_floats(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob)//4}f", blob))


def floats_to_blob(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)
