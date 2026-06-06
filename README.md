# Cortex - Enterprise AI Assistant System

An intelligent multi-agent AI assistant designed for enterprise environments. It combines a supervisor agent that routes tasks across specialised sub-agents, a fully asynchronous RAG pipeline backed by Temporal, PostgreSQL, and ChromaDB, and deep integrations with Confluence, Jira, GitLab, and GitHub through the Model Context Protocol (MCP).

## Features

### Multi-Agent Architecture
- **Supervisor Agent**: LangGraph-based orchestrator that classifies every request (code generation, search, knowledge-base lookup, general chat) and delegates to the right sub-agent
- **Search Agent**: Searches Confluence, Jira, GitLab, and GitHub via MCP tools
- **Knowledge Base Search Agent**: Runs vector search against ingested documents, fetches original chunks from PostgreSQL, and returns grounded answers with citations
- **Coding Agent**: Reads Jira tickets, generates code, creates branches and merge requests on GitLab via MCP
- **General Chat Agent**: Handles open-ended conversation directly with the LLM
- **Question Enhancer**: Rewrites ambiguous follow-up questions using conversation history before routing

### Document Ingestion & RAG
- **Direct-to-S3 uploads**: Browser gets a presigned POST URL and uploads files directly — no credentials in the browser
- **Temporal workflows**: Durable, retryable ingestion pipelines orchestrated by Temporal; failures replay without re-uploading
- **Multi-vector retrieval**: LLM summaries go to ChromaDB (for semantic search); original chunks go to PostgreSQL (for precise retrieval)
- **PDF processing**: Text extraction via PyMuPDF, table extraction via tabula-py, per-chunk summarisation via LLM
- **Source citations**: Responses include `[Document X, page Y]` references

### Enterprise Integrations via MCP
- **Atlassian**: Confluence pages, Jira tickets, issue search
- **GitLab**: File reads, branch creation, commit, merge requests
- **GitHub**: Repository access, file browsing
- **Context7**: Library documentation lookups

### Frontend ↔ Backend Communication (AG-UI)
- **AG-UI protocol** (`@ag-ui/client`): open event-based standard for streaming agent responses to the UI — typed events replace custom SSE/WebSocket code
- **`AgUIMiddleware`**: custom Python middleware that handles `RUN_STARTED → STEP_STARTED/FINISHED → CUSTOM(metadata) → TEXT_MESSAGE streaming → RUN_FINISHED` lifecycle
- **Interrupt / Resume**: agent can pause mid-run to ask the user a question, preserve its state, and resume exactly where it left off via `forwardedProps.resume`
- **Abort support**: any in-flight stream can be cleanly cancelled from the frontend

