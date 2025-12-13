# MCP Architecture - Dual Transport Implementation

## Overview

This document explains how MCP (Model Context Protocol) servers are integrated with support for **two transport modes**: SSE (Server-Sent Events) for Docker Compose deployments and stdio for local development.

## Architecture

### MCP Protocol

MCP servers can communicate via two transport mechanisms:

1. **SSE (Server-Sent Events)**: HTTP-based persistent connection for service-to-service communication
2. **stdio**: Standard input/output protocol for process execution

### Dual-Mode Integration Strategy

The implementation automatically selects the appropriate transport based on environment configuration:

```python
# Check if MCP_ATLASSIAN_URL is set (Docker Compose) vs local development
USE_SSE_TRANSPORT = hasattr(settings, 'mcp_atlassian_url') and settings.mcp_atlassian_url

if USE_SSE_TRANSPORT:
    # Docker Compose: Connect to persistent MCP services via SSE/HTTP
else:
    # Local development: Launch Docker containers on-demand with stdio
```

### Comparison

| Feature | SSE Transport | stdio Transport |
|---------|---------------|-----------------|
| **Use Case** | Production, Docker Compose | Local development |
| **Performance** | Fast (persistent connection) | Slower (1-2s startup per request) |
| **Security** | Secure (no Docker socket) | Requires Docker socket mount |
| **Setup** | Requires MCP services running | Automatic on-demand |
| **Resource Usage** | Low (1 container per MCP server) | High (new container per request) |
| **Environment Variable** | `MCP_ATLASSIAN_URL` must be set | `MCP_ATLASSIAN_URL` not set |
| **Recommended** | ✅ Yes | ⚠️ Development only |

## Mode 1: SSE Transport (Docker Compose - Recommended)

**When Used**: When `MCP_ATLASSIAN_URL` and `MCP_GITLAB_URL` environment variables are set (Docker Compose deployments)

### Configuration

```python
multi_server_mcp_client = MultiServerMCPClient({
    "atlassian": {
        "url": f"{settings.mcp_atlassian_url}/sse",  # e.g., http://mcp-atlassian:3000/sse
        "transport": "sse"
    },
    "gitlab": {
        "url": f"{settings.mcp_gitlab_url}/sse",  # e.g., http://mcp-gitlab:3001/sse
        "transport": "sse"
    }
})
```

### Benefits:
- ✅ **Performance**: Persistent connections, no container startup overhead
- ✅ **Reliable**: Services are always ready to handle requests
- ✅ **Production-Ready**: Service-based architecture suitable for production
- ✅ **Secure**: No Docker socket mount required
- ✅ **Resource Efficient**: Single container per MCP server handles all requests


## Mode 2: stdio Transport (Local Development)

**When Used**: When `MCP_ATLASSIAN_URL` is not set (local development without Docker Compose)

### Benefits:
- ✅ **Simple Setup**: No Docker Compose required
- ✅ **Isolated**: Each request gets a fresh container
- ✅ **Self-Contained**: Docker handles container lifecycle

### Trade-offs:
- ⚠️ **Docker Socket Required**: Must mount `/var/run/docker.sock` if running in container
- ⚠️ **Startup Overhead**: ~1-2s container launch time per request
- ⚠️ **Security**: Docker socket access gives elevated privileges
- ⚠️ **Resource Usage**: Creates/destroys containers for each request

## Network Flow

### SSE Transport (Docker Compose)

```
User Request
    ↓
Streamlit UI Container
    ↓
SupervisorAgent
    ↓
SearchAgent
    ↓
MCP Client (multi_server_mcp_client.py)
    ↓
HTTP/SSE Connection → Persistent MCP Service
    ↓
MCP Container (mcp-atlassian:3000 or mcp-gitlab:3001)
    ├─ Maintains persistent SSE connection
    ├─ Makes API calls to Jira/Confluence/GitLab
    └─ Streams results via SSE
    ↓
Response flows back to user
```

### stdio Transport (Local Development)

```
User Request
    ↓
Streamlit UI Container
    ↓
SupervisorAgent
    ↓
SearchAgent
    ↓
MCP Client (multi_server_mcp_client.py)
    ↓
Docker Socket → Launch MCP Container
    ↓
MCP Container (ephemeral)
    ├─ Launched on-demand
    ├─ Makes API calls to Jira/Confluence/GitLab
    └─ Returns results via stdio
    ↓
Response flows back to user
    ↓
Container terminates (--rm flag)
```

## Security Considerations

### SSE Transport (Recommended for Production)

**Security Benefits**:
- ✅ **No Docker Socket Required**: Services run independently
- ✅ **Network Isolation**: Services communicate via Docker network only
- ✅ **Standard Service Communication**: Uses HTTP/SSE like any other microservice
- ✅ **Easier to Secure**: Standard network policies and firewalls apply

### stdio Transport (Development Only)

#### Docker Socket Mount

**Risk**: Containers with Docker socket access can:
- Launch any container
- Access other containers
- Potentially escape to host

