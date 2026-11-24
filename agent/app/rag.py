"""Policy RAG: markdown policies -> section chunks -> embeddings -> Qdrant.

* Chunking is by `##` section, so every chunk maps to a citable "document § section".
* Embeddings run locally (fastembed / ONNX, BAAI/bge-small-en-v1.5): no embedding API key,
  and policy text never leaves the box. The model is baked into the Docker image.
* Each chunk is scanned for embedded instructions at ingest time (indirect injection).
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from .guardrails import sanitize_tool_output

log = logging.getLogger(__name__)


@dataclass
class Chunk:
    doc_file: str
    doc_title: str
    section: str
    text: str

    @property
    def citation(self) -> str:
        return f"{self.doc_title} § {self.section} (policies/{self.doc_file})"

    def embedding_text(self) -> str:
        return f"{self.doc_title} — {self.section}\n{self.text}"


def chunk_markdown(markdown: str, doc_file: str) -> list[Chunk]:
    title_match = re.search(r"^#\s+(.+)$", markdown, re.M)
    title = title_match.group(1).strip() if title_match else doc_file
    chunks: list[Chunk] = []
    parts = re.split(r"^##\s+(.+)$", markdown, flags=re.M)
    preamble = parts[0].replace(title_match.group(0), "").strip() if title_match else parts[0].strip()
    if preamble:
        chunks.append(Chunk(doc_file, title, "Overview", preamble))
    for heading, body in zip(parts[1::2], parts[2::2]):
        body = body.strip()
        if body:
            chunks.append(Chunk(doc_file, title, heading.strip(), body))
    return chunks


def load_policy_chunks(policies_dir: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(Path(policies_dir).glob("*.md")):
        for chunk in chunk_markdown(path.read_text(encoding="utf-8"), path.name):
            safe, flagged = sanitize_tool_output(chunk.text)
            if flagged:
                log.warning("Dropping chunk %s § %s: looks like embedded instructions", path.name, chunk.section)
                continue
            chunk.text = safe
            chunks.append(chunk)
    return chunks


# ---------------------------------------------------------------------------- embedders
class Embedder(Protocol):
    dim: int
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    def __init__(self, model_name: str, cache_dir: str | None = None):
        from fastembed import TextEmbedding

        self.model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        self.dim = len(next(iter(self.model.embed(["probe"]))))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self.model.passage_embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self.model.query_embed(text))).tolist()


class HashEmbedder:
    """Dependency-free bag-of-words hashing embedder. ONLY for offline unit tests."""

    dim = 512
    _stop = {"the", "a", "an", "of", "to", "and", "or", "is", "are", "for", "in", "on", "my", "i",
             "do", "does", "how", "what", "can", "be", "with", "at", "it", "if", "per"}

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            if tok in self._stop:
                continue
            for t in (tok, tok[:5]):  # crude stemming
                v[int(hashlib.md5(t.encode()).hexdigest(), 16) % self.dim] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def make_embedder(backend: str, model_name: str, cache_dir: str | None) -> Embedder:
    if backend == "hash":
        return HashEmbedder()
    return FastEmbedEmbedder(model_name, cache_dir)


# ---------------------------------------------------------------------------- vector store
@dataclass
class Hit:
    chunk: Chunk
    score: float


class PolicyStore:
    def __init__(self, url: str, collection: str, embedder: Embedder):
        self.client = QdrantClient(location=":memory:") if url == ":memory:" else QdrantClient(url=url)
        self.collection = collection
        self.embedder = embedder

    def ingest(self, chunks: list[Chunk]) -> int:
        """(Re)build the collection. The corpus is tiny, so a full rebuild on start-up keeps the
        index exactly in sync with the policy files without any bookkeeping."""
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        self.client.create_collection(
            self.collection, vectors_config=VectorParams(size=self.embedder.dim, distance=Distance.COSINE))
        vectors = self.embedder.embed_documents([c.embedding_text() for c in chunks])
        points = [
            PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{c.doc_file}#{c.section}")),
                vector=vec,
                payload={"doc_file": c.doc_file, "doc_title": c.doc_title, "section": c.section, "text": c.text},
            )
            for c, vec in zip(chunks, vectors)
        ]
        self.client.upsert(self.collection, points=points, wait=True)
        log.info("Ingested %d policy chunks into Qdrant collection %r", len(points), self.collection)
        return len(points)

    def search(self, query: str, k: int = 4, min_score: float = 0.0) -> list[Hit]:
        res = self.client.query_points(self.collection, query=self.embedder.embed_query(query), limit=k)
        hits = []
        for p in res.points:
            if p.score < min_score:
                continue
            pl = p.payload or {}
            hits.append(Hit(Chunk(pl["doc_file"], pl["doc_title"], pl["section"], pl["text"]), float(p.score)))
        return hits
