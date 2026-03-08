# Coding Agent - Enterprise AI Assistant System

An intelligent multi-agent AI assistant system designed for enterprise environments, featuring document processing, multi-modal RAG (Retrieval-Augmented Generation), automated code generation, and REST API capabilities. The system integrates with Confluence, Jira, and GitLab through the Model Context Protocol (MCP) to provide comprehensive workflow automation and intelligent assistance.

## 🚀 Features

### Multi-Agent Architecture
- **Supervisor Agent**: Intelligent task routing and orchestration with confidence-based classification
- **Search Agent**: Advanced search across Confluence, Jira, and document repositories with semantic retrieval
- **Coding Agent**: Automated code generation from Jira tickets with GitLab integration
- **Question Enhancer**: Context-aware query enhancement for improved retrieval

### REST API Service
- **FastAPI Backend**: Production-ready REST API for supervisor agent
- **Interactive Documentation**: Automatic OpenAPI/Swagger documentation at `/api/docs`
- **Streaming Support**: Server-Sent Events (SSE) for real-time responses
- **CORS Enabled**: Cross-origin support for frontend integration
- **Docker Compose Deployment**: Complete containerized setup with all dependencies

### Document Processing & RAG
- **Multi-modal PDF Processing**: Extract and process text, tables, and images from PDF documents
- **Confluence Integration**: Process Confluence pages with images, tables, and hierarchical content
- **Intelligent Summarization**: AI-powered summarization of documents, tables, and images
- **Vector Storage**: ChromaDB-based vector storage for efficient similarity search
- **Multi-Vector Retrieval**: Advanced retrieval system supporting text, tables, and images
- **MongoDB Document Store**: Persistent storage for retrieved documents and metadata

### Enterprise Integrations via MCP
- **MCP (Model Context Protocol)**: Dual-transport architecture (SSE + stdio)
- **Confluence Integration**: Search, retrieve, and process pages and documentation
- **Jira Integration**: Ticket lookup, search, and automated workflows
- **GitLab Integration**: Branch creation, code commits, and merge request management
- **Extensible Architecture**: Easy addition of new MCP servers and tools

### LLM Support
- **Ollama Integration**: Local LLM deployment (Llama 3, Mistral, etc.)
- **OpenAI Integration**: GPT-4, GPT-3.5 support via LiteLLM
- **AWS Bedrock Support**: Claude, Titan, and other Bedrock models
- **Multi-Provider Architecture**: Flexible LLM provider switching via unified factory

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐
│  Agent UI       │    │  REST API       │
│  (Port 3000)    │    │  (Port 8000)    │
└─────────┬───────┘    └─────────┬───────┘
          │                      │
          └──────────┬───────────┘
                                 │
                    ┌─────────────▼─────────────┐
                    │    Supervisor Agent       │
                    │  (Task Classification &   │
                    │      Routing)            │
                    └─────────────┬─────────────┘
                                 │
                ┌────────────────┼────────────────┐
                │                │                │
    ┌───────────▼───────────┐   │   ┌───────────▼───────────┐
    │    Search Agent       │   │   │    Coding Agent       │
    │ - MCP Atlassian       │   │   │ - Jira via MCP        │
    │ - Confluence Search   │   │   │ - Code Generation     │
    │ - Jira Lookup        │   │   │ - GitLab via MCP      │
    │ - Vector Store RAG    │   │   │ - Branch Management   │
    └───────────────────────┘   │   └───────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │   Framework Base      │
                    │ - LLM Factory         │
                    │ - Vector Store        │
                    │ - Document Store      │
                    │ - MCP Client          │
                    └───────────┬───────────┘
                                │
            ┌───────────────────┼───────────────────┐
            │                   │                   │
    ┌───────▼────────┐  ┌──────▼──────┐  ┌────────▼────────┐
    │ MCP Atlassian  │  │ MCP GitLab  │  │    MongoDB      │
    │ (Port 3000)    │  │ (Port 3001) │  │  (Port 27017)   │
    └────────────────┘  └─────────────┘  └─────────────────┘
