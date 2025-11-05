from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional, Any, Dict, List, Sequence, Iterator
from pymongo import MongoClient
from langchain_core.stores import BaseStore


class MongoDocStore(BaseStore[str, Dict[str, Any]]):
    """MongoDB-backed document store with both sync and async capabilities."""

    def __init__(
        self,
        database: str = "langchain_db",
        collection_name: str = "documents",
        mongodb_uri: str = "mongodb://127.0.0.1:27017"
    ):
        """Initialize with both sync and async clients."""
        # Sync client for MultiVectorRetriever
        self.sync_client = MongoClient(mongodb_uri)
        self.database = database
        self.collection_name = collection_name
        self.sync_collection = self.sync_client[database][collection_name]

        # Async client for other operations
        self.async_client = AsyncIOMotorClient(mongodb_uri)
        self.async_collection = self.async_client[database][collection_name]

    def mget(self, keys: Sequence[str]) -> List[Optional[Dict[str, Any]]]:
        """
        Get the values associated with the given keys.

        Args:
            keys: A sequence of keys to retrieve.

        Returns:
            List of values associated with the keys. None for missing keys.
        """
        try:
            # Query MongoDB for documents with matching IDs
            documents = list(self.sync_collection.find({"_id": {"$in": list(keys)}}))

            # Create a mapping of id to document for preserving order
            doc_map = {doc["_id"]: doc for doc in documents}

            # Return documents in the same order as requested keys
            result = []
            for key in keys:
                if key in doc_map:
                    doc = doc_map[key].copy()
                    doc.pop("_id", None)  # Remove MongoDB's _id field
                    result.append(doc)
                else:
                    result.append(None)
            print("************************DOCSTORE RESPONSE FOR MULTIVECTOR RETRIEVER******************************")
            print(result)
            print("************************DOCSTORE RESPONSE FOR MULTIVECTOR RETRIEVER******************************")

            return result

        except Exception as e:
            print(f"Error retrieving documents: {str(e)}")
            raise

    def mset(self, key_value_pairs: Sequence[tuple[str, Dict[str, Any]]]) -> None:
        """
        Set the values for the given keys.

        Args:
            key_value_pairs: A sequence of key-value pairs to set.
        """
        try:
            documents = []
            for key, value in key_value_pairs:
                doc = {"_id": key, **value}
                documents.append(doc)

            if documents:
                self.sync_collection.insert_many(documents)
        except Exception as e:
            print(f"Error setting documents: {str(e)}")
            raise

    def mdelete(self, keys: Sequence[str]) -> None:
        """
        Delete the given keys and their associated values.

        Args:
            keys: A sequence of keys to delete.
        """
        try:
            self.sync_collection.delete_many({"_id": {"$in": list(keys)}})
        except Exception as e:
            print(f"Error deleting documents: {str(e)}")
            raise

    def yield_keys(self, prefix: Optional[str] = None) -> Iterator[str]:
        """
        Get an iterator over keys that match the given prefix.

        Args:
            prefix: Optional prefix to filter keys.

        Returns:
            Iterator over matching keys.
        """
        try:
            query = {}
            if prefix:
                query["_id"] = {"$regex": f"^{prefix}"}

            for doc in self.sync_collection.find(query, {"_id": 1}):
                yield doc["_id"]
        except Exception as e:
            print(f"Error yielding keys: {str(e)}")
            raise

    async def async_mget(self, keys: Sequence[str]) -> List[Optional[Dict[str, Any]]]:
        """
        Asynchronous get multiple documents by their keys.

        Args:
            keys: A sequence of keys to retrieve.

        Returns:
            List of values associated with the keys. None for missing keys.
        """
        try:
            cursor = self.async_collection.find({"_id": {"$in": list(keys)}})
            documents = await cursor.to_list(length=None)

            doc_map = {doc["_id"]: doc for doc in documents}

            result = []
            for key in keys:
                if key in doc_map:
                    doc = doc_map[key].copy()
                    doc.pop("_id", None)
                    result.append(doc)
                else:
                    result.append(None)

            return result

        except Exception as e:
            print(f"Error retrieving documents: {str(e)}")
            raise

    def close(self):
        """Close both sync and async clients."""
        if self.sync_client:
            self.sync_client.close()
        if self.async_client:
            self.async_client.close()


class DocStoreClient:
    def __init__(self):
        self.database_name = "langchain_db"
        self.collection_name = "documents"
        self.mongodb_uri = "mongodb://127.0.0.1:27017"
        self._docstore = None

    def get_docstore(
        self,
        collection_name: Optional[str] = None
    ) -> MongoDocStore:
        """
        Get or create a MongoDB document store instance.

        Args:
            collection_name (str, optional): Name of the collection to use.

        Returns:
            MongoDocStore: Configured MongoDB document store instance
        """
        if collection_name:
            self.collection_name = collection_name

        if not self._docstore:
            self._docstore = MongoDocStore(
                database=self.database_name,
                collection_name=self.collection_name,
                mongodb_uri=self.mongodb_uri
            )

        return self._docstore

    def close(self) -> None:
        """Close the MongoDB connections"""
        if self._docstore:
            self._docstore.close()
            self._docstore = None


# Singleton instance
_docstore_client = None


def get_document_store(
    collection_name: Optional[str] = None
) -> MongoDocStore:
    """
    Get a MongoDB document store instance.

    Args:
        collection_name (str, optional): Name of the MongoDB collection to use.

    Returns:
        MongoDocStore: Configured MongoDB document store instance
    """
    global _docstore_client

    if not _docstore_client:
        _docstore_client = DocStoreClient()

    return _docstore_client.get_docstore(collection_name)
