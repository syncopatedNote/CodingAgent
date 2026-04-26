import json
import os
from typing import Any, Dict, Iterator, List, Optional, Sequence

from langchain_core.stores import BaseStore
from redis import Redis


class RedisDocStore(BaseStore[str, Dict[str, Any]]):
    """Redis-backed document store keyed by string IDs.

    Used by MultiVectorRetriever to look up the original chunk after a vector
    search returns the matching summary. Values are JSON-encoded dicts.
    Keys are namespaced with `key_prefix` so the docstore doesn't collide
    with other Redis users in the same instance (e.g. RQ jobs).
    """

    def __init__(
        self,
        redis_url: str = "redis://127.0.0.1:6379/0",
        key_prefix: str = "docstore:documents:",
    ):
        self.client = Redis.from_url(redis_url)
        self.key_prefix = key_prefix

    def _k(self, key: str) -> str:
        return f"{self.key_prefix}{key}"

    def mget(self, keys: Sequence[str]) -> List[Optional[Dict[str, Any]]]:
        if not keys:
            return []
        raw = self.client.mget([self._k(k) for k in keys])
        return [json.loads(v) if v is not None else None for v in raw]

    def mset(self, key_value_pairs: Sequence[tuple[str, Dict[str, Any]]]) -> None:
        if not key_value_pairs:
            return
        pipe = self.client.pipeline()
        for key, value in key_value_pairs:
            pipe.set(self._k(key), json.dumps(value))
        pipe.execute()

    def mdelete(self, keys: Sequence[str]) -> None:
        if not keys:
            return
        self.client.delete(*[self._k(k) for k in keys])

    def yield_keys(self, prefix: Optional[str] = None) -> Iterator[str]:
        pattern = f"{self.key_prefix}{prefix or ''}*"
        for raw_key in self.client.scan_iter(match=pattern):
            key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else raw_key
            yield key[len(self.key_prefix) :]


def get_document_store(collection_name: Optional[str] = None) -> RedisDocStore:
    """Return a RedisDocStore namespaced under the given collection.

    Reuses RAG_REDIS_URL — same Redis instance as RQ, isolated by key prefix.
    """
    redis_url = os.getenv("RAG_REDIS_URL", "redis://127.0.0.1:6379/0")
    prefix = f"docstore:{collection_name or 'documents'}:"
    return RedisDocStore(redis_url=redis_url, key_prefix=prefix)