```

### MCP Architecture
- **Dual Transport**: SSE (production) and stdio (development)
- **SSE Transport**: Persistent HTTP connections to MCP services
- **stdio Transport**: On-demand Docker container execution
- See [MCP_ARCHITECTURE.md](MCP_ARCHITECTURE.md) for detailed information

## 📋 Prerequisites

- **Python 3.11+**
- **Docker & Docker Compose** (for containerized deployment)
- **Ollama** (optional, for local LLM deployment)
- **MongoDB** (automatically managed in Docker Compose)
- **ChromaDB** (automatically managed)

## 🛠️ Installation

### Option 1: Docker Compose (Recommended)

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd Coding_agent
   ```

2. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration (see Configuration section below)
   ```

3. **Start all services**
   ```bash
   docker compose up -d
   ```

4. **Access the services**
   - **Agent UI**: http://localhost:3000
   - **REST API**: http://localhost:8000
   - **API Docs**: http://localhost:8000/api/docs

### Option 2: Local Development

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd Coding_agent
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up Ollama (if using local LLMs)**
   ```bash
   # Install Ollama (macOS/Linux)
   curl -fsSL https://ollama.ai/install.sh | sh

   # Pull required models
   ollama pull llama3:8b
   ollama pull nomic-embed-text
   ```

4. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

5. **Start MongoDB**
   ```bash
   brew services start mongodb/brew/mongodb-community
   # or
   sudo systemctl start mongod
   ```

## ⚙️ Configuration

### Environment Variables

Create a `.env` file with the following configuration:

```env
# LLM Configuration
LLM_PROVIDER="ollama"          # Options: ollama, litellm, bedrock
LLM_MODEL_NAME="llama3:8b"     # Model name for your provider
LLM_MODEL_TYPE="chat"          # Usually "chat" for conversational models

# Ollama Configuration (if using local Ollama)
OLLAMA_BASE_URL="http://host.docker.internal:11434"  # For Docker
# OLLAMA_BASE_URL="http://localhost:11434"           # For local dev

# OpenAI Configuration (if using litellm with OpenAI)
OPENAI_API_KEY="your-openai-api-key"

# AWS Bedrock Configuration (if using bedrock provider)
AWS_ACCESS_KEY_ID="your-aws-access-key"
AWS_SECRET_ACCESS_KEY="your-aws-secret-key"
AWS_REGION="us-east-1"

# Confluence Configuration
CONFLUENCE_URL="https://your-company.atlassian.net/wiki"
CONFLUENCE_USERNAME="your-email@company.com"
CONFLUENCE_API_TOKEN="your-confluence-api-token"
CONFLUENCE_SSL_VERIFY="false"  # Set to "true" in production with valid certs

# Jira Configuration
JIRA_URL="https://your-company.atlassian.net"
JIRA_PERSONAL_TOKEN="your-jira-personal-token"
JIRA_SSL_VERIFY="false"        # Set to "true" in production with valid certs

# GitLab Configuration
GITLAB_PERSONAL_ACCESS_TOKEN="your-gitlab-token"
GITLAB_API_URL="https://gitlab.example.com"
GITLAB_PROJECT_ID="your-project-id"
GITLAB_READ_ONLY_MODE="false"

# MCP Configuration
MCP_VERY_VERBOSE="true"        # Enable verbose logging for MCP

# MCP Service URLs (for Docker Compose - SSE transport)
MCP_ATLASSIAN_URL="http://mcp-atlassian:3000"
MCP_GITLAB_URL="http://mcp-gitlab:3001"

