# Development Guidelines — Cortex Agent Platform

> **Audience:** an autonomous coding agent generating code for this repository.
> These are your authoritative system instructions. Follow them exactly when
> writing or modifying code. They override any general assumptions you hold
> about how a Python project "usually" works.

---

## 1. What this project is

A multi-agent AI assistant (called **Cortex**) built on FastAPI + LangGraph:

- A LangGraph **Supervisor Agent** that classifies each request and routes to
  one of four sub-agents: **Search**, **Coding**, **KB Search**, **General Chat**.
- A **Sprint Start Agent** triggered by a Jira `sprint_started` webhook that
  autonomously drives the coding pipeline for every open ticket in the sprint.
- A **RAG pipeline** (document ingestion → pgvector summaries + PostgreSQL
  originals) exposed as a separate service.
- **AG-UI protocol** streaming between the Next.js frontend and the backend.
- **MCP integrations**: Atlassian, GitLab, GitHub, Context7.

---

## 2. Repository structure

```
Coding_agent/
├── main.py                    # Supervisor API entrypoint (FastAPI app)
├── settings.py                # ALL env vars via pydantic-settings (single source)
│
├── routes/                    # API route handlers — THIN wrappers only
│   ├── supervisor_routes.py   # /api/supervisor/* (AG-UI)
│   ├── knowledge_base_routes.py
│   ├── documents_routes.py
│   ├── sprint_routes.py       # /api/sprint/webhook/jira
│   └── mcp_routes.py
│
├── agents/                    # Business logic for each agent (no HTTP code)
│   ├── prompts/               # ALL prompts — one SUBDIR per agent, one MODULE per prompt
│   │   ├── coding_supervisor/ # autonomous.py, generate_code.py, review_code.py, ...
│   │   ├── context_collector/ # autonomous.py, nudge.py, system.py
│   │   ├── general_chat/
│   │   ├── kb_search/
│   │   ├── main_supervisor/
│   │   ├── question_enhancer/
│   │   └── search/
│   ├── coding_pipeline/       # Context collector → coding agent pipeline
│   │   ├── coding_pipeline.py # CodingPipeline — chains collector → coding agent
│   │   ├── common_helpers.py  # Shared prune / tool-retry / llm-retry functions
│   │   ├── coding_agent/      # generate → review → push agent
│   │   │   ├── langgraph_coding_agent.py
│   │   │   ├── custom_tools.py            # generate_code, review_code, select_tools
│   │   │   └── coding_llm_singleton.py    # Module-level codegen LLM (temp=0.3)
│   │   └── collector_agent/   # Gathers context into a ContextBundle
│   │       ├── context_collector_agent.py
│   │       ├── context_bundle.py          # ContextBundle dataclass (the hand-off)
│   │       ├── collector_tools.py         # ask_user + submit_context
│   │       ├── mcp_fetch.py
│   │       ├── jira_collector.py
│   │       ├── confluence_collector.py
│   │       ├── gitlab_collector.py
│   │       └── github_collector.py
│   ├── models/                # Pydantic response models
│   ├── supervisor_agent.py    # LangGraph state machine — classify + route
│   ├── search_agent.py
│   ├── kb_search_agent.py
│   ├── sprint_start_agent.py
│   ├── general_chat_agent.py
│   └── question_enhancer_agent.py
│
├── framework_base/            # Shared infrastructure (factories + registries)
│   ├── llm_base.py            # LLMFactory — the ONLY way to build an LLM
│   ├── llm_providers/         # ONE module per LLM provider
│   │   ├── anthropic_provider.py   azure_provider.py   bedrock_provider.py
│   │   ├── gcp_provider.py         litellm_provider.py ollama_provider.py
│   │   ├── openai_provider.py      openrouter_provider.py
│   ├── reranker.py            # RerankerFactory — create_reranker()
│   ├── vector_store.py        # get_vector_store() — PGVector (sync + async modes)
│   ├── doc_store.py           # get_document_store() — PostgresDocStore
│   └── mcp_servers/
│       ├── registry.py        # MCPServerRegistry — registration + discovery
│       ├── base_server.py     # MCPServerConfig base class
│       ├── multi_server_mcp_client.py
│       └── servers/           # ONE module per MCP server
│           ├── atlassian.py   context7.py   github.py   gitlab.py
│
├── ag_ui_middleware/          # AG-UI protocol adapter (event emission)
├── RAG/                       # RAG service — separate FastAPI app + Temporal worker
│   └── prompts/               # RAG prompts live HERE, not under agents/prompts
└── Agent_UI/                  # Next.js frontend
```

