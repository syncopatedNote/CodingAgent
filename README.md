# Coding Agent

An intelligent multi-agent AI assistant system designed for enterprise environments, featuring document processing, multi-modal RAG (Retrieval-Augmented Generation), and automated code generation capabilities. The system integrates with Confluence, Jira, and GitLab to provide comprehensive workflow automation and intelligent assistance.

## 🚀 Features

### Multi-Agent Architecture
- **Supervisor Agent**: Intelligent task routing and orchestration
- **Search Agent**: Advanced search across Confluence, Jira, and document repositories
- **Coding Agent**: Automated code generation from Jira tickets and requirements
- **Question Enhancer**: Context-aware query enhancement and optimization

### Document Processing & RAG
- **Multi-modal PDF Processing**: Extract and process text, tables, and images from PDF documents
- **Intelligent Summarization**: AI-powered summarization of documents, tables, and images
- **Vector Storage**: ChromaDB-based vector storage for efficient similarity search
- **Multi-Vector Retrieval**: Advanced retrieval system supporting text, tables, and images

### Enterprise Integrations
- **Confluence Integration**: Search, retrieve, and process Confluence pages and documentation
- **Jira Integration**: Ticket lookup, search, and automated code generation from requirements
- **GitLab Integration**: Automated branch creation, code commits, and merge request management
- **MCP (Model Context Protocol)**: Extensible tool integration framework

### LLM Support
- **Ollama Integration**: Local LLM deployment with support for various models (Llama3, etc.)
- **Amazon Q Integration**: Enterprise-grade AI assistance
- **Bedrock Support**: AWS Bedrock integration for scalable AI services
- **Multi-Provider Architecture**: Flexible LLM provider switching

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Streamlit UI   │    │ Chat Interface  │    │ Supervisor UI   │
└─────────┬───────┘    └─────────┬───────┘    └─────────┬───────┘
          │                      │                      │
          └──────────────────────┼──────────────────────┘
                                 │
                    ┌─────────────┴─────────────┐
                    │    Supervisor Agent       │
                    │  (Task Classification &   │
                    │      Routing)            │
                    └─────────────┬─────────────┘
                                 │
                ┌────────────────┼────────────────┐
                │                │                │
    ┌───────────▼───────────┐   │   ┌───────────▼───────────┐
    │    Search Agent       │   │   │    Coding Agent       │
    │ - Confluence Search   │   │   │ - Jira Integration    │
    │ - Jira Lookup        │   │   │ - Code Generation     │
    │ - Document Retrieval  │   │   │ - GitLab Integration  │
    └───────────────────────┘   │   └───────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │   Framework Base      │
                    │ - LLM Factory         │
                    │ - Vector Store        │
                    │ - Document Store      │
                    │ - MCP Client          │
                    └───────────────────────┘
```

## 📋 Prerequisites

- **Python 3.8+**
- **Ollama** (for local LLM deployment)
- **MongoDB** (for document storage)
- **ChromaDB** (automatically managed)
- **Docker** (optional, for containerized deployment)

## 🛠️ Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up Ollama**
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

5. **Environment Configuration**
   ```env
   # Confluence Configuration
   CONFLUENCE_URL="https://your-confluence-instance.com"
   CONFLUENCE_USERNAME="your-username"
   CONFLUENCE_API_TOKEN="your-api-token"
   CONFLUENCE_SSL_VERIFY="false"
   
   # Jira Configuration
   JIRA_URL="https://your-jira-instance.com"
   JIRA_PERSONAL_TOKEN="your-personal-token"
   JIRA_SSL_VERIFY="false"
   
   # GitLab Configuration (for coding agent)
   GITLAB_PROJECT_ID="your-project-id"
   GITLAB_ACCESS_TOKEN="your-access-token"
   
   # MCP Configuration
   MCP_VERY_VERBOSE="true"
   ```

## 🚀 Quick Start

### 1. Document Processing (PDF RAG)

1. **Add your PDF documents** to the `pdf_files/` directory

2. **Process documents** to create vector embeddings:
   ```bash
   python pdf_loader.py
   ```

3. **Launch the chat interface**:
   ```bash
   streamlit run chat.py
   ```

### 2. Multi-Agent Assistant

Launch the advanced multi-agent interface:
```bash
streamlit run chat_with_supervisor.py
```

### 3. Confluence Data Loading

Process Confluence pages for enhanced search:
```bash
python confluence_loader_new.py
```

## 💡 Usage Examples

### Document Q&A
```
User: "What are the key features of the Service Order Orchestrator?"
AI: Based on the technical guide, the Service Order Orchestrator includes...
```

### Jira Integration
```
User: "Show me details for ticket CBP-8446"
AI: [Retrieves and displays Jira ticket information with context]
```

### Code Generation
```
User: "Generate code for implementing the feature in DEV-123"
AI: [Analyzes Jira ticket, retrieves design docs, generates code]
```

### Confluence Search
```
User: "Find API documentation for authentication"
AI: [Searches Confluence and returns relevant documentation]
```

## 🔧 Configuration

### LLM Configuration
The system supports multiple LLM providers through the `LLMFactory`:

```python
# Ollama (Local)
llm = LLMFactory.create_llm(
    provider="ollama",
    model_name="llama3:8b",
    model_type="chat",
    temperature=0.7
)

