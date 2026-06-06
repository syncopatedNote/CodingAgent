"""
he Temporal Sandbox intercepts the Python import system. If Workflow A and Workflow B both import your_module, Temporal completely wipes and re-creates your_module in an isolated environment for each individual workflow run.

When you wrap an import in with workflow.unsafe.imports_passed_through():, you are telling Temporal to turn off that isolation. Instead of creating a clean copy, Temporal reaches out to the host Worker's standard global Python environment (sys.modules) and passes a direct reference to that existing module into the sandbox.

2. Is it a "global reference for other processes"?
It is a global reference within the same Worker process, but not across different OS processes or different servers.

Inside the same Worker: Yes. If Workflow Task 1 and Workflow Task 2 are running concurrently on the same Worker and they both use imports_passed_through() for my_shared_module, they are pointing to the exact same object in memory.

State Leakage Danger: If Workflow Task 1 modifies a global variable inside my_shared_module (e.g., my_shared_module.GLOBAL_COUNT += 1), Workflow Task 2 will see that change. This is precisely why it is marked unsafe—mutating that shared state will break workflow determinism and cause replay failures.

Summary: The Golden Rule
You should only pass modules through the sandbox if:

They are heavy libraries (like boto3, pandas, or large internal data models) that take too long to re-import every few milliseconds.

The passed-through modules are completely stateless or read-only within your workflow.

If you just need to pass data or activities into your workflow (as seen in the Temporal Quickstart Guide), using imports_passed_through() is perfectly safe because you are only referencing function definitions, not modifying global module variables.

The UnsandboxedWorkflowRunner in the Temporal Python SDK is directly related to this concept—in fact, it is the nuclear option for what you are trying to achieve.

While workflow.unsafe.imports_passed_through() is a surgical knife used to bypass isolation for specific, individual modules, UnsandboxedWorkflowRunner is a sledgehammer that completely turns off the sandbox for your entire Worker.

🛠️ How it is Used
By default, the Worker class uses SandboxedWorkflowRunner under the hood. If you want to completely disable the sandbox for every workflow running on a specific Worker, you pass UnsandboxedWorkflowRunner into the worker's initialization definition:

import asyncio
from temporalio.client import Client
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

async def main():
    client = await Client.connect("localhost:7233")

    # This worker will not isolate ANY workflow code
    worker = Worker(
        client,
        task_queue="my-task-queue",
        workflows=[MyWorkflow],
        activities=[my_activity],
        workflow_runner=UnsandboxedWorkflowRunner() # <-- Disables the sandbox entirely
    )
    await worker.run()

To understand why non-deterministic code is dangerous, you have to look at Temporal’s superpower: Replay.

Temporal does not save the actual state of your running code (like a virtual machine snapshot). Instead, it saves an Event History (a timeline of events like "Workflow Started", "Activity 1 Scheduled", "Activity 1 Completed").

If a Worker crashes midway through a workflow, a new Worker picks up the pieces. To reconstruct where your code left off, it spins up your workflow code from the very beginning and replays it. During this replay, when the code calls an Activity, Temporal intercepts it and says, "Don't actually run that API call again; here is the result from the last time we did it."

For this to work, your workflow code must make the exact same logical decisions during the replay as it did the first time. If it takes a different path, the replay breaks.

🚫 A Clear Example of Broken Code
Imagine you are writing a workflow that approves a discount. If the customer is lucky, they get a 20% discount; otherwise, they get 5%.

Here is a broken, non-deterministic workflow using Python's native random module:

Python
import random
from temporalio import workflow
from datetime import timedelta

@workflow.defn
class DiscountWorkflow:
    @workflow.run
    async def run(self) -> str:
        # ❌ CRITICAL BUG: Native random is non-deterministic
        lucky_number = random.randint(1, 10)

        if lucky_number > 5:
            discount = "20%"
        else:
            discount = "5%"

        # This is a safe Temporal Activity execution
        await workflow.execute_activity(
            send_discount_email,
            discount,
            schedule_to_close_timeout=timedelta(seconds=5)
        )

        return discount
💥 How It Breaks the Workflow (Step-by-Step)
If you use the default SandboxedWorkflowRunner, Temporal will throw an error the moment you try to import random, protecting you. But if you use UnsandboxedWorkflowRunner, this code will execute. Here is how it blows up:

Step 1: The Initial Execution
The workflow starts.

It hits random.randint(1, 10). The CPU generates the number 8.

Since 8 > 5, the code enters the if block. discount becomes "20%".

It executes the Activity send_discount_email("20%").

Temporal records this in the Event History: "Activity completed successfully with input 20%".

Step 2: The Disaster (Crash)
Right after the email activity finishes, the server hosting your Worker loses power and crashes. The workflow is not done yet, so Temporal spins up a new Worker on a different machine to finish the job.

Step 3: The Replay (Where it breaks)
The new Worker needs to figure out what happens next, so it replays the code from line 1:

It hits random.randint(1, 10) again.

Because it's a completely new execution on a new machine, the CPU generates a different number: 3.

Since 3 is not greater than 5, the code enters the else block! discount becomes "5%".

The code reaches the line: await workflow.execute_activity(send_discount_email, discount...).

The workflow engine looks at its official Event History to see what happened next. The history says: “The next event is the completion of send_discount_email with the argument "20%".”

But the replaying code is trying to pass "5%"!

The Result: NondeterminismError
Temporal realizes the code has diverged from reality. It throws a NondeterminismError, immediately freezes your workflow, and pages your engineering team. Your workflow is now stuck in limbo because Temporal can no longer trust your code to reconstruct the past.

🛠️ What you must do instead
Being "entirely responsible" means you cannot use Python's native utilities for anything related to time, randomness, or external systems. You must use Temporal's deterministic wrappers, which are designed to return the exact same values during a replay.

Dangerous Native Python	Safe Temporal Equivalent	How Temporal Fixes It
random.randint()	workflow.random().randint() -	Seeds the random generator with a fixed seed based on the Workflow ID, so it yields the exact same "random" sequence during replay.
datetime.now()	workflow.now()	- Records the timestamp of the initial execution in history, and returns that exact same timestamp during replay.
time.sleep(10)	await asyncio.sleep(10) - Temporal hooks into asyncio to turn sleeps into durable, trackable timers rather than blocking the CPU thread.
requests.get()	Put it inside an Activity -	Workflows cannot touch the network. Period. External API calls must live inside Activities, because Temporal logs Activity results to history and skips them during replay.

"""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

from RAG.workflows.activities import ingest_file_activity
from RAG.workflows.ingestion_workflow import IngestionWorkflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    temporal_host = os.getenv("TEMPORAL_HOST", "temporal:7233")
    client = await Client.connect(temporal_host)

    worker = Worker(
        client,
        task_queue="rag-ingestion",
        workflows=[IngestionWorkflow],
        activities=[ingest_file_activity],
        activity_executor=ThreadPoolExecutor(max_workers=5),
        workflow_runner=UnsandboxedWorkflowRunner(),
    )

    logger.info("Temporal worker started on task queue 'rag-ingestion'")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
