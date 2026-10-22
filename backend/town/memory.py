"""
memory.py — each agent's memory stream (after Park et al., "Generative Agents", 2023).

Every observation, action outcome, conversation and reflection is stored as a
memory with an importance score (1-10). When an agent decides, it retrieves
the memories that best match what it is thinking about, scored by

    recency (decays per day) + importance + relevance (embedding similarity)

so a missed EMI last week can outweigh a cup of tea this morning.

Backends:
  * QdrantMemory — persistent, in the `agent_memory` collection (the default
    when Qdrant is reachable)
  * LocalMemory  — in-process; used in tests and as a fallback
Embedders:
  * sentence-transformers all-MiniLM-L6-v2 (the default, same as module 7)
  * HashEmbedder — dependency-free lexical fallback (ECOSIM_EMBEDDER=hash)
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

DIM = 384
RECENCY_DECAY = 0.85        # per day
W_RECENCY, W_IMPORTANCE, W_RELEVANCE = 1.0, 1.0, 1.0
PHASE_OFFSET = {"dawn": 0.0, "morning": 0.25, "afternoon": 0.5, "evening": 0.75, "night": 0.9}


@dataclass
class Memory:
    agent_id: str
    day: int
    phase: str
    kind: str          # observation | action | conversation | reflection | news | plan
    text: str
    importance: int
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    vector: Optional[np.ndarray] = None
    score: float = 0.0

    @property
    def t(self) -> float:
        return self.day + PHASE_OFFSET.get(self.phase, 0.5)

    def to_dict(self) -> dict:
        return {"id": self.id, "agent_id": self.agent_id, "day": self.day, "phase": self.phase,
                "kind": self.kind, "text": self.text, "importance": self.importance,
                "score": round(self.score, 3)}


# ── embedders ───────────────────────────────────────────────────────────────
class HashEmbedder:
    """Feature-hashed bag of words + bigrams. Crude, deterministic, no downloads."""

    name = "hash"

    def encode(self, texts: List[str]) -> np.ndarray:
        out = np.zeros((len(texts), DIM), dtype=np.float32)
        for i, t in enumerate(texts):
            toks = re.findall(r"[a-z0-9₹]+", t.lower())
            feats = toks + [a + "_" + b for a, b in zip(toks, toks[1:])]
            for f in feats:
                h = int(hashlib.md5(f.encode()).hexdigest(), 16)
                out[i, h % DIM] += 1.0 if (h >> 9) & 1 else -1.0
            n = np.linalg.norm(out[i])
            if n > 0:
                out[i] /= n
        return out


class STEmbedder:
    name = "all-MiniLM-L6-v2"

    def __init__(self):
        from sentence_transformers import SentenceTransformer  # heavy import, only when used
        self.model = SentenceTransformer("all-MiniLM-L6-v2")

    def encode(self, texts: List[str]) -> np.ndarray:
        return np.asarray(self.model.encode(texts, normalize_embeddings=True), dtype=np.float32)


_EMBEDDER = None


def get_embedder():
    global _EMBEDDER
    if _EMBEDDER is None:
        if os.getenv("ECOSIM_EMBEDDER", "") == "hash":
            _EMBEDDER = HashEmbedder()
        else:
            try:
                _EMBEDDER = STEmbedder()
            except Exception as e:  # no model download / no torch: degrade, but say so
                logger.warning("sentence-transformers unavailable (%s); using hash embeddings", e)
                _EMBEDDER = HashEmbedder()
    return _EMBEDDER


# ── stores ──────────────────────────────────────────────────────────────────
class MemoryStore:
    """Common retrieval logic; subclasses implement storage."""

    backend = "base"

    def __init__(self, run_id: str, embedder=None):
        self.run_id = run_id
        self.embedder = embedder or get_embedder()
        self._mem: Dict[str, List[Memory]] = {}   # recent window kept in-process for speed

    def add(self, agent_id: str, day: int, phase: str, kind: str, text: str, importance: int) -> Memory:
        importance = int(max(1, min(10, importance)))
        m = Memory(agent_id, day, phase, kind, text.strip(), importance)
        m.vector = self.embedder.encode([m.text])[0]
        self._mem.setdefault(agent_id, []).append(m)
        self._persist(m)
        return m

    def add_many(self, items: List[tuple]) -> List[Memory]:
        """items: (agent_id, day, phase, kind, text, importance) — embeds in one batch."""
        if not items:
            return []
        vecs = self.embedder.encode([it[4] for it in items])
        out = []
        for it, v in zip(items, vecs):
            m = Memory(it[0], it[1], it[2], it[3], it[4].strip(), int(max(1, min(10, it[5]))))
            m.vector = v
            self._mem.setdefault(m.agent_id, []).append(m)
            out.append(m)
        self._persist_many(out)
        return out

    def recent(self, agent_id: str, n: int = 10, kinds: Optional[tuple] = None) -> List[Memory]:
        ms = [m for m in self._mem.get(agent_id, []) if kinds is None or m.kind in kinds]
        return ms[-n:]

    def all(self, agent_id: str) -> List[Memory]:
        return list(self._mem.get(agent_id, []))

    def importance_since(self, agent_id: str, t: float) -> int:
        return sum(m.importance for m in self._mem.get(agent_id, []) if m.t > t and m.kind != "reflection")

    def retrieve(self, agent_id: str, query: str, now_day: int, k: int = 6) -> List[Memory]:
        cands = self._candidates(agent_id, query)
        if not cands:
            return []
        q = self.embedder.encode([query])[0]
        now = now_day + 0.5
        rel = np.array([float(np.dot(q, m.vector)) if m.vector is not None else 0.0 for m in cands])
        if rel.max() > rel.min():
            rel = (rel - rel.min()) / (rel.max() - rel.min())
        else:
            rel = np.zeros_like(rel)
        for m, r in zip(cands, rel):
            rec = RECENCY_DECAY ** max(0.0, now - m.t)
            m.score = W_RECENCY * rec + W_IMPORTANCE * m.importance / 10.0 + W_RELEVANCE * float(r)
        out, seen = [], set()
        for m in sorted(cands, key=lambda m: m.score, reverse=True):
            if m.text in seen:
                continue
            seen.add(m.text)
            out.append(m)
            if len(out) >= k:
                break
        return out

    # storage hooks
    def _persist(self, m: Memory) -> None:
        pass

    def _persist_many(self, ms: List[Memory]) -> None:
        for m in ms:
            self._persist(m)

    def _candidates(self, agent_id: str, query: str) -> List[Memory]:
        return self._mem.get(agent_id, [])


class LocalMemory(MemoryStore):
    backend = "local"


class QdrantMemory(MemoryStore):
    """Persists every memory to Qdrant so runs can be inspected and replayed later."""

    backend = "qdrant"
    COLLECTION = "agent_memory"

    def __init__(self, run_id: str, embedder=None, client=None):
        super().__init__(run_id, embedder)
        from qdrant_client import QdrantClient
        from qdrant_client.http import models as rest
        self.rest = rest
        self.client = client or QdrantClient(host=os.getenv("QDRANT_HOST", "localhost"),
                                             port=int(os.getenv("QDRANT_PORT", "6333")),
                                             check_compatibility=False, timeout=5)
        if not self.client.collection_exists(self.COLLECTION):
            self.client.create_collection(self.COLLECTION, vectors_config=rest.VectorParams(
                size=DIM, distance=rest.Distance.COSINE))

    def _persist_many(self, ms: List[Memory]) -> None:
        if not ms:
            return
        try:
            self.client.upsert(self.COLLECTION, points=[
                self.rest.PointStruct(id=str(uuid.UUID(m.id)), vector=m.vector.tolist(), payload={
                    "run_id": self.run_id, "agent_id": m.agent_id, "day": m.day, "phase": m.phase,
                    "kind": m.kind, "text": m.text, "importance": m.importance})
                for m in ms])
        except Exception as e:   # memory still works in-process; persistence is best effort
            logger.warning("Qdrant upsert failed: %s", e)

    def _persist(self, m: Memory) -> None:
        self._persist_many([m])


def make_memory(run_id: str, prefer: str = "auto", embedder=None) -> MemoryStore:
    if prefer == "local":
        return LocalMemory(run_id, embedder)
    try:
        return QdrantMemory(run_id, embedder)
    except Exception as e:
        if prefer == "qdrant":
            raise
        logger.warning("Qdrant not reachable (%s); agent memory will be kept in-process for this run", e)
        return LocalMemory(run_id, embedder)