### LLM Support
- **LiteLLM proxy** (default): unified gateway supporting OpenAI, GitHub Models, Azure OpenAI, and more
- **AWS Bedrock**: Claude, Titan, Nova models
- **Anthropic direct**, **Google/GCP**, **OpenRouter**, **Ollama** (local)
- Switched at runtime via `LLM_PROVIDER` / `LLM_MODEL_NAME` env vars

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                       Browser  (Agent UI)                            │
│                       Next.js  ·  Port 3000                          │
│                                                                      │
│  HttpAgent (@ag-ui/client)          axios / XHR                      │
│  ┌────────────────────────────┐     ┌──────────────────────────┐    │
│  │ AG-UI event callbacks      │     │ REST / presigned S3 URLs │    │
│  │ · onTextMessageContent     │     └──────────┬───────────────┘    │
│  │ · onCustomEvent(metadata)  │                │                     │
│  │ · onStepStarted/Finished   │                │                     │
│  │ · onRunFinished / onError  │                │                     │
│  │ · onInterrupt → resume     │                │                     │
│  └──────────────┬─────────────┘                │                     │
└─────────────────┼────────────────────────────  ┼ ────────────────────┘
                  │  AG-UI protocol              │  HTTP
                  │  (SSE event stream)          │
       ┌──────────┴──────────┐        ┌──────────┴──────────┐
       │   Supervisor API    │        │    RAG Service       │
       │   FastAPI · 8000    │        │   FastAPI  · 8001    │
       │                     │        │   presigned S3 URLs  │
       │  ┌───────────────┐  │        │   Temporal client    │
       │  │ AgUIMiddleware│  │        └──────────┬───────────┘
       │  │ ─────────────│  │                   │ start workflow
       │  │ RUN_STARTED  │  │                   ▼
       │  │ STEP_START   │  │        ┌──────────────────────┐
       │  │ CUSTOM(meta) │  │        │   Temporal Server    │
       │  │ TEXT chunks  │  │        │      Port 7233       │
       │  │ RUN_FINISHED │  │        │   UI  ·  Port 8080   │
       │  │ (+ interrupt)│  │        └──────────┬───────────┘
       │  └──────┬────────┘  │                   │ task queue
       │         │           │                   ▼
       │  ┌──────▼────────┐  │        ┌──────────────────────┐
       │  │  Supervisor   │  │        │    RAG Worker         │
       │  │   Agent       │  │        │  (Temporal worker)    │
       │  │  (LangGraph)  │  │        │  S3 → PDF extract     │
       │  └──┬──┬──┬──────┘  │        │  LLM summarise        │
       └─────┼──┼──┼─────────┘        │  → Chroma + Postgres  │
             │  │  │                  └──────────┬────────────┘
             │  │  └──────────────┐              │
             │  │                 ▼              │
             │  │    ┌──────────────────────┐    │
             │  │    │  MCP Servers         │    │
             │  │    │  · Atlassian  · 3001 │    │
             │  │    │  · GitLab     · 3333 │    │
             │  │    │  · Context7   · 3003 │    │
             │  │    │  .... and more       │    │
             │  │    └──────────────────────┘    │
             │  │                                │
             │  ▼                                │
             │ ┌──────────────────────────┐      │
             │ │  ChromaDB  ·  Port 8002  │◄─────┘ (summaries + embeddings)
             │ │  collection: "uploads"   │
             │ └──────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────┐
│                  PostgreSQL                      │
│  document_chunks  (JSONB docstore)      ◄── RAG Worker writes chunks
│  Temporal workflow history tables               │
└─────────────────────────────────────────────────┘

LiteLLM Proxy · Port 4000
  Used by supervisor-api and rag-worker
  Backed by GitHub Models / OpenAI / Azure / Bedrock

AWS S3
  Browser uploads directly via presigned POST URLs
  RAG Worker downloads for processing
```

### Document Ingestion Flow

```
1. Browser  →  POST /upload/presigned-url     (get S3 presigned POST)
2. Browser  →  PUT  s3://bucket/uploads/…     (direct upload, no creds in browser)
3. Browser  →  POST /upload/complete          (notify RAG service)
4. RAG Svc  →  Temporal: start IngestionWorkflow(bucket, object_key)
5. Worker   →  S3 download → PDF extract (PyMuPDF + tabula)
6. Worker   →  LLM summarise each chunk / table
7. Worker   →  ChromaDB  ← summaries + embeddings
8. Worker   →  PostgreSQL ← original chunks (JSONB)
```

### Knowledge-Base Query Flow

```
User query
  → KBSearchAgent
  → ChromaDB vector search  (top-k summaries)
  → PostgreSQL docstore      (fetch original chunks by doc_id)
  → LLM: synthesise answer with citations [Document X, page Y]
