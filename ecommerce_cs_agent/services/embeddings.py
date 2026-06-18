from __future__ import annotations

from dataclasses import dataclass
import hashlib


@dataclass(frozen=True)
class EmbeddingResult:
    model: str
    vector: list[float]

    def to_pgvector(self) -> str:
        return "[" + ",".join(f"{value:.6f}" for value in self.vector) + "]"


class DeterministicEmbeddingProvider:
    def __init__(self, *, dimensions: int = 1536, model: str = "deterministic-hash-v1") -> None:
        self.dimensions = dimensions
        self.model = model

    def embed(self, text: str) -> EmbeddingResult:
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        values: list[float] = []
        counter = 0
        while len(values) < self.dimensions:
            digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            for index in range(0, len(digest), 2):
                if len(values) >= self.dimensions:
                    break
                raw = int.from_bytes(digest[index:index + 2], "big")
                values.append((raw / 65535.0) * 2 - 1)
            counter += 1
        return EmbeddingResult(model=self.model, vector=values)
