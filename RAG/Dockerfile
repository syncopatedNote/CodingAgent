FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the RAG service code — not the rest of the monorepo
COPY RAG/main.py RAG/settings.py ./
COPY RAG/routes/ ./routes/
COPY RAG/services/ ./services/

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