```

---

## AG-UI Protocol

The frontend and backend communicate exclusively through the **AG-UI protocol** — an open, event-based standard that defines how AI agents stream structured events to user interfaces. This replaces ad-hoc SSE/WebSocket implementations with a typed event contract both sides agree on.

### What AG-UI provides

| Concern | Without AG-UI | With AG-UI |
|---|---|---|
| Streaming text | Custom chunked SSE parsing | `TEXT_MESSAGE_CONTENT` delta events |
| Run lifecycle | Manual start/end signals | `RUN_STARTED` / `RUN_FINISHED` events |
| Agent steps | Not visible to UI | `STEP_STARTED` / `STEP_FINISHED` events |
| Metadata (task type, etc.) | Separate REST call | `CUSTOM` event with named payload |
| Agent interrupts | Not supported | `RUN_FINISHED{outcome:"interrupt"}` + resume |
| Aborting a run | Kill connection, undefined state | `abortController.abort()` — clean teardown |

### How it is wired in this project

**Backend — `ag_ui_middleware/middleware.py`**

A custom `AgUIMiddleware` class wraps any agent callable and manages the full run lifecycle, producing a `StreamingResponse` from FastAPI:

```
RUN_STARTED
  └─ STEP_STARTED("processing")
       └─ [agent executes]
  └─ STEP_FINISHED("processing")
  └─ CUSTOM("task_analysis", {task_type, …})   ← metadata
  └─ TEXT_MESSAGE_START
       └─ TEXT_MESSAGE_CONTENT × N             ← word-by-word streaming
  └─ TEXT_MESSAGE_END
RUN_FINISHED                                   ← outcome: "success" or "interrupt"
```

Any API endpoint becomes a one-liner:

```python
from ag_ui_middleware import AgUIMiddleware

ag_ui = AgUIMiddleware()

@router.post("/agent")
async def supervisor_agent_endpoint(input_data: RunAgentInput, request: Request):
    return ag_ui.create_response(input_data, request, agent_fn=my_agent_fn)
```

The agent callable just returns an `AgentResult` — it never touches SSE or encoding:

```python
async def my_agent_fn(user_input, conversation_history, context) -> AgentResult:
    response = await supervisor_agent.run(user_input, conversation_history)
    return AgentResult(response=response, metadata={"task_type": "search"})
```

**Frontend — `Agent_UI/src/services/api.js`**

`HttpAgent` from `@ag-ui/client` connects to the backend endpoint and fires typed callbacks:

```js
import { HttpAgent } from "@ag-ui/client";

const agent = new HttpAgent({ url: `${API_BASE_URL}/api/supervisor/agent` });
agent.messages = aguiMessages;   // full conversation history
agent.threadId  = sessionId;

agent.runAgent({ runId, tools: [], forwardedProps }, {
  onTextMessageContentEvent: ({ event }) => appendDelta(event.delta),
  onCustomEvent:             ({ event }) => setMetadata(event.value),
  onStepStartedEvent:        ({ event }) => showStep(event.stepName),
  onRunFinishedEvent:        ({ event }) => {
    if (event.outcome === "interrupt") handleInterrupt(event.interrupt);
    else markDone();
  },
  onRunErrorEvent:           ({ event }) => showError(event.message),
});
```

### Interrupt / Resume flow

When the coding agent needs user confirmation (e.g. "create this branch?"), it returns an `AgentResult` with an `InterruptData` payload. The middleware stores the in-flight state, and emits `RUN_FINISHED{outcome:"interrupt"}`. The frontend renders the question and, on user response, sends a new run with `forwardedProps.resume = { interruptId, payload }`. The middleware resolves the stored state and passes `context.is_resume = True` to the agent callable — no extra endpoints needed.

```
Agent needs input
  → backend: InterruptManager.create(thread_id, interrupt, agent_state)
  → frontend: onInterrupt({id, reason, payload})  ← show question to user

User answers
  → frontend: runAgentChat(messages, threadId, callbacks,
               { resume: { interruptId, answer } })
  → backend:  InterruptManager.resolve(thread_id, interrupt_id)
  → agent callable receives context.is_resume = True
