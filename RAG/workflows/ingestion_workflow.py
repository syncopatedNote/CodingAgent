from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class IngestionWorkflow:
    """Thin workflow wrapper that runs ingest_file_activity with retry logic.

    The activity is referenced by string name to avoid importing the heavy
    ingest module inside the Temporal workflow sandbox.
    """

    @workflow.run
    async def run(self, bucket: str, object_key: str) -> dict:
        return await workflow.execute_activity(
            "ingest_file_activity",
            args=[bucket, object_key],
            schedule_to_close_timeout=timedelta(hours=1),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=10),
                backoff_coefficient=2.0,
                maximum_interval=timedelta(minutes=5),
            ),
        )
