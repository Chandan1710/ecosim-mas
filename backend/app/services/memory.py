"""
Module 7: Qdrant Episodic Memory Integration

Provides memory persistence and retrieval for agents based on
(event, action, outcome) tuples using local sentence-transformers embeddings
and Qdrant.
"""

import json
import logging
import os
from typing import List, Dict, Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as rest_models
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Constants
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION_NAME = "episodic_memory"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384

# Globals for lazy loading
_qdrant_client: QdrantClient = None
_embedding_model: SentenceTransformer = None


def _get_qdrant_client() -> QdrantClient:
    """Initialize Qdrant client and idempotently create the collection."""
    global _qdrant_client
    if _qdrant_client is not None:
        return _qdrant_client

    try:
        client = QdrantClient(
            host=QDRANT_HOST,
            port=QDRANT_PORT,
            check_compatibility=False,  # server is ahead of qdrant-client's latest
                                          # release; functionally fine, verified via
                                          # test_memory.py. Revisit if the gap widens.
        )
        # Check if collection exists
        if not client.collection_exists(COLLECTION_NAME):
            logger.info(f"Creating Qdrant collection: {COLLECTION_NAME}")
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=rest_models.VectorParams(
                    size=EMBEDDING_DIMENSION,
                    distance=rest_models.Distance.COSINE,
                ),
            )
        _qdrant_client = client
        return client
    except Exception as e:
        logger.error(f"Failed to initialize Qdrant client: {e}")
        raise


def _get_embedding_model() -> SentenceTransformer:
    """Lazily load the sentence-transformers model."""
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model

    logger.info(f"Loading embedding model: {EMBEDDING_MODEL_NAME}")
    try:
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        return _embedding_model
    except Exception as e:
        logger.error(f"Failed to load embedding model {EMBEDDING_MODEL_NAME}: {e}")
        raise


def _format_episode_text(event: dict, action: dict, outcome: dict) -> str:
    """Format the situation into a single string for embedding."""
    # We serialize dicts to string representations for a simple and effective 
    # semantic text representation.
    return (
        f"Event: {json.dumps(event)}\n"
        f"Action: {json.dumps(action)}\n"
        f"Outcome: {json.dumps(outcome)}"
    )


def _format_situation_text(situation: dict) -> str:
    """Format a current situation into a string for embedding to query similar pasts."""
    return f"Situation: {json.dumps(situation)}"


def store_episode(agent_id: str, event: dict, action: dict, outcome: dict) -> None:
    """
    Embeds the combined (event, action, outcome) as text and stores it in Qdrant
    under the episodic_memory collection, with agent_id as a payload filter.
    """
    client = _get_qdrant_client()
    model = _get_embedding_model()

    episode_text = _format_episode_text(event, action, outcome)
    # Embed the text
    vector = model.encode(episode_text).tolist()

    import uuid
    point_id = str(uuid.uuid4())

    payload = {
        "agent_id": agent_id,
        "event": event,
        "action": action,
        "outcome": outcome,
        "text": episode_text,
    }

    client.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            rest_models.PointStruct(
                id=point_id,
                vector=vector,
                payload=payload,
            )
        ],
    )


def retrieve_similar_episodes(agent_id: str, current_situation: dict, k: int = 5) -> List[Dict[str, Any]]:
    """
    Embeds current_situation, queries Qdrant for the k nearest past
    episodes for that agent_id, and returns them.
    """
    client = _get_qdrant_client()
    model = _get_embedding_model()

    situation_text = _format_situation_text(current_situation)
    vector = model.encode(situation_text).tolist()

    search_result = client.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        query_filter=rest_models.Filter(
            must=[
                rest_models.FieldCondition(
                    key="agent_id",
                    match=rest_models.MatchValue(value=agent_id),
                )
            ]
        ),
        limit=k,
        with_payload=True,
    )

    # Reconstruct returned episodes
    episodes = []
    for hit in search_result.points:
        episodes.append({
            "event": hit.payload.get("event", {}),
            "action": hit.payload.get("action", {}),
            "outcome": hit.payload.get("outcome", {}),
            "score": hit.score,
        })

    return episodes