```

---

## Services

| Service | Port | Description |
|---|---|---|
| agent-ui | 3000 | Next.js frontend |
| supervisor-api | 8000 | FastAPI — supervisor agent, search, docs management |
| rag-service | 8001 | FastAPI — S3 presigned URLs, workflow trigger |
| litellm | 4000 | LiteLLM proxy (OpenAI-compatible gateway) |
| chroma | 8002 | ChromaDB vector store |
| temporal | 7233 | Temporal workflow server (gRPC) |
| temporal-ui | 8080 | Temporal web UI |
| postgresql | 5432 | Docstore + Temporal backend |
| mcp-atlassian | 3001 | MCP — Confluence & Jira |
| mcp-gitlab | 3333 | MCP — GitLab |
| mcp-context7 | 3003 | MCP — library docs |
| rag-worker | — | Temporal worker (no exposed port) |

---

## Prerequisites

- **Docker & Docker Compose** v2+
- **Python 3.11+** (local dev only)
- AWS account with an S3 bucket (for document uploads)
- API keys for your chosen LLM provider

---

## Quick Start

### Docker Compose (recommended)

```bash
git clone <repository-url>
cd Coding_agent

cp .env.example .env
# Edit .env — minimum required: LLM keys, AWS/S3 credentials, POSTGRES_DSN

docker compose up -d
```

Services available after startup:

| URL | Description |
|---|---|
| http://localhost:3000 | Agent UI |
| http://localhost:8000/api/docs | Supervisor API (Swagger) |
| http://localhost:8001/docs | RAG Service (Swagger) |
| http://localhost:8080 | Temporal UI |
| http://localhost:4000 | LiteLLM proxy |

### Verify everything is running

```bash
docker compose ps
docker compose logs -f supervisor-api
docker compose logs -f rag-worker

# Health checks
curl http://localhost:8000/api/health
curl http://localhost:8001/health
```

---

## Configuration

Copy `.env.example` to `.env` and fill in values. Key variables:

```env
# ── LLM ──────────────────────────────────────────────────────
LLM_PROVIDER=litellm          # litellm | openai | bedrock | anthropic | azure | ollama
LLM_MODEL_NAME=gpt-4o-mini
LLM_MODEL_TYPE=chat

LITELLM_PROXY_URL=http://litellm:4000
LITELLM_MASTER_KEY=sk-1234

# ── Database ─────────────────────────────────────────────────
POSTGRES_DSN=postgresql://appname:apppassword@postgresql:port/app  #pragma: allowlist secret

# ── Vector store ─────────────────────────────────────────────
CHROMA_SERVER_HOST=chroma
CHROMA_SERVER_HTTP_PORT=8000

# ── RAG / S3 ─────────────────────────────────────────────────
RAG_AWS_ACCESS_KEY_ID=...
RAG_AWS_SECRET_ACCESS_KEY=...
RAG_AWS_REGION=us-east-1
S3_BUCKET_NAME=your-bucket-name

# ── Temporal ─────────────────────────────────────────────────
TEMPORAL_HOST=temporal:7233

# ── Enterprise integrations ──────────────────────────────────
CONFLUENCE_URL=https://your-company.atlassian.net/wiki
CONFLUENCE_USERNAME=you@company.com
CONFLUENCE_API_TOKEN=...

JIRA_URL=https://your-company.atlassian.net
JIRA_PERSONAL_TOKEN=...

GITLAB_PERSONAL_ACCESS_TOKEN=...
GITLAB_API_URL=https://gitlab.example.com
GITLAB_PROJECT_ID=...

GITHUB_TOKEN=...

# ── MCP toggles ──────────────────────────────────────────────
MCP_ATLASSIAN_ENABLED=true
MCP_GITLAB_ENABLED=true
MCP_GITHUB_ENABLED=true
MCP_CONTEXT7_ENABLED=true

# ── LangSmith tracing (optional) ─────────────────────────────
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=coding_agent
```

---

## API Reference

### Supervisor chat

```bash
curl -X POST http://localhost:8000/api/supervisor/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "Find ticket PROJ-123",
    "session_id": "my-session"
  }'
```

With conversation history:

```bash
curl -X POST http://localhost:8000/api/supervisor/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "Tell me more about it",
    "conversation_history": [
      {"role": "user",      "content": "What is PROJ-123?"},
      {"role": "assistant", "content": "PROJ-123 is..."}
    ],
    "session_id": "my-session"
  }'