# Amazon Q
llm = LLMFactory.create_llm(
    provider="amazon_q",
    model_name="amazon-q-developer",
    model_type="chat"
)

# AWS Bedrock
llm = LLMFactory.create_llm(
    provider="bedrock",
    model_name="anthropic.claude-3-sonnet-20240229-v1:0",
    model_type="chat"
)
```

### Vector Store Configuration
```python
# ChromaDB (Default)
vectorstore = get_vector_store(
    store_type="chroma",
    collection_name="langchain"
)
```

### Document Store Configuration
```python
# MongoDB Document Store
doc_store = get_document_store(
    database="langchain_db",
    collection_name="documents",
    mongodb_uri="mongodb://127.0.0.1:27017"
)
```

## 📁 Project Structure

```
cbp-ai-wizard/
├── agents/                     # Multi-agent system
│   ├── supervisor_agent.py     # Main orchestration agent
│   ├── search_agent.py         # Search and retrieval agent
│   ├── coding_agent.py         # Code generation agent
│   ├── question_enhancer_agent.py
│   ├── components/             # Modular agent components
│   └── models/                 # Data models
├── framework_base/             # Core framework
│   ├── llm_base.py            # LLM factory and abstractions
│   ├── vector_store.py        # Vector storage management
│   ├── doc_store.py           # Document storage
│   ├── multi_server_mcp_client.py
│   └── amazon_q/              # Amazon Q integration
├── pdf_files/                 # PDF documents for processing
├── chroma_db/                 # ChromaDB storage
├── logs/                      # Application logs
├── chat.py                    # Simple chat interface
├── chat_with_supervisor.py    # Advanced multi-agent interface
├── pdf_loader.py              # PDF processing pipeline
├── confluence_loader_new.py   # Confluence data loader
├── utils.py                   # Utility functions
├── logger.py                  # Logging configuration
└── requirements.txt           # Python dependencies
```

## 🔍 Key Components

### Multi-Vector Retrieval System
- Processes and indexes text, tables, and images separately
- Generates AI summaries for better semantic search
- Supports multi-modal queries and responses

### Intelligent Task Routing
- Automatically classifies user queries
- Routes to appropriate specialized agents
- Maintains conversation context and history

### Enterprise Integration
- Secure authentication with enterprise systems
- SSL/TLS support with certificate management
- Configurable API endpoints and credentials

## 🚨 Troubleshooting

### Common Issues

1. **Ollama Connection Issues**
   ```bash
   # Check if Ollama is running
   ollama list
   
   # Restart Ollama service
   ollama serve
   ```

2. **MongoDB Connection Issues**
   ```bash
   # Start MongoDB service
   brew services start mongodb/brew/mongodb-community
   # or
   sudo systemctl start mongod
   ```

3. **ChromaDB Persistence Issues**
   ```bash
   # Clear ChromaDB if corrupted
   rm -rf chroma_db/
   # Re-run pdf_loader.py to rebuild
   ```

4. **SSL Certificate Issues**
   - Set `SSL_VERIFY="false"` in environment variables for development
   - Add custom certificates to `ca_roots.pem` for production

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- **LangChain** for the RAG framework
- **Ollama** for local LLM deployment
- **Streamlit** for the user interface
- **ChromaDB** for vector storage
- **MongoDB** for document persistence
