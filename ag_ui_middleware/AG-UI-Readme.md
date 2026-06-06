# AG-UI Integration Guide

This guide is split into two parts:
- Part I: AG-UI protocol concepts (spec-level)
- Part II: How this repository implements those concepts

## Part I: AG-UI Protocol (Spec-Level)

## 1) What AG-UI is

AG-UI is an event-based protocol for agent execution. A single run can emit a sequence of events before completion, instead of returning one final payload.

## 2) Core objects

`RunAgentInput` — the POST body sent to any AG-UI endpoint — contains:

- `threadId`: conversation identity across runs.
- `runId`: identity of one run inside a thread.
- `parentRunId` *(optional)*: links sub-runs to a parent run.
- `messages`: input conversation turns supplied by the client.
- `state`: arbitrary agent state passed back from the client.
- `tools`: tool definitions available to the agent for this run.
- `context`: additional context items (documents, metadata) for the run.
- `forwardedProps`: opaque extension bag passed through without interpretation.
- `resume` *(optional)*: array of interrupt resolutions — see Section 4.

`subscriber` (client SDK concept, not a protocol field): the client-side handler object whose methods are called as events arrive.

## 3) Complete event type reference

AG-UI defines the following event categories (all values from the `EventType` enum):

- **Run lifecycle**: `RUN_STARTED`, `RUN_FINISHED`, `RUN_ERROR`
- **Text streaming**: `TEXT_MESSAGE_START`, `TEXT_MESSAGE_CONTENT`, `TEXT_MESSAGE_END`
- **Tool calls**: `TOOL_CALL_START`, `TOOL_CALL_ARGS`, `TOOL_CALL_END`, `TOOL_CALL_RESULT`
- **Steps**: `STEP_STARTED`, `STEP_FINISHED`
- **State**: `STATE_SNAPSHOT`, `STATE_DELTA`
- **Message history**: `MESSAGES_SNAPSHOT`
- **Activity**: `ACTIVITY_SNAPSHOT`, `ACTIVITY_DELTA`
- **Reasoning** (extended thinking): `REASONING_START`, `REASONING_MESSAGE_START`, `REASONING_MESSAGE_CONTENT`, `REASONING_MESSAGE_END`, `REASONING_MESSAGE_CHUNK`, `REASONING_END`, `REASONING_ENCRYPTED_VALUE`
- **Custom / passthrough**: `CUSTOM`, `RAW`

AG-UI uses SSE (Server-Sent Events) as its transport. The response `Content-Type` is negotiated via the `Accept` header using the `EventEncoder` helper (Python SDK) or equivalent in other SDKs.

## 4) Interrupt and resume (spec concept)

When a run pauses for human input, the agent emits `RUN_FINISHED` with a structured interrupt outcome:

```json
{
  "type": "RUN_FINISHED",
  "threadId": "...",
  "runId": "...",
  "outcome": {
    "type": "interrupt",
    "interrupts": [
      {
        "id": "int-abc123",
        "reason": "input_required",
        "message": "Please confirm this action",
        "responseSchema": { "type": "object", "properties": { "approved": { "type": "boolean" } } }
      }
    ]
  }
}
```

The client resumes by sending a new `RunAgentInput` with the top-level `resume` field — an array of interrupt resolutions:

```json
{
  "threadId": "...",
  "runId": "...",
  "messages": [...],
  "resume": [
    { "interruptId": "int-abc123", "status": "resolved", "payload": { "approved": true } }
  ]
}
```

`status` may be `"resolved"` or `"cancelled"`.

## Part II: This Repository (Implementation-Level)

## 5) Frontend implementation

File: `Agent_UI/src/services/api.js`

- Uses `@ag-ui/client` `HttpAgent`.
- Primary function: `runAgentChat(messages, threadId, callbacks, options = {})`.
- Default endpoint: `${API_BASE_URL}/api/supervisor/agent`.
- Endpoint override: `options.agentUrl`.
- Resume payload location: `forwardedProps.resume`.

Current call pattern (abridged — see `api.js` for full subscriber and abort wiring):

```javascript
export const runAgentChat = (messages, threadId, callbacks, options = {}) => {
  const endpointUrl = options.agentUrl ?? `${API_BASE_URL}/api/supervisor/agent`;

  const abortController = new AbortController();
  const agent = new HttpAgent({ url: endpointUrl });
  agent.threadId = threadId;
  agent.messages = messages;

  const runId = `run-${Date.now()}`;

  // NOTE: the AG-UI spec places resume at the top level of RunAgentInput.
  // This repo passes it via forwardedProps instead, which the backend
  // middleware reads from input_data.forwarded_props["resume"].
  const forwardedProps = {};
  if (options.resume) {
    forwardedProps.resume = options.resume;
  }

  agent
    .runAgent(
      { runId, tools: [], context: [], forwardedProps, abortController },
      subscriber,
    )
    .catch((err) => onError?.(err));
};
```