```

### Knowledge base search

```bash
curl -X POST http://localhost:8000/api/knowledge-base/agent \
  -H "Content-Type: application/json" \
  -d '{"query": "deployment checklist"}'
```

### Document management

```bash
# List ingested documents
curl http://localhost:8000/api/documents

# Delete a document (removes from Chroma + PostgreSQL)
curl -X DELETE "http://localhost:8000/api/documents/my-doc.pdf"
```

### Document upload (RAG pipeline)

```bash
# 1. Request a presigned upload URL
curl -X POST http://localhost:8001/upload/presigned-url \
  -H "Content-Type: application/json" \
  -d '{"filename": "spec.pdf", "content_type": "application/pdf"}'

# 2. Upload directly to S3 using the fields returned above (multipart/form-data)

# 3. Notify the RAG service to start ingestion
curl -X POST http://localhost:8001/upload/complete \
  -H "Content-Type: application/json" \
  -d '{"object_key": "uploads/<uuid>/spec.pdf"}'

# 4. Poll workflow status
curl http://localhost:8001/upload/status/<workflow-id>
```

### Python client example

```python
import requests

resp = requests.post(
    "http://localhost:8000/api/supervisor/chat",
    json={"user_input": "Search for deployment docs", "session_id": "py-1"}
)
data = resp.json()
print(data["task_analysis"]["task_type"])  # SEARCH_OPERATION
print(data["response"])
```

---

## Project Structure

```
Coding_agent/
├── agents/
│   ├── supervisor_agent.py          # LangGraph orchestrator — classifies & routes
│   ├── search_agent.py              # MCP-backed search (Confluence, Jira, GitLab)
│   ├── kb_search_agent.py           # RAG search — Chroma + PostgreSQL docstore
│   ├── langgraph_coding_agent.py    # Code generation via MCP (GitHub/GitLab)
│   ├── general_chat_agent.py        # Direct LLM conversation
│   ├── question_enhancer_agent.py   # Rewrites follow-up questions from history
│   ├── components/                  # Handler modules per integration
│   │   ├── jira_handler.py
│   │   ├── confluence_handler.py
│   │   ├── gitlab_handler.py
│   │   └── code_generator.py
│   └── models/
│       └── jira_response_model.py
│
├── framework_base/
│   ├── llm_base.py                  # LLMFactory — provider-agnostic LLM creation
│   ├── vector_store.py              # ChromaDB client initialisation
│   ├── doc_store.py                 # PostgresDocStore (psycopg3, JSONB)
│   └── mcp_servers/
│       └── registry.py              # MCP server registration & SSE transport
│
├── RAG/
│   ├── main.py                      # RAG service FastAPI app
│   ├── worker.py                    # Temporal worker entry point
│   ├── ingest.py                    # Ingestion dispatcher (PDF, text)
│   ├── constants.py                 # Metadata key constants
│   ├── settings.py                  # RAG-specific settings (S3, Temporal)
│   ├── loaders/
│   │   └── pdf_loader.py            # PyMuPDF + tabula extraction, LLM summarisation
│   ├── services/
│   │   └── s3_service.py            # Presigned URL generation, S3 download
│   ├── routes/
│   │   └── upload_routes.py         # /upload/* endpoints
│   ├── workflows/
│   │   ├── ingestion_workflow.py    # Temporal workflow definition
│   │   └── activities.py           # Temporal activity (download → extract → store)
│   ├── Dockerfile                   # RAG service image
│   └── Dockerfile.rag_worker        # Temporal worker image
│
├── routes/
│   ├── supervisor_routes.py         # POST /api/supervisor/agent  (AG-UI)
│   ├── documents_routes.py          # GET/DELETE /api/documents
│   ├── knowledge_base_routes.py     # POST /api/knowledge-base/agent  (AG-UI)
│   └── mcp_routes.py               # MCP tool discovery
│
├── ag_ui_middleware/
│   ├── middleware.py                # AgUIMiddleware — run lifecycle, text streaming
│   ├── events.py                    # EventFactory helpers (typed AG-UI events)
│   ├── interrupt.py                 # InterruptManager — stores/resolves pending interrupts
│   └── types.py                     # AgentResult, RunContext, InterruptData, ResumeData
│
├── Agent_UI/                        # Next.js frontend
│   ├── src/services/api.js          # HttpAgent (@ag-ui/client) + S3 upload helpers
│   ├── src/app/page.js              # Main chat page — streams AG-UI events
│   ├── src/app/knowledge-base/      # Knowledge base search page
│   ├── src/app/upload/              # Document upload page
│   └── Dockerfile
│
├── main.py                          # Supervisor API FastAPI app
├── settings.py                      # Global settings (pydantic-settings)
├── logger.py
├── requirements.txt
├── docker-compose.yml
├── dockerfile.api                   # Supervisor API image
├── litellm_config.yaml              # LiteLLM model routing config
├── .env.example
└── README.md
```

---

## LLM Provider Configuration

The `LLMFactory` in `framework_base/llm_base.py` supports:

```python
from framework_base.llm_base import LLMFactory