---

## 3. Main components & flows

- **Request flow:** `routes/*` (thin) → `agents/*` (logic) → `framework_base/*`
  (LLM, MCP, stores). Route handlers must contain no business logic.
- **Supervisor flow:** `supervisor_agent.py` classifies the task, then routes to
  the matching sub-agent. To add a new destination, add a task type there.
- **Coding pipeline flow:** `CodingPipeline.run()` chains two agents:
  1. `ContextCollectorAgent` — gathers requirements/design/guidelines into a
     `ContextBundle`. **Only this agent may interrupt** (to ask the user).
  2. `LangGraphCodingAgent` — consumes the bundle and runs a pure
     **generate → review → push** loop with no further context gathering.
  Both use the same **supervisor → tools → supervisor → … → END** hub-and-spoke
  graph. The coding agent must call `select_tools("github"/"gitlab")` before
  using that server's MCP tools.
- **Sprint flow:** Jira webhook → fetch open tickets → run `CodingPipeline` in
  `autonomous` mode per ticket (no human prompts; a blocked ticket returns a
  parseable `FAILURE:` report).

### Class structure conventions
- Each agent is a class in its own module under `agents/`, exposing an async
  `run(...)` entry point and holding its own graph/state. No HTTP or streaming
  code inside agent classes.
- LangGraph state is a `TypedDict`; graphs compile with a `MemorySaver`
  checkpointer. Keep nodes small and single-purpose.
- Shared, fiddly logic (message pruning, tool/LLM retry) lives as plain
  functions in `agents/coding_pipeline/common_helpers.py` — not a base class.

---

## 4. Extending factory-backed services

Always go through the existing factory/registry — never instantiate the
underlying library class directly.

### LLM creation
```python
from framework_base.llm_base import LLMFactory
llm = LLMFactory.create_llm(
    provider=settings.llm_provider,
    model_name=settings.llm_model_name,
    model_type=settings.llm_model_type,
    temperature=0.3,
)
```

### Add a new LLM provider
1. Create `framework_base/llm_providers/my_provider.py` with a factory function
   `create_my_provider(model_name, temperature, max_tokens, **kwargs)`.
2. Register it in `framework_base/llm_base.py`'s `providers_map` inside
   `LLMFactory.create_llm`.
3. Add any required API-key env vars to `settings.py`.

### Add a new MCP server
1. Create `framework_base/mcp_servers/servers/my_server.py` extending
   `MCPServerConfig`.
2. Register it in `framework_base/mcp_servers/registry.py`'s
   `_auto_register_servers()`.
3. Add URL and enable-flag env vars to `settings.py`.

### Reranker / vector store / doc store
- `RerankerFactory.create_reranker()` (`framework_base/reranker.py`) returns a
  `BaseDocumentCompressor`.
- `get_vector_store(collection_name, async_mode=...)` (`vector_store.py`) returns
  a `PGVector`. Use `async_mode=True` for async callers, `False` for sync
  ingestion — mixing them causes greenlet errors.
- `get_document_store(collection_name)` (`doc_store.py`) returns a
  `PostgresDocStore`; store plain JSONB dicts, not `Document` objects.

### Settings
All config lives in `settings.py` as a `pydantic-settings` `BaseSettings`.
Every new env var gets a `Field(alias="ENV_VAR_NAME")`. Read it via
`from settings import settings`. **Never call `os.getenv()`.**

### Prompts
Prompts are Python modules, never inline strings. Each agent owns a subdirectory
under `agents/prompts/`; RAG prompts live under `RAG/prompts/`. One module per
prompt, exporting a single `ALL_CAPS` string constant:
```python
# agents/prompts/coding_supervisor/review_code.py
REVIEW_CODE_PROMPT = """..."""
```
Import directly: `from agents.prompts.coding_supervisor.review_code import REVIEW_CODE_PROMPT`.

### Add a new agent
1. Create `agents/my_agent.py` — business logic only.
2. Wire it into `routes/my_routes.py` (or the nearest router).
3. Register the router in `main.py` via `app.include_router(...)`.
4. If the supervisor should route to it, add a task type in `supervisor_agent.py`.

---

## 5. Where each kind of logic goes

