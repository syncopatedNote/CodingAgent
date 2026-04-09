# Supervisor Agent API Guide

Complete guide for the Supervisor Agent REST API service - from setup to deployment.

## Table of Contents
- [Overview](#overview)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
- [Integration Examples](#integration-examples)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)

---

## Overview

The Supervisor Agent API exposes an intelligent multi-agent orchestrator as a REST service. It automatically:
- **Classifies** user queries into task types (search, code generation, general chat)
- **Routes** to specialized sub-agents (search agent, coding agent)
- **Manages** conversation context and session state
- **Returns** structured responses with metadata

### Key Features

- ✅ **Automatic routing** based on query intent
- ✅ **Context-aware** question enhancement
- ✅ **Async/await** for efficient processing
- ✅ **Streaming support** for real-time updates
- ✅ **Session tracking** for conversation continuity
- ✅ **CORS enabled** for frontend integration

---

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (recommended)
- Environment credentials (Jira, Confluence, GitLab)

### Option 1: Docker (Recommended)

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with your credentials

# 2. Start all services
docker compose up -d

# 3. Verify
curl http://localhost:8000/api/health
```

**Services Available:**
- API: http://localhost:8000
- Agent UI: http://localhost:3000

### Option 2: Local Development

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your credentials

# 3. Start the API
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Quick Test

```bash
# Health check
curl http://localhost:8000/api/health

# Test chat
curl -X POST http://localhost:8000/api/supervisor/chat \
  -H "Content-Type: application/json" \
  -d '{"user_input":"What can you help me with?"}'
```

---

## API Reference

Base URL: `http://localhost:8000`

### Interactive Documentation

- **Swagger UI**: http://localhost:8000/api/docs
- **ReDoc**: http://localhost:8000/api/redoc
- **OpenAPI Schema**: http://localhost:8000/api/openapi.json

### Endpoints

#### 1. Health Check

**GET** `/api/health`

Check if the API service is running and ready.

**Response:**
```json
{
  "status": "healthy",
  "message": "Supervisor API is running",
  "timestamp": "2025-12-13T10:30:45.123456"
}
```

**Status Codes:**
- `200`: Service healthy
- `503`: Service initializing

---

#### 2. Chat (Main Endpoint)

**POST** `/api/supervisor/chat`

Send a query to the supervisor agent for intelligent routing and processing.

**Request Body:**
```json
{
  "user_input": "Find information about PROJ-123",
  "conversation_history": [
    {
      "role": "user",
      "content": "Previous question"
    },
    {
      "role": "assistant",
      "content": "Previous response"
    }
  ],
  "session_id": "session-abc-123"
}
```

**Parameters:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `user_input` | string | Yes | The user's question or request |
| `conversation_history` | array | No | Previous messages for context |
| `session_id` | string | No | Session identifier for tracking |

**Response:**
```json
{
  "session_id": "session-abc-123",
  "task_analysis": {
    "task_type": "search_operation",
    "confidence": 0.85,
    "extracted_jira_tickets": ["PROJ-123"]
  },
  "response": "I found ticket PROJ-123 with the following details...",
  "search_results": {
    "formatted_response": "...",
    "search_results": [...]
  },
  "coding_results": null,
  "error": null,
  "requires_user_input": false,
  "timestamp": "2025-12-13T10:30:45.123456"
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Echo of session ID for tracking |
| `task_analysis.task_type` | string | `search_operation`, `code_generation`, or `general_chat` |
| `task_analysis.confidence` | float | Classification confidence (0-1) |
| `task_analysis.extracted_jira_tickets` | array | Jira ticket keys found in input |
| `response` | string | Final response from supervisor |
| `search_results` | object\|null | Results from search agent (if applicable) |
| `coding_results` | object\|null | Results from coding agent (if applicable) |
| `error` | string\|null | Error message if any |
| `requires_user_input` | boolean | Whether workflow needs additional input |
| `timestamp` | string | ISO timestamp of response |

**Status Codes:**
- `200`: Success
- `400`: Invalid request
- `500`: Internal server error
- `503`: Service not initialized

**Example cURL:**
```bash
curl -X POST "http://localhost:8000/api/supervisor/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "Search for deployment documentation",
    "session_id": "my-session-1"
  }'
```

---

#### 3. AG-UI Agent Endpoint

**POST** `/api/supervisor/agent`

Stream responses using the AG-UI protocol (Server-Sent Events with typed events).

**Request:** AG-UI `RunAgentInput` format
```json
{
  "threadId": "session-123",
  "runId": "run-1709000000000",
  "state": {},
  "messages": [
    { "id": "msg-0", "role": "user", "content": "Hello" }
  ],
  "tools": [],
  "context": [],
  "forwardedProps": {}
}
```

**Response:** AG-UI event stream (SSE) with events:
- `RUN_STARTED` / `RUN_FINISHED` / `RUN_ERROR` — lifecycle
- `STEP_STARTED` / `STEP_FINISHED` — processing steps
- `TEXT_MESSAGE_START` / `TEXT_MESSAGE_CONTENT` / `TEXT_MESSAGE_END` — response text
- `CUSTOM(task_analysis)` — task classification metadata

**Example (JavaScript):**
```javascript
import { HttpAgent, EventType } from "@ag-ui/client";

const agent = new HttpAgent({
  url: "http://localhost:8000/api/supervisor/agent",
});

agent.threadId = "session-123";
agent.messages = [{ id: "msg-0", role: "user", content: "Hello" }];

agent.runAgent({ runId: "run-1", tools: [], context: [] }).subscribe({
  next: (event) => {
    if (event.type === EventType.TEXT_MESSAGE_CONTENT) {
      process.stdout.write(event.delta);
    }
  },
});
```

---

#### 4. Root Information

**GET** `/`

Get API information and available endpoints.

**Response:**
```json
{
  "name": "Supervisor Agent API",
  "version": "1.0.0",
  "documentation": "/api/docs",
  "redoc": "/api/redoc",
  "endpoints": {
    "health": "/api/health",
    "supervisor_chat": "/api/supervisor/chat",
    "supervisor_chat_stream": "/api/supervisor/agent"
  }
}
```

---

## Integration Examples

### JavaScript/TypeScript

```typescript
// supervisorClient.ts
const API_BASE = "http://localhost:8000/api";

interface ChatRequest {
  user_input: string;
  conversation_history?: Array<{role: string; content: string}>;
  session_id?: string;
}

export class SupervisorClient {
  async chat(request: ChatRequest) {
    const response = await fetch(`${API_BASE}/supervisor/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.statusText}`);
    }

    return response.json();
  }

  async health() {
    const response = await fetch(`${API_BASE}/health`);
    return response.json();
  }
}

