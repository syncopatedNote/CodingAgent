"""
Coding pipeline package: context collection + code generation.

``CodingPipeline`` is the single entry point callers should use; it chains the
``ContextCollectorAgent`` and the ``LangGraphCodingAgent``.
"""

from .coding_pipeline import CodingPipeline
from .coding_agent.langgraph_coding_agent import LangGraphCodingAgent
from .collector_agent import ContextCollectorAgent, ContextBundle

__all__ = [
    "CodingPipeline",
    "LangGraphCodingAgent",
    "ContextCollectorAgent",
    "ContextBundle",
]