# MongoDB Configuration (optional, defaults work for Docker Compose)
MONGODB_URI="mongodb://mongodb:27017"
MONGODB_DATABASE="langchain_db"
```

### Transport Mode Selection

The system automatically selects MCP transport based on configuration:

- **SSE Transport** (Production): Used when `MCP_ATLASSIAN_URL` is set
  - Persistent connections to MCP services
  - Better performance and security
  - Docker Compose default

- **stdio Transport** (Development): Used when `MCP_ATLASSIAN_URL` is not set
  - On-demand Docker container execution
  - No persistent services required
  - Local development fallback

See [MCP_ARCHITECTURE.md](MCP_ARCHITECTURE.md) for detailed information.

## 🚀 Quick Start

### Using Docker Compose (Recommended)

1. **Start all services**
   ```bash
   docker compose up -d
   ```

2. **Check service status**
   ```bash
   docker compose ps
   docker compose logs -f supervisor-api
   ```

3. **Access the interfaces**
   - **Agent UI**: http://localhost:3000
   - **REST API**: http://localhost:8000
   - **API Interactive Docs**: http://localhost:8000/api/docs

4. **Test the API**
   ```bash
   # Health check
   curl http://localhost:8000/api/health

   # Chat request
   curl -X POST http://localhost:8000/api/supervisor/chat \
     -H "Content-Type: application/json" \
     -d '{"user_input":"What can you help me with?"}'
   ```

### Using Local Development

1. **Start MongoDB**
   ```bash
   brew services start mongodb/brew/mongodb-community
   ```

2. **Launch REST API**
   ```bash
   uvicorn supervisor_api:app --host 0.0.0.0 --port 8000 --reload
   ```
   Visit http://localhost:8000/api/docs

### Document Processing (RAG Pipeline)

#### Process PDF Documents

1. **Add PDFs** to a directory (e.g., `old_stuff/pdf_files/`)

2. **Run the PDF loader** (update file paths in script):
   ```bash
   python old_stuff/pdf_loader.py
   ```

#### Process Confluence Pages

1. **Configure Confluence credentials** in `.env`

2. **Update the loader script** with space key and page ID:
   ```python
   # In RAG/confluence_loader_new.py
   CONFLUENCE_URL = "https://your-confluence.com"
   SPACE_KEY = "YOUR_SPACE"
   PAGE_ID = "123456"
   ```

3. **Run the loader**:
   ```bash
   python RAG/confluence_loader_new.py
   ```

## 💡 Usage Examples

### Usage Examples

**Search Operations:**
```
User: "Find ticket PROJ-123"
User: "Search for API documentation in Confluence"
User: "Show me recent bugs in the DEV project"
```

**Code Generation:**
```
User: "Generate code for ticket CBP-8446"
User: "Implement the feature described in DEV-789"
```

**General Chat:**
```
User: "What can you help me with?"
User: "How do I integrate with the API?"
```

### REST API Examples

**Using cURL:**

```bash
# Health check
curl http://localhost:8000/api/health

# Simple chat
curl -X POST http://localhost:8000/api/supervisor/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "Find information about PROJ-123",
    "session_id": "my-session-1"
  }'

# Chat with history
curl -X POST http://localhost:8000/api/supervisor/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "Tell me more about it",
    "conversation_history": [
      {"role": "user", "content": "What is PROJ-123?"},
      {"role": "assistant", "content": "PROJ-123 is..."}
    ],
    "session_id": "my-session-1"
  }'
```

**Using Python:**

```python
import requests

# Simple request
response = requests.post(
    "http://localhost:8000/api/supervisor/chat",
    json={
        "user_input": "Search for deployment documentation",
        "session_id": "python-session"
    }
)

result = response.json()
print(f"Task Type: {result['task_analysis']['task_type']}")
print(f"Response: {result['response']}")
```

**Using JavaScript/TypeScript:**

```typescript
const response = await fetch('http://localhost:8000/api/supervisor/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    user_input: 'Find ticket PROJ-123',
    session_id: 'js-session'
  })
});

