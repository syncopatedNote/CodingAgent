# Consolidated Docker Compose Setup

This setup includes:
- **Agent UI** (Next.js frontend) - Port 3000
- **Supervisor API** (Python backend) - Port 8000  
- **LiteLLM Proxy** (LLM gateway) - Port 4000
- **MongoDB** (Document storage) - Port 27017
- **PostgreSQL** (LiteLLM database) - Port 5432
- **MCP Atlassian Server** (Jira/Confluence) - Port 3001
- **MCP GitLab Server** - Port 3333
- **Mongo Express** (Database GUI, optional) - Port 8081

## Quick Start

### 1. Configure Environment Variables

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env and fill in your actual values
nano .env
```

### 2. Start All Services

```bash
# Build and start all services
docker-compose up -d

# View logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f agent-ui
docker-compose logs -f supervisor-api
docker-compose logs -f litellm
```

### 3. Access Services

- **Agent UI**: http://localhost:3000
- **Supervisor API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **LiteLLM**: http://localhost:4000
- **LiteLLM UI**: http://localhost:4000/ui
- **Mongo Express**: http://localhost:8081

## Service Architecture

```
┌─────────────────┐
│   Agent UI      │  Port 3000 (Next.js)
│   (Frontend)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────┐
│ Supervisor API  │────▶│  LiteLLM     │  Port 4000
│   (Backend)     │     │  (LLM Proxy) │
└────────┬────────┘     └──────┬───────┘
         │                     │
         ├──────────────┬──────┴──────┬────────────┐
         ▼              ▼             ▼            ▼
    ┌────────┐    ┌──────────┐  ┌─────────┐  ┌──────────┐
    │MongoDB │    │MCP       │  │MCP      │  │PostgreSQL│
    │        │    │Atlassian │  │GitLab   │  │(LiteLLM) │
    └────────┘    └──────────┘  └─────────┘  └──────────┘
```

## LiteLLM Configuration

The `litellm_config.yaml` file defines available models:

- **OpenAI**: gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo
- **Anthropic**: claude-3-5-sonnet, claude-3-opus
- **AWS Bedrock**: bedrock-claude-3-sonnet, bedrock-claude-3-haiku

### Using LiteLLM

```python
import openai

client = openai.OpenAI(
    api_key="",  # LITELLM_MASTER_KEY from .env
    base_url="http://localhost:4000"
)

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

## Management Commands

### Start/Stop Services

```bash
# Start all services
docker-compose up -d

# Stop all services
docker-compose down

# Stop and remove volumes (WARNING: deletes data)
docker-compose down -v

# Restart specific service
docker-compose restart agent-ui

# Rebuild and restart
docker-compose up -d --build
```

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f supervisor-api

# Last 100 lines
docker-compose logs --tail=100 litellm
```

### Execute Commands in Containers

```bash
# Access agent-ui shell
docker-compose exec agent-ui sh

# Access supervisor-api shell
docker-compose exec supervisor-api bash

# Run Python script in supervisor-api
docker-compose exec supervisor-api python script.py

# Access MongoDB
docker-compose exec mongodb mongosh -u admin -p password

# Access PostgreSQL (LiteLLM)
docker-compose exec litellm-db psql -U litellm
```

### Health Checks

```bash
# Check all service health
docker-compose ps

# Check specific service
curl http://localhost:8000/health
curl http://localhost:4000/health
curl http://localhost:3000
```

## Development Mode

For development, you can run services individually:

```bash
# Run only Agent UI locally (outside Docker)
cd Agent_UI
npm install
npm run dev

# Run only Supervisor API locally
cd Coding_agent
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Run supporting services via Docker
docker-compose up mongodb litellm mcp-atlassian mcp-gitlab -d
```

## Troubleshooting

### Agent UI not building

```bash
# Check Next.js build logs
docker-compose logs agent-ui

# Rebuild without cache
docker-compose build --no-cache agent-ui
docker-compose up -d agent-ui
```

### LiteLLM connection issues

```bash
# Verify LiteLLM is running
curl http://localhost:4000/health

# Check configuration
docker-compose exec litellm cat /app/config.yaml

# View LiteLLM logs
docker-compose logs -f litellm
```

### Database connection errors

```bash
# Check MongoDB status
docker-compose exec mongodb mongosh --eval "db.adminCommand('ping')"

# Check PostgreSQL status
docker-compose exec litellm-db pg_isready -U litellm

# View database logs
docker-compose logs mongodb
docker-compose logs litellm-db
```

### Port conflicts

If ports are already in use:

```bash
# Check what's using the port
lsof -i :3000
lsof -i :8000

# Kill the process or change ports in docker-compose.yml
```

## Updating Services

```bash
# Pull latest images
docker-compose pull

# Rebuild custom services
docker-compose build

# Restart with new images/builds
docker-compose up -d
```

## Backup and Restore

### Backup MongoDB

```bash
docker-compose exec mongodb mongodump --out /backup
docker cp supervisor-mongodb:/backup ./mongodb-backup
```

### Restore MongoDB

```bash
docker cp ./mongodb-backup supervisor-mongodb:/backup
docker-compose exec mongodb mongorestore /backup
```

## Environment Variables Reference

See `.env.example` for all available configuration options.

Key variables:
- `OPENAI_API_KEY`: OpenAI API key
- `LITELLM_MASTER_KEY`: Master key for LiteLLM proxy
- `MONGO_USERNAME/MONGO_PASSWORD`: MongoDB credentials
- `NEXT_PUBLIC_API_URL`: Backend API URL for frontend

## Production Deployment

For production:

1. **Update environment variables** with production values
2. **Enable HTTPS** using a reverse proxy (nginx, Caddy, Traefik)
3. **Use secrets management** instead of .env file
4. **Configure backups** for databases
5. **Set up monitoring** (Prometheus, Grafana)
6. **Review security settings** in all services
7. **Use production-grade database passwords**

## Support

For issues or questions:
- Check logs: `docker-compose logs -f`
- Review configuration files
- Ensure all required environment variables are set
