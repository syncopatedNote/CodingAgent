# CLAUDE.md — Cortex Agent Platform

## What this project is

A multi-agent AI assistant (called **Cortex**) with:
- A LangGraph **Supervisor Agent** that routes to Search, Coding, KB Search, and General Chat sub-agents
- A **RAG pipeline** (S3 → Temporal worker → ChromaDB summaries + PostgreSQL originals)
- **AG-UI protocol** streaming between the Next.js frontend and the FastAPI backend
- MCP integrations: Atlassian, GitLab, GitHub, Context7

---

## Running the project

```bash
# Start everything
docker compose up -d

# Tail logs for the services you're working on
docker compose logs -f supervisor-api
docker compose logs -f rag-worker
docker compose logs -f rag-service

# Rebuild a single service after code changes
docker compose up -d --build supervisor-api

# Full teardown (keeps volumes)
docker compose down

# Teardown + wipe all persistent data (Postgres, Chroma)
docker compose down -v
```

**Service URLs after startup:**

| Service | URL |
|---|---|
| Agent UI | http://localhost:3000 |
| Supervisor API + Swagger | http://localhost:8000/api/docs |
| RAG Service + Swagger | http://localhost:8001/docs |
| Temporal UI | http://localhost:8080 |
| LiteLLM proxy | http://localhost:4000 |
| ChromaDB | http://localhost:8002 |

**Quick health check:**
```bash
curl http://localhost:8000/api/health
curl http://localhost:8001/health
```

---

## Repository layout

```
Coding_agent/
├── main.py                    # Supervisor API entrypoint (FastAPI)
├── settings.py                # All env vars via pydantic-settings
├── routes/                    # API route handlers (thin — logic lives elsewhere)
│   ├── supervisor_routes.py   # /api/supervisor/chat and /api/supervisor/agent (AG-UI)
│   ├── knowledge_base_routes.py # /api/knowledge-base/agent (AG-UI)
│   ├── documents_routes.py    # /api/documents list + delete
│   └── mcp_routes.py
│
├── agents/                    # Business logic for each agent
│   ├── prompts/               # All supervisor + sub-agent prompts (one module per prompt)
│   ├── supervisor_agent.py    # LangGraph state machine — classify + route
│   ├── search_agent.py        # MCP tool calls (Confluence, Jira, GitLab)
│   ├── kb_search_agent.py     # MultiVectorRetriever → PostgreSQL → LLM
│   ├── langgraph_coding_agent.py  # Jira ticket → code → GitLab
│   ├── general_chat_agent.py  # Direct LLM, no tools
│   └── question_enhancer_agent.py # Rewrites follow-ups from history
│
├── framework_base/            # Shared infrastructure
│   ├── llm_base.py            # LLMFactory — single way to get an LLM instance
│   ├── vector_store.py        # get_vector_store() — ChromaDB client
│   ├── doc_store.py           # get_document_store() — PostgresDocStore (psycopg3)
│   └── mcp_servers/registry.py  # MCP server registration + SSE transport
│
├── ag_ui_middleware/          # AG-UI protocol adapter
│   ├── middleware.py          # AgUIMiddleware.create_response() — wraps any agent fn
│   ├── types.py               # AgentResult, RunContext, InterruptData, ResumeData
│   ├── events.py              # EventFactory helpers
│   └── interrupt.py           # InterruptManager (in-memory interrupt store)
│
├── RAG/
│   ├── main.py                # RAG service entrypoint (FastAPI, port 8001)
│   ├── worker.py              # Temporal worker entrypoint
│   ├── workflows/
│   │   ├── ingestion_workflow.py  # Temporal workflow: download → ingest
│   │   └── activities.py         # Temporal activity: does the actual work
│   ├── loaders/pdf_loader.py  # PDF extract + HyDE vectors + store
│   ├── prompts/               # All RAG prompts (one module per prompt)
│   │   ├── search_queries.py  # SEARCH_QUERIES_PROMPT
│   │   └── search_questions.py # SEARCH_QUESTIONS_PROMPT
│   ├── services/s3_service.py # Presigned URL generation, S3 download
│   ├── routes/upload_routes.py # /upload/* endpoints
│   ├── constants.py           # Metadata keys: ID_KEY, DOC_NAME_KEY, etc.
│   └── utils.py               # extract_text_from_pdf, extract_tables_from_pdf
│
└── Agent_UI/                  # Next.js frontend
    └── src/services/api.js    # HttpAgent (@ag-ui/client) + S3 upload helpers
```