// Usage
const client = new SupervisorClient();
const result = await client.chat({
  user_input: "What is PROJ-123 about?",
  session_id: "user-session-1"
});

console.log("Task:", result.task_analysis.task_type);
console.log("Response:", result.response);
```

### React Hook

```typescript
// useSupervisor.ts
import { useState } from 'react';

export function useSupervisor() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const chat = async (userInput: string, sessionId?: string) => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch('http://localhost:8000/api/supervisor/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_input: userInput, session_id: sessionId }),
      });

      if (!response.ok) {
        throw new Error(`API error: ${response.statusText}`);
      }

      return await response.json();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      throw err;
    } finally {
      setLoading(false);
    }
  };

  return { chat, loading, error };
}

// Usage in component
function ChatComponent() {
  const { chat, loading, error } = useSupervisor();
  const [response, setResponse] = useState(null);

  const handleSend = async (message: string) => {
    const result = await chat(message, 'session-123');
    setResponse(result);
  };

  return (
    <div>
      {loading && <p>Processing...</p>}
      {error && <p>Error: {error}</p>}
      {response && <p>{response.response}</p>}
    </div>
  );
}
```

### Python

```python
# supervisor_client.py
import requests
from typing import Optional, List, Dict, Any

class SupervisorClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url

    def chat(
        self,
        user_input: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send a chat request to the supervisor agent."""
        response = requests.post(
            f"{self.base_url}/api/supervisor/chat",
            json={
                "user_input": user_input,
                "conversation_history": conversation_history or [],
                "session_id": session_id
            },
            timeout=60  # Supervisor processing can take time
        )
        response.raise_for_status()
        return response.json()

    def health(self) -> Dict[str, Any]:
        """Check API health status."""
        response = requests.get(f"{self.base_url}/api/health")
        response.raise_for_status()
        return response.json()

# Usage
client = SupervisorClient()

# Check health
status = client.health()
print(f"Status: {status['status']}")

# Send query
result = client.chat(
    user_input="Find ticket PROJ-123",
    session_id="my-session"
)

print(f"Task Type: {result['task_analysis']['task_type']}")
print(f"Confidence: {result['task_analysis']['confidence']}")
print(f"Response: {result['response']}")
```

### cURL Examples

```bash
# Simple query
curl -X POST http://localhost:8000/api/supervisor/chat \
  -H "Content-Type: application/json" \
  -d '{"user_input":"What can you help me with?"}'

# With session ID
curl -X POST http://localhost:8000/api/supervisor/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_input":"Generate code for PROJ-123",
    "session_id":"session-abc"
  }'

# With conversation history
curl -X POST http://localhost:8000/api/supervisor/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_input":"Tell me more about it",
    "conversation_history":[
      {"role":"user","content":"What is PROJ-123?"},
      {"role":"assistant","content":"PROJ-123 is a feature request..."}
    ],
    "session_id":"session-abc"
  }'
```

---

## Configuration

### Environment Variables

Required variables in `.env`:

See .env.example for details

### CORS Configuration

Default (development):
```python
# In main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Production (restrict origins):
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://your-frontend.com",
        "https://app.example.com"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)
```

---

## Deployment

### Docker Compose (Recommended)

```bash
# Start all services
docker compose up -d

# View logs
docker compose logs -f supervisor-api

# Restart specific service
docker compose restart supervisor-api

# Stop all services
docker compose down

# Stop and remove volumes
docker compose down -v
```

### Production with Gunicorn

```bash
pip install gunicorn

gunicorn main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
```

### Kubernetes

Example deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: supervisor-api
spec:
  replicas: 2
  selector:
    matchLabels:
      app: supervisor-api
  template:
    metadata:
      labels:
        app: supervisor-api
    spec:
      containers:
      - name: api
        image: supervisor-api:latest
        ports:
        - containerPort: 8000
        env:
        - name: LLM_PROVIDER
          value: "ollama"
        - name: JIRA_URL
          valueFrom:
            secretKeyRef:
              name: jira-credentials
              key: url
        # ... other env vars
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2000m"
---
apiVersion: v1
kind: Service
metadata:
  name: supervisor-api
spec:
  selector:
    app: supervisor-api
  ports:
  - port: 80
    targetPort: 8000
  type: LoadBalancer
```

---

## Troubleshooting
integrate Langsmith (cloud hosted - paid) or Langfuse (self-hosted/open-source)
to recieve telemetry from the app for detail tracing of the request.

---

## Performance Tips

1. **Use Session IDs**: Maintain context across requests for better responses
2. **Cache on Frontend**: Cache supervisor responses for repeated queries
3. **Implement Timeouts**: Set 60-120 second timeouts for supervisor requests
4. **Use Streaming**: For real-time responses, use the AG-UI endpoint `/api/supervisor/agent`
5. **Monitor MCP Servers**: Ensure MCP containers have adequate resources
6. **Scale Horizontally**: Run multiple supervisor-api replicas behind load balancer

---

## Task Types

The supervisor automatically classifies queries into:

### 1. **search_operation**
- Finding Confluence documentation
- Looking up Jira tickets
- Searching for specific information

**Keywords:** "search", "find", "look for", "show me", "get", "fetch", "display", "list", "what is", "tell me about"

**Examples:**
- "Find ticket PROJ-123"
- "Search for API documentation"
- "What is the status of DEV-456?"

### 2. **code_generation**
- Generating code from Jira tickets
- Implementing features based on requirements

**Keywords:** "generate code", "write code", "implement", "develop", "build", "create code"

**Examples:**
- "Generate code for PROJ-123"
- "Implement feature from ticket DEV-456"

### 3. **general_chat**
- General questions
- Help requests
- Casual conversation

**Examples:**
- "What can you help me with?"
- "How do I use this?"
- "Hello"

---

## Additional Resources

- **API Interactive Docs**: http://localhost:8000/api/docs
- **Source Code**: `main.py`
- **Agent Implementation**: `agents/supervisor_agent.py`
- **Settings**: `settings.py`
- **Docker Setup**: `docker-compose.yml`
- **Project README**: `README.md`

---

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review application logs: `docker compose logs supervisor-api`
3. Verify environment configuration in `.env`
4. Test with the interactive docs: http://localhost:8000/api/docs

---

**Last Updated:** December 13, 2025
