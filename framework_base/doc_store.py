from typing import Any, Dict, Iterator, List, Optional, Sequence

import psycopg
from psycopg.types.json import Jsonb
from langchain_core.stores import BaseStore

from settings import settings


class PostgresDocStore(BaseStore[str, Dict[str, Any]]):
    """PostgreSQL-backed document store keyed by string IDs.

    Used by MultiVectorRetriever to look up the original chunk after a vector
    search returns the matching summary. Values are stored as JSONB.
    Collection-level isolation is handled via the `collection` column so a
    single table serves all knowledge-base namespaces.
    """

    def __init__(self, dsn: str, collection: str = "documents"):
        self.dsn = dsn
        self.collection = collection
        self._ensure_table()

    def _conn(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn, autocommit=True)

    def _ensure_table(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id          TEXT        NOT NULL,
                    collection  TEXT        NOT NULL DEFAULT 'documents',
                    data        JSONB       NOT NULL,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (id, collection)
                )
            """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_document_chunks_collection "
                "ON document_chunks (collection)"
            )

    def mget(self, keys: Sequence[str]) -> List[Optional[Dict[str, Any]]]:
        if not keys:
            return []
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, data FROM document_chunks "
                "WHERE collection = %s AND id = ANY(%s)",
                (self.collection, list(keys)),
            ).fetchall()
        row_map = {row[0]: row[1] for row in rows}
        return [row_map.get(k) for k in keys]

    def mset(self, key_value_pairs: Sequence[tuple[str, Dict[str, Any]]]) -> None:
        if not key_value_pairs:
            return
        with self._conn() as conn, conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO document_chunks (id, collection, data)
                VALUES (%s, %s, %s)
                ON CONFLICT (id, collection)
                DO UPDATE SET data = EXCLUDED.data
                """,
                [(k, self.collection, Jsonb(v)) for k, v in key_value_pairs],
            )

    def mdelete(self, keys: Sequence[str]) -> None:
        if not keys:
            return
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM document_chunks " "WHERE collection = %s AND id = ANY(%s)",
                (self.collection, list(keys)),
            )

    def yield_keys(self, prefix: Optional[str] = None) -> Iterator[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id FROM document_chunks "
                "WHERE collection = %s AND id LIKE %s",
                (self.collection, f"{prefix or ''}%"),
            ).fetchall()
        for row in rows:
            yield row[0]


def get_document_store(
    collection_name: Optional[str] = None,
) -> PostgresDocStore:
    """Return a PostgresDocStore namespaced to the given collection."""
    return PostgresDocStore(
        dsn=settings.postgres_dsn, collection=collection_name or "documents"
    )
