from typing import Optional

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except Exception:
    ChatGoogleGenerativeAI = None

from settings import settings


def create_gcp(
    model_name: str,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    **kwargs,
) -> object:
    # Prefer Vertex AI (when project provided); otherwise use Gemini API key
    project = kwargs.get("project") or settings.gcp_project
    api_key = kwargs.get("api_key") or settings.google_api_key
    vertexai = kwargs.get("vertexai")

    if ChatGoogleGenerativeAI is None:
        raise ImportError(
            "langchain_google_genai not installed; install langchain-google"
        )

    gcp_kwargs = {
        "model": model_name,
        "temperature": temperature,
    }
    if max_tokens:
        gcp_kwargs["max_tokens"] = max_tokens
    if project:
        gcp_kwargs["project"] = project
        # If a project is provided, default to Vertex AI backend unless
        # explicitly disabled
        if vertexai is None:
            gcp_kwargs["vertexai"] = True
        else:
            gcp_kwargs["vertexai"] = bool(vertexai)
    elif api_key:
        gcp_kwargs["api_key"] = api_key

    return ChatGoogleGenerativeAI(**gcp_kwargs)