A dedicated `resumeAgent(messages, threadId, interruptId, payload, callbacks)` export wraps `runAgentChat` with the resume payload pre-filled.

## 6) Backend middleware implementation

File: `ag_ui_middleware/middleware.py`

`AgUIMiddleware` emits:
- `RUN_STARTED`
- `STEP_STARTED` / `STEP_FINISHED`
- optional `CUSTOM` event (`task_analysis` by default)
- `TEXT_MESSAGE_START` → `TEXT_MESSAGE_CONTENT` → `TEXT_MESSAGE_END`
- `RUN_FINISHED` on success
- `RUN_FINISHED` with an interrupt outcome when paused for user input
- `RUN_ERROR` on exceptions

**Interrupt outcome format note**: the AG-UI spec encodes the interrupt as a structured `outcome` object (`{type: "interrupt", interrupts: [...]}` — see Section 4). The current frontend subscriber reads `event.outcome === "interrupt"` (string comparison) and `event.interrupt` (singular object), which is a repo-specific encoding that diverges from the standard spec shape. The backend middleware must emit matching fields for the frontend to handle interrupts correctly.

Resume handling in this repo:
- Checks `input_data.forwarded_props["resume"]` (the repo routes resume via `forwardedProps` rather than the spec's top-level `resume` field).
- Resolves pending interrupt via `InterruptManager`.
- Builds `RunContext(is_resume=True, resume_data=..., saved_state=...)`.

## 7) Endpoint wiring in this repo

- Supervisor AG-UI endpoint: `/api/supervisor/agent`
  - file: `routes/supervisor_routes.py`
- Knowledge base AG-UI endpoint: `/api/knowledge-base/agent`
  - file: `routes/knowledge_base_routes.py`

Knowledge-base UI path uses `runKbSearchAgentChat(...)`, which is a thin wrapper around `runAgentChat(...)` with `options.agentUrl` set.

### Knowledge-base endpoint details (`/api/knowledge-base/agent`)

- Route handler: `kb_search_agent_endpoint(input_data: RunAgentInput, request: Request)`.
- Middleware: uses the same `AgUIMiddleware.create_response(...)` pipeline as supervisor.
- Agent function behavior:
  - calls `kb_search_agent.search(user_input)`
  - returns `AgentResult(response=..., metadata={"mode": "knowledge_base_search"})`
- Interrupt model:
  - this path is designed as single-turn search/answer
  - no interrupt/resume loop is currently surfaced by the route/UI
- Frontend caller:
  - `runKbSearchAgentChat(...)` in `Agent_UI/src/services/api.js`
  - used by `Agent_UI/src/app/knowledge-base/page.js`
  - implemented as `runAgentChat(..., { agentUrl: `${API_BASE_URL}/api/knowledge-base/agent` })`

## 8) LangGraph interrupt bridge used here

Files:
- `agents/langgraph_coding_agent.py`
- `routes/supervisor_routes.py`

Implementation details:
- `ask_user(...)` tool calls `interrupt(...)` in LangGraph.
- Middleware surfaces interrupt info to frontend as interrupted run outcome.
- On resume, supervisor extracts `context.resume_data.payload` and passes `resume_value` into coding agent.
- Coding agent resumes with `Command(resume=resume_value)`.

## 9) End-to-end flow (this repo)

1. UI submits message history and latest user input.
2. Frontend `HttpAgent.runAgent(...)` calls an AG-UI endpoint.
3. Middleware emits run/step/text/custom events.
4. UI updates message content incrementally from `TEXT_MESSAGE_CONTENT` deltas.
5. If coding flow interrupts, frontend receives interrupt outcome in `RUN_FINISHED` and prompts user.
6. Frontend sends resume payload; middleware resolves interrupt state and resumes execution.

## 10) Known implementation constraints

- `InterruptManager` is in-memory.
- Pending interrupts are lost on process restart.
- Pending interrupts are not shared across multiple replicas unless you replace storage with a shared backend.

## 11) Troubleshooting

- Connection issues:
  - verify backend is up and endpoint URL is correct (`/api/supervisor/agent` or `/api/knowledge-base/agent`).
- No text streaming:
  - verify subscriber handlers (`onTextMessageContentEvent`, `onRunFinishedEvent`, `onRunErrorEvent`).
- Resume not working:
  - keep `threadId` stable, send valid `interruptId`, ensure interrupt is still pending in server memory.

## 12) Key files

- `Agent_UI/src/services/api.js`
- `Agent_UI/src/app/page.js`
- `Agent_UI/src/app/knowledge-base/page.js`
- `routes/supervisor_routes.py`
- `routes/knowledge_base_routes.py`
- `ag_ui_middleware/middleware.py`
- `ag_ui_middleware/events.py`
- `ag_ui_middleware/types.py`
- `agents/langgraph_coding_agent.py`
