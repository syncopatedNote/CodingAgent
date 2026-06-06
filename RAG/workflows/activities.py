from temporalio import activity


@activity.defn
def ingest_file_activity(bucket: str, object_key: str) -> dict:
    from RAG.ingest import ingest_file

    return ingest_file(bucket, object_key)