# Via LiteLLM proxy (default)
llm = LLMFactory.create_llm(provider="litellm", model_name="gpt-4o-mini")

# OpenAI directly
llm = LLMFactory.create_llm(provider="openai", model_name="gpt-4o")

# AWS Bedrock
llm = LLMFactory.create_llm(provider="bedrock", model_name="us.amazon.nova-lite-v1:0")

# Local Ollama
llm = LLMFactory.create_llm(provider="ollama", model_name="llama3:8b",
                             base_url="http://localhost:11434")
```

LiteLLM model routing is defined in `litellm_config.yaml`. Default models: `gpt-4o`, `gpt-4o-mini`, `o1-preview`, `o1-mini` — all via GitHub Models.

---

## Document Store

`framework_base/doc_store.py` provides a `PostgresDocStore` keyed by document ID. Original document chunks are stored as JSONB and retrieved after a vector search returns matching summaries:

```python
from framework_base.doc_store import get_document_store

store = get_document_store(collection_name="uploads")

# Write chunks
store.mset([("chunk-id-1", {"type": "text", "content": "...", "page": 1})])

# Read back
chunks = store.mget(["chunk-id-1"])
```

The DSN is sourced from `settings.postgres_dsn` (`POSTGRES_DSN` env var).

---

## Temporal Workflows

Document ingestion is orchestrated by Temporal to guarantee durability. If the worker crashes mid-way, Temporal replays the workflow from the last completed activity.

```
Workflow:  IngestionWorkflow(bucket, object_key)
Activities:
  1. download_from_s3(bucket, object_key)        → local temp file
  2. run_ingestion(file_path, object_key)         → extract + summarise + store
Task queue: "rag-ingestion"
```

Monitor workflows in the Temporal UI at http://localhost:8080.

---

## Troubleshooting

**rag-worker fails to connect to PostgreSQL**
Make sure `POSTGRES_DSN` is set in `.env` and the `postgresql` service is healthy before the worker starts.

**Temporal workflows stuck in "Running"**
Check `docker compose logs rag-worker`. Common cause: missing S3 credentials or the LiteLLM proxy not yet ready.

**ChromaDB connection refused**
`CHROMA_SERVER_HOST` must be `chroma` (the Docker service name) when running inside Compose, not `localhost`.

**MCP tools unavailable**
Verify the corresponding `MCP_*_ENABLED` flag is `true` and the MCP container has passed its healthcheck (`docker compose ps`).

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes
4. Open a pull request

## License

MIT License — see the LICENSE file for details.

## Acknowledgements

- **LangChain / LangGraph** — agent orchestration and RAG tooling
- **Temporal** — durable workflow engine
- **FastAPI** — REST API framework
- **ChromaDB** — vector database
- **PostgreSQL + psycopg** — document chunk store
- **LiteLLM** — unified LLM proxy
- **AG-UI Protocol** — open event-based standard for agent-to-UI communication
- **Model Context Protocol (MCP)** — extensible tool integration