const result = await response.json();
console.log(result.response);
```

See [SUPERVISOR_API_GUIDE.md](SUPERVISOR_API_GUIDE.md) for complete API documentation.

## 📁 Project Structure

```
Coding_agent/
├── agents/                     # Multi-agent system
│   ├── supervisor_agent.py     # Main orchestration agent
│   ├── search_agent.py         # Search and retrieval agent
│   ├── coding_agent.py         # Code generation agent
│   ├── question_enhancer_agent.py # Query enhancement
│   ├── components/             # Modular agent components
│   │   ├── jira_handler.py
│   │   ├── confluence_handler.py
│   │   ├── gitlab_handler.py
│   │   └── code_generator.py
│   └── models/                 # Data models and schemas
│       └── jira_response_model.py
├── framework_base/             # Core framework
│   ├── llm_base.py            # LLM factory and abstractions
│   ├── vector_store.py        # Vector storage management
│   ├── doc_store.py           # Document storage (MongoDB)
│   └── multi_server_mcp_client.py # MCP client with dual transport
├── RAG/                       # RAG pipeline implementations
│   └── confluence_loader_new.py # Confluence data loader
├── old_stuff/                 # Legacy implementations
│   ├── pdf_loader.py          # PDF processing pipeline
│   └── chat.py                # Simple chat interface
├── chroma_db/                 # ChromaDB vector storage (auto-created)
├── logs/                      # Application logs (auto-created)
├── supervisor_api.py          # FastAPI REST API service
├── settings.py                # Application settings and configuration
├── logger.py                  # Logging configuration
├── utils.py                   # Utility functions
├── requirements.txt           # Python dependencies
├── docker-compose.yml         # Docker Compose configuration
├── dockerfile.api             # Dockerfile for API service
├── README.md                  # This file
├── SUPERVISOR_API_GUIDE.md    # Complete API documentation
├── MCP_ARCHITECTURE.md        # MCP integration details
└── .env.example               # Environment variables template
```

## 🔧 Advanced Configuration

### LLM Configuration Examples

The system supports multiple LLM providers through the `LLMFactory`:

```python
# Ollama (Local)
llm = LLMFactory.create_llm(
    provider="ollama",
    model_name="llama3:8b",
    model_type="chat",
    temperature=0.7,
    base_url="http://localhost:11434"
)

# OpenAI via LiteLLM
llm = LLMFactory.create_llm(
    provider="litellm",
    model_name="gpt-4o-mini",
    model_type="chat",
    temperature=0.7
)

# AWS Bedrock
llm = LLMFactory.create_llm(
    provider="bedrock",
    model_name="anthropic.claude-3-sonnet-20240229-v1:0",
    model_type="chat",
    temperature=0.7
)
```

### Vector Store Configuration

```python
from framework_base.vector_store import get_vector_store

# ChromaDB (Default)
vectorstore = get_vector_store(
    store_type="chroma",
    collection_name="langchain",
    persist_directory="./chroma_db"
)
```

### Document Store Configuration

```python
from framework_base.doc_store import get_document_store

# MongoDB Document Store
doc_store = get_document_store(
    database="langchain_db",
    collection_name="documents",
    mongodb_uri="mongodb://127.0.0.1:27017"
)
```

## 🐳 Docker Services

The Docker Compose setup includes:

| Service | Port | Description |
|---------|------|-------------|
| supervisor-api | 8000 | FastAPI REST API service |
| mcp-atlassian | 3000 | MCP server for Jira/Confluence |
| mcp-gitlab | 3001 | MCP server for GitLab |
| mongodb | 27017 | MongoDB document store |
| mongo-express | 8081 | MongoDB admin interface |

## 🚨 Troubleshooting

See respective guides or .md files for troubleshooting tips specific to a service

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- **LangChain** for the RAG framework and agent orchestration
- **LangGraph** for state machine graph workflows
- **Ollama** for local LLM deployment
- **FastAPI** for the REST API framework
- **ChromaDB** for vector storage
- **MongoDB** for document persistence
- **Model Context Protocol (MCP)** for extensible tool integration

## 🔗 Related Resources

- [LangChain Documentation](https://python.langchain.com/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Ollama Models](https://ollama.ai/library)
- [MCP Servers](https://github.com/modelcontextprotocol)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