---

## Core conventions

### Settings
All config lives in `settings.py` as a `pydantic-settings` `BaseSettings` class.
Every new env var must be added there with an alias matching the env var name.
Never call `os.getenv()` directly — always import `settings`.

```python
from settings import settings
dsn = settings.postgres_dsn
```

### LLM creation
Always use `LLMFactory`, never instantiate LangChain LLM classes directly.

```python
from framework_base.llm_base import LLMFactory
llm = LLMFactory.create_llm(
    provider=settings.llm_provider,
    model_name=settings.llm_model_name,
    model_type=settings.llm_model_type,
    temperature=0.3,
)
```

### Adding a new AG-UI endpoint
Route handlers are one-liners. The middleware owns all event emission.

```python
from ag_ui_middleware import AgUIMiddleware
from ag_ui_middleware.types import AgentResult, RunContext
from ag_ui.core import RunAgentInput

ag_ui = AgUIMiddleware()

@router.post("/agent")
async def my_agent_endpoint(input_data: RunAgentInput, request: Request):
    async def _agent_fn(user_input, conversation_history, context: RunContext) -> AgentResult:
        result = await my_agent.run(user_input)
        return AgentResult(response=result, metadata={"mode": "my_agent"})
    return ag_ui.create_response(input_data, request, agent_fn=_agent_fn)
```

### Adding a new agent
1. Create `agents/my_agent.py` — business logic only, no HTTP/streaming code
2. Initialize it in `routes/my_routes.py` (or the nearest existing router)
3. Register the router in `main.py` via `app.include_router(...)`
4. If the supervisor should route to it, add a task type in `supervisor_agent.py`

### Prompts

Prompts are Python modules, not inline strings. Each service owns its `prompts/` directory:

| Service | Directory |
|---|---|
| Supervisor agent + all sub-agents (search, general chat, coding, KB search) | `agents/prompts/` |
| RAG (ingestion + retrieval) | `RAG/prompts/` |

One module per prompt, named unambiguously after its purpose. The module exports a single `ALL_CAPS` string constant:

```python
# agents/prompts/classify_task.py
CLASSIFY_TASK_PROMPT = """..."""
```

Import directly — no loader utility needed:

```python
# from an agent file
from agents.prompts.classify_task import CLASSIFY_TASK_PROMPT

# from within the RAG package (relative import)
from ..prompts.search_queries import SEARCH_QUERIES_PROMPT
```

Never define a prompt as an inline string constant inside an agent or loader file.

### RAG metadata schema
All RAG metadata keys are constants in `RAG/constants.py`. Import them everywhere — never hardcode the strings.

```python
from RAG.constants import ID_KEY, DOC_NAME_KEY, INGEST_DATE_KEY, CHUNK_TYPE_KEY, COLLECTION_NAME
```

### PostgreSQL docstore
`get_document_store(collection_name)` returns a `PostgresDocStore`. It takes the DSN from `settings.postgres_dsn`. Values are stored as JSONB dicts; do not store `Document` objects directly — store plain dicts and convert at retrieval time (see `_DocStoreAdapter` in `kb_search_agent.py`).

### Temporal workflows
- Task queue name: `"rag-ingestion"` — worker and client must match
- Activities must be `@activity.defn` decorated, workflows must be `@workflow.defn`
- Workflows must be deterministic: no `datetime.now()`, `random`, or `asyncio.sleep` inside workflow code — use Temporal's APIs instead
- The worker uses `UnsandboxedWorkflowRunner` to allow heavy imports (PyMuPDF, tabula)

---

## Key environment variables

| Variable | Used by | Notes |
|---|---|---|
| `POSTGRES_DSN` | supervisor-api, rag-worker | Full psycopg3 DSN |
| `LLM_PROVIDER` | supervisor-api, rag-worker | `litellm` is default |
| `LLM_MODEL_NAME` | supervisor-api, rag-worker | e.g. `gpt-4o-mini` |
| `LITELLM_PROXY_URL` | supervisor-api, rag-worker | `http://litellm:4000` in Docker |
| `CHROMA_SERVER_HOST` | supervisor-api, rag-worker | `chroma` in Docker, `localhost` locally |
| `TEMPORAL_HOST` | rag-service, rag-worker | `temporal:7233` in Docker |
| `S3_BUCKET_NAME` | rag-service, rag-worker | Upload bucket |
| `RAG_AWS_ACCESS_KEY_ID` | rag-service, rag-worker | Separate from Bedrock credentials |
---