**Mitigations**:
1. **Read-only mount**: `:ro` flag (though Docker API still allows container launches)
2. **Limited scope**: Only needed for local development
3. **No privileged mode**: Containers run unprivileged

### Production Recommendations

For production deployments, **always use SSE transport**:

1. ✅ **Use Docker Compose with SSE** (Current Implementation):
   ```yaml
   environment:
     - MCP_ATLASSIAN_URL=http://mcp-atlassian:3000
     - MCP_GITLAB_URL=http://mcp-gitlab:3001
   ```


2. **DO NOT** use Docker socket in production:
   - Never mount `/var/run/docker.sock` in production
   - stdio transport is for local development only

## Troubleshooting

### SSE Transport Issues

#### "Connection refused" or "Cannot connect to MCP server"

**Cause**: MCP service not running or wrong URL

**Fix**: 
```bash
# Check if MCP services are running
docker compose ps

# Check MCP service logs
docker compose logs mcp-atlassian
docker compose logs mcp-gitlab

# Verify environment variables
echo $MCP_ATLASSIAN_URL
echo $MCP_GITLAB_URL

# Test MCP service directly
curl http://localhost:3000/sse
```

#### "Tools not available" or Empty tool list

**Cause**: MCP service started but credentials not configured

**Fix**: Verify environment variables in docker-compose.yml:
```yaml
mcp-atlassian:
  environment:
    - CONFLUENCE_URL=${CONFLUENCE_URL}
    - CONFLUENCE_USERNAME=${CONFLUENCE_USERNAME}
    - CONFLUENCE_API_TOKEN=${CONFLUENCE_API_TOKEN}
    - JIRA_URL=${JIRA_URL}
    - JIRA_PERSONAL_TOKEN=${JIRA_PERSONAL_TOKEN}
```

### stdio Transport Issues (Local Development)

#### "No such file or directory: 'docker'"

**Cause**: Container doesn't have Docker CLI installed or can't access Docker socket

**Fix**: Ensure Dockerfile includes:
```dockerfile
# Install Docker CLI
RUN apt-get update && apt-get install -y docker.io
```

#### "Cannot connect to Docker daemon"

**Cause**: Docker socket not mounted

**Fix**: Verify docker-compose.yml has:
```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock:ro
```

### General Debugging

**Check which transport mode is active**:
```python
# In your code or Python shell
from framework_base.multi_server_mcp_client import USE_SSE_TRANSPORT
print(f"Using SSE Transport: {USE_SSE_TRANSPORT}")
```

**Test MCP client directly**:
```bash
cd framework_base
python3 multi_server_mcp_client.py
# Should print available tools
```

## Environment Variables

### Required for SSE Transport (Docker Compose)

```bash
# MCP Service URLs (set in docker-compose.yml or .env)
MCP_ATLASSIAN_URL=http://mcp-atlassian:3000
MCP_GITLAB_URL=http://mcp-gitlab:3001

# Atlassian Credentials (for MCP services)
CONFLUENCE_URL=https://your-company.atlassian.net/wiki
CONFLUENCE_USERNAME=your-email@company.com
CONFLUENCE_API_TOKEN=your-confluence-token
JIRA_URL=https://your-company.atlassian.net
JIRA_PERSONAL_TOKEN=your-jira-token
JIRA_SSL_VERIFY=false

# GitLab Credentials (for MCP service)
GITLAB_PERSONAL_ACCESS_TOKEN=your-gitlab-token
GITLAB_API_URL=https://gitlab.example.com
GITLAB_READ_ONLY_MODE=false
```

### Required for stdio Transport (Local Development)

```bash
# No MCP_ATLASSIAN_URL or MCP_GITLAB_URL needed
# Same Atlassian and GitLab credentials as above

# Optional
MCP_VERY_VERBOSE=true
```

## Transport Selection Logic

The implementation automatically determines which transport to use:

```python
# From multi_server_mcp_client.py
USE_SSE_TRANSPORT = hasattr(settings, 'mcp_atlassian_url') and settings.mcp_atlassian_url

if USE_SSE_TRANSPORT:
    # Use SSE (Docker Compose)
    print("Using SSE transport for persistent MCP services")
else:
    # Use stdio (Local Development)
    print("Using stdio transport with on-demand containers")
```

**Decision Tree**:
- If `MCP_ATLASSIAN_URL` is set → SSE Transport
- If `MCP_ATLASSIAN_URL` is not set → stdio Transport

## Future Improvements

1. ~~**HTTP/SSE Transport**~~: ✅ **IMPLEMENTED** - Use persistent MCP services
2. **Connection Pooling**: Cache SSE connections with reconnection logic
3. **Health Checks**: Monitor MCP service health and auto-restart
4. **Load Balancing**: Multiple MCP service replicas for high availability
5. **Metrics**: Add Prometheus metrics for MCP call latency and success rates
6. **Fallback Mode**: Auto-switch to stdio if SSE connection fails