| Kind of code | Directory |
|---|---|
| New LLM provider | `framework_base/llm_providers/` |
| New MCP server config | `framework_base/mcp_servers/servers/` |
| Reranker / vector store / doc store infra | `framework_base/` |
| Agent business logic | `agents/<name>_agent.py` (or a package) |
| A prompt for an agent | `agents/prompts/<agent>/<purpose>.py` |
| A RAG prompt | `RAG/prompts/<purpose>.py` |
| Pydantic response models | `agents/models/` |
| API route handlers (thin) | `routes/` |
| AG-UI event/streaming glue | `ag_ui_middleware/` |
| Env var declarations | `settings.py` |

Route handlers stay thin — push all logic down into an agent or a
`framework_base` helper.

---

## 6. Naming conventions

- Names must be **unambiguous and descriptive** — a reader should know what a
  module/class/function contains from its name alone.
- **Avoid generic names** (`utils`, `helpers`, `common`, `base`, `manager`,
  `data`) when a specific name exists. Prefer `mcp_fetch.py` over `helpers.py`,
  `context_bundle.py` over `models.py`.
- Modules: `snake_case.py`. Classes: `PascalCase`. Functions/vars: `snake_case`.
- Prompt constants: `ALL_CAPS`, named after their purpose
  (`REVIEW_CODE_PROMPT`), in a module named after the same purpose.
- Provider factory functions: `create_<provider>` (e.g. `create_anthropic`).
- Test files: `test_<module_name>.py` (see §8).

---

## 7. Security review (mandatory)

Before completing any change, review the generated code for security
vulnerabilities and fix every issue found:
- No secrets, API keys, tokens, or credentials hardcoded — read them from
  `settings`.
- Validate and sanitize all external input (webhook payloads, MCP/tool results,
  user prompts). Never trust model output on a critical path without validation.
- Guard against injection (SQL, command, prompt), path traversal, and SSRF when
  building URLs/queries from input.
- Enforce signature/auth checks where the codebase already does (e.g. the Jira
  webhook HMAC validation).
- No silent exception swallowing — log with context; fail loudly on critical
  paths.
- Never log secrets or full credential-bearing payloads.

---

## 8. Unit tests (mandatory for all impacted modules)

Write unit tests for every new or modified module.

- **If a `tests/` directory does not exist at the repo root, create it.**
- The `tests/` tree **mirrors the main repository directory structure.** A test
  for a module lives at the **same relative path / directory level** as that
  module, under `tests/`. Examples:
  - `framework_base/llm_providers/my_provider.py`
    → `tests/framework_base/llm_providers/test_my_provider.py`
  - `agents/coding_pipeline/collector_agent/context_bundle.py`
    → `tests/agents/coding_pipeline/collector_agent/test_context_bundle.py`
  - `agents/supervisor_agent.py`
    → `tests/agents/test_supervisor_agent.py`
- Name test files `test_<module_name>.py`. Mock external services (LLM calls,
  MCP servers, Postgres) — tests must not require live infrastructure.
- Cover the happy path plus the edge/failure cases the module is meant to
  handle.

---

## 9. After implementation — update this file

After the **3 generate–review cycles are complete**, update `robots.md` with any
new feature information so it stays the accurate source of truth:
- New agents, providers, MCP servers, factories, or directories.
- New conventions, env vars, or flows introduced by the change.
Keep the additions concise and in the existing section structure.

---

## What NOT to do

- Do not call `os.getenv()` — use `settings`.
- Do not instantiate `ChatOpenAI`, `ChatBedrock`, etc. directly — use `LLMFactory`.
- Do not bypass the MCP registry — register servers, don't hand-roll clients.
- Do not put business logic in route handlers.
- Do not define prompts as inline strings inside agent files.
- Do not hardcode constants that are defined elsewhere — import them.
- Do not add a default to `POSTGRES_DSN` in `settings.py` — it must be set explicitly.
- Do not use generic module names when a specific one fits.
- Do not skip tests or the security review for a change.

---

## Principles

- Smallest change that solves the issue.
- Preserve existing contracts; version breaking changes explicitly.
- Keep route handlers thin — logic belongs in agents or `framework_base`.
- Structured logs with context; no silent exception swallowing.
- Never trust model output for critical paths without validation.
- Use unambiguous, descriptive names — never a generic name when a specific one exists.
- For any multi-file feature, share the implementation plan first for confirmation before proceeding.