## Gotchas

**ChromaDB `host` in Docker vs local**: Inside Compose it is `chroma`. Outside it is `localhost`. `CHROMA_SERVER_HOST` controls this — don't hardcode it.

**`POSTGRES_DSN` has no default**: The field in `settings.py` has no `default=` — if the env var is missing the app will refuse to start with a validation error. Always set it.

**tabula-py needs Java**: `extract_tables_from_pdf` will throw if Java is absent (e.g. in a minimal Docker image). The loader catches this and continues without tables — check worker logs if tables are missing from ingestion results.

**`_DocStoreAdapter` is read-only**: The adapter in `kb_search_agent.py` that wraps `PostgresDocStore` for `MultiVectorRetriever` intentionally raises `NotImplementedError` on `mset`. Writes go through `pdf_loader.py` directly, not via the retriever's docstore interface.

**Temporal replay safety**: Any code inside a `@workflow.defn` class is replayed on restart. Side-effecting code (S3 calls, DB writes, LLM calls) must live in `@activity.defn` functions, not directly in the workflow body.

**AG-UI interrupt state is in-memory**: `InterruptManager` stores pending interrupts in a dict. They are lost on supervisor-api restart. If the user was mid-interrupt when the pod restarts, the resume call will silently fall back to a fresh run.

**`supervisor-api` mounts the repo as a volume** (`- .:/app`) in Compose. Code changes are reflected immediately for the API — you do not need to rebuild. The rag-worker and rag-service do not have this mount and require `--build`.

---

## Common tasks

**Add a new env var:**
1. Add to `.env` and `.env.example`
2. Add a `Field(alias="MY_VAR")` to `Settings` in `settings.py`
3. Reference via `settings.my_var`

**Trigger a document ingest manually (bypassing the upload UI):**
```bash
# Exec into the rag-worker container
docker compose exec rag-worker python -c "
from RAG.loaders.pdf_loader import ingest_pdf
ingest_pdf('/path/to/file.pdf', 'my-document')
"
```

**Wipe and re-ingest all documents:**
```bash
# Delete via API (removes from both Chroma and Postgres)
curl -X DELETE http://localhost:8000/api/documents/my-document.pdf
```

**Inspect Temporal workflows:**
Open http://localhost:8080 — shows all workflow runs, their history, and activity failures with full stack traces.

**Check what's in the vector store:**
```python
from framework_base.vector_store import get_vector_store
vs = get_vector_store(collection_name="uploads")
print(vs._collection.count())
```

---

## What NOT to do

- Do not call `os.getenv()` — use `settings`
- Do not instantiate `ChatOpenAI`, `ChatBedrock`, etc. directly — use `LLMFactory`
- Do not add business logic in route handlers — keep them as thin wrappers
- Do not put side-effecting code (I/O, LLM calls) inside Temporal workflow classes
- Do not hardcode RAG metadata key strings — import from `RAG/constants.py`
- Do not add defaults to `POSTGRES_DSN` in `settings.py` — it must be explicitly set
- Do not commit real credentials to `.env` — `.env` is gitignored but double-check
- Do not define prompts as inline strings inside agent or loader files — every prompt belongs in the service's `prompts/` directory (`agents/prompts/` or `RAG/prompts/`)

---

## Principles

- Smallest change that solves the issue
- Preserve existing contracts; version breaking changes explicitly
- Keep orchestration (Temporal workflows) deterministic
- Keep route handlers thin — logic belongs in agents or services
- Structured logs with context; no silent exception swallowing
- Never trust model output for critical paths without validation
- Use unambiguous, descriptive names for modules, classes, and variables — avoid generic names (`utils`, `helpers`, `common`, `base`) when a more specific name is available; a reader should know what a module contains from its name alone
- Before implementing any feature that involves changes, always share the complete implementation plan first, for a confirmation, before proceeding.
