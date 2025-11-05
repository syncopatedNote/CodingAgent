# CBP AI Wizard - Agent Architecture

This directory contains the agent-based architecture for the CBP AI Wizard, featuring a simplified supervisor agent that coordinates between specialized agents.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    User Interface                           │
│                 (Streamlit Chat)                           │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                Supervisor Agent                             │
│              (supervisor_agent.py)                         │
│                                                             │
│  Responsibilities:                                          │
│  1. Classify user intent (Search vs Code Generation)       │
│  2. Route to appropriate agent                              │
│  3. Handle general chat queries                             │
└─────────────────────┬───────────────────┬───────────────────┘
                      │                   │
                      ▼                   ▼
┌─────────────────────────────────┐ ┌─────────────────────────────────┐
│          Search Agent           │ │         Coding Agent            │
│       (search_agent.py)         │ │      (coding_agent.py)          │
│                                 │ │                                 │
│ Responsibilities:               │ │ Responsibilities:               │
│ • Confluence document search    │ │ • Fetch Jira ticket details    │
│ • Jira ticket lookup           │ │ • Extract Confluence designs   │
│ • Jira issue search            │ │ • Generate code using LLM      │
│ • Entity extraction            │ │ • Create GitLab branches        │
│ • Result formatting            │ │ • Commit generated code         │
└─────────────────┬───────────────┘ └─────────────────┬───────────────┘
                  │                                   │
                  ▼                                   ▼
┌─────────────────────────────────────────────────────────────┐
│                    MCP Tools                                │
│                                                             │
│ • atlassian___confluence_search                             │
│ • atlassian___jira_get_issue                                │
│ • atlassian___jira_search                                   │
│ • gitlab___* (various GitLab operations)                    │
└─────────────────────────────────────────────────────────────┘
```

## Agent Descriptions

### 1. Supervisor Agent (supervisor_agent.py)

**Purpose**: Main orchestrator with two primary responsibilities:
- Route search queries to the Search Agent
- Route code generation requests to the Coding Agent

**Key Features**:
- Simple intent classification based on keywords and patterns
- Jira ticket extraction from user input
- Fallback to general chat for unclassified queries
- Clean separation of concerns

**Task Types**:
- `SEARCH_OPERATION`: Document/ticket searches
- `CODE_GENERATION`: Code generation from requirements
- `GENERAL_CHAT`: Help and general questions

### 2. Search Agent (search_agent.py)

**Purpose**: Handle all search operations across different systems.

**Search Types**:
- `CONFLUENCE_SEARCH`: Search Confluence documents
- `JIRA_TICKET_LOOKUP`: Get specific Jira ticket details
- `JIRA_SEARCH`: Search Jira issues using JQL

**Key Features**:
- Automatic entity extraction (Jira tickets, keywords, projects)
- Intelligent search type determination
- Formatted result presentation
- Error handling and fallbacks

### 3. Coding Agent (coding_agent.py)

**Purpose**: Generate code from Jira ticket requirements.

**Workflow**:
1. Fetch Jira ticket details
2. Extract Confluence design links
3. Load development rules
4. Generate code using LLM
5. Create GitLab branch and commit

**Dependencies**:
- OpenAI API key for code generation
- GitLab project ID for code commits
- Development rules file

### 4. Question Enhancer Agent (question_enhancer_agent.py)

**Purpose**: Enhance user questions using conversation context.

**Usage**: Called by other agents to improve search queries based on chat history.

## File Structure

```
agents/
├── README.md                      # This file
├── __init__.py                    # Package initialization
├── supervisor_agent.py              # Simplified supervisor agent
├── search_agent.py                # Dedicated search agent
├── coding_agent.py                # Code generation agent
├── question_enhancer_agent.py     # Question enhancement utility
└── requirements.txt               # Agent-specific dependencies
```

## Usage Examples

### Search Operations

```python
# Search for Confluence documents
"Search for API documentation"
"Find deployment guides"

# Look up specific Jira tickets
"Show me ticket PROJ-123"
"Get details for DEV-456"

# Search Jira issues
"Find recent bugs in production"
"Show open stories assigned to John"
```

### Code Generation

```python
# Generate code from Jira ticket
"Generate code for DEV-456"
"Implement the feature in STORY-789"
"Write code for TASK-123"
```

### General Chat

```python
# Get help and guidance
"What can you help me with?"
"How do I search for documents?"
"Explain the code generation process"
```

## Configuration

### Environment Variables

```bash
# Required for coding agent
OPENAI_API_KEY=your_openai_api_key
GITLAB_PROJECT_ID=your_gitlab_project_id

# Optional
DEVELOPMENT_RULES_PATH=./development_rules.md
```

### MCP Server Configuration

The agents rely on MCP (Model Context Protocol) tools for external integrations:

- **Atlassian MCP Server**: For Confluence and Jira operations
- **GitLab MCP Server**: For GitLab operations

Ensure these MCP servers are configured and running before using the agents.

## Running the System

### 1. Test the Integration

```bash
python test_supervisor_integration.py
```

### 2. Start the Chat Interface

```bash
streamlit run chat_with_supervisor_v2.py
```

### 3. Alternative: Use Original Chat

```bash
streamlit run chat.py
```

## Development Guidelines

### Adding New Search Types

1. Add new `SearchType` enum value in `search_agent.py`
2. Implement search method (e.g., `_search_new_system`)
3. Add routing logic in `_route_after_analysis`
4. Add result formatting in `_format_results`

### Adding New Task Types

1. Add new `TaskType` enum value in `supervisor_agent.py`
2. Implement task handler method
3. Add routing logic in `_route_after_classification`
4. Update classification logic in `_classify_task_simple`

### Error Handling

All agents implement comprehensive error handling:
- Graceful degradation when services are unavailable
- Clear error messages for users
- Fallback behaviors for edge cases

## Testing

The system includes test scripts to verify:
- Individual agent functionality
- Integration between agents
- Environment configuration
- MCP tool availability

Run tests before deployment to ensure everything works correctly.

## Future Enhancements

1. **Enhanced Intent Classification**: Use ML models for better intent detection
2. **Multi-Agent Collaboration**: Allow agents to work together on complex tasks
3. **Caching**: Implement result caching for frequently accessed data
4. **Metrics**: Add performance monitoring and usage analytics
5. **Custom Agents**: Framework for adding domain-specific agents
