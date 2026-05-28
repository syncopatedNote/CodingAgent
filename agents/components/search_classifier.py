"""
Search Classifier — Hybrid keyword → LLM fallback

Determines which MCP server category a search query targets
(atlassian, github, gitlab, context7) before the search executes.
This lets the SearchAgent check server availability upfront and
reject queries whose backing service is not enabled.

Classification strategy:
  1. Keyword pass  — fast, zero-cost, deterministic.
  2. LLM fallback  — used only when keywords return UNKNOWN.
"""

import re
from enum import Enum
from typing import Optional

from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

from framework_base.llm_base import LLMFactory
from settings import settings
from logger import setup_logger

logger = setup_logger(__name__)


# ── Category definition ────────────────────────────────────────────


class SearchCategory(str, Enum):
    """Maps 1-to-1 with MCP server names in the registry."""

    ATLASSIAN = "atlassian"  # Confluence pages, Jira issues/epics/sprints
    GITHUB = "github"  # GitHub repos, PRs, issues, commits, actions
    GITLAB = "gitlab"  # GitLab repos, MRs, pipelines
    DOCUMENTATION = "context7"  # Library / framework docs via Context7
    UNKNOWN = "unknown"  # Could not be determined


# ── Keyword rules (order: most specific first) ─────────────────────

# Each tuple: (compiled regex, SearchCategory)
# Short-circuit on first match → order matters for overlapping terms.
_KEYWORD_RULES: list[tuple[re.Pattern, SearchCategory]] = [
    # ── Atlassian / Confluence / Jira ──────────────────────────────
    (
        re.compile(
            r"\b("
            r"confluence|jira|atlassian|"
            r"sprint|epic|story|backlog|"
            r"ticket|issue tracker|"
            r"confluence page|space|"
            r"jql|jira query"
            r")\b",
            re.IGNORECASE,
        ),
        SearchCategory.ATLASSIAN,
    ),
    # ── GitLab ─────────────────────────────────────────────────────
    (
        re.compile(
            r"\b("
            r"gitlab|merge request|"
            r"mr\s*#?\d*|"
            r"gitlab pipeline|gitlab ci|"
            r"gitlab repo"
            r")\b",
            re.IGNORECASE,
        ),
        SearchCategory.GITLAB,
    ),
    # ── GitHub ─────────────────────────────────────────────────────
    (
        re.compile(
            r"\b("
            r"github|"
            r"pull request|pr\s*#?\d*|"
            r"gh repo|"
            r"github action|github workflow|"
            r"git commit|git branch|"
            r"repository|repo"
            r")\b",
            re.IGNORECASE,
        ),
        SearchCategory.GITHUB,
    ),
    # ── Documentation / Context7 ───────────────────────────────────
    (
        re.compile(
            r"\b("
            r"documentation|docs|"
            r"library|framework|package|"
            r"api reference|sdk|"
            r"context7|"
            r"how (do|to) (use|install|import|configure)|"
            r"npm|pypi"
            r")\b",
            re.IGNORECASE,
        ),
        SearchCategory.DOCUMENTATION,
    ),
]


def _keyword_classify(query: str) -> SearchCategory:
    """Return the first keyword match, or UNKNOWN."""
    for pattern, category in _KEYWORD_RULES:
        if pattern.search(query):
            logger.debug(
                "Keyword classifier matched",
                category=category.value,
                query=query[:80],
            )
            return category
    logger.debug("Keyword classifier found no match, returning UNKNOWN")
    return SearchCategory.UNKNOWN


# ── LLM classifier (Pydantic structured output) ────────────────────


class _ClassifyOutput(BaseModel):
    category: SearchCategory = Field(
        description=(
            "The search category. Must be one of: "
            "atlassian, github, gitlab, context7, unknown"
        )
    )
    reasoning: str = Field(
        description="One sentence explaining why you chose the category."
    )


_CLASSIFY_PROMPT = """\
You are a search-routing assistant.  Classify the following search query into
exactly one category based on WHERE the information is most likely stored.

Categories:
  atlassian  — Confluence pages, Jira issues, epics, sprints, design docs
               stored in Atlassian products
  github     — GitHub repositories, pull requests, GitHub issues, commits,
               branches, GitHub Actions workflows
  gitlab     — GitLab repositories, merge requests, GitLab CI pipelines
  context7   — Library documentation, framework docs, package API references,
               technical how-to guides for open-source software
  unknown    — Cannot be determined from the query alone

Query: {query}

Respond with a JSON object matching this schema:
{format_instructions}

Important:
- Choose "unknown" only if the query is genuinely ambiguous across multiple
  categories, or refers to no specific system at all.
- Do NOT infer "github" just because code is mentioned; only use it when
  the query clearly targets a GitHub resource.
"""


async def _llm_classify(query: str) -> SearchCategory:
    """Call the LLM to classify the query. Falls back to UNKNOWN on error."""
    try:
        parser = PydanticOutputParser(pydantic_object=_ClassifyOutput)
        llm = LLMFactory.create_llm(
            provider=settings.llm_provider,
            model_name=settings.llm_model_name,
            model_type=settings.llm_model_type,
            temperature=0,
        )
        prompt = _CLASSIFY_PROMPT.format(
            query=query,
            format_instructions=parser.get_format_instructions(),
        )
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        result = parser.parse(response.content)
        logger.info(
            "LLM classifier",
            category=result.category.value,
            reason=result.reasoning,
        )
        return result.category
    except Exception as exc:
        logger.warning(
            "LLM classifier failed, defaulting to UNKNOWN",
            error=str(exc),
            exc_info=True,
        )
        return SearchCategory.UNKNOWN


# ── Public API ─────────────────────────────────────────────────────


async def classify_search_query(query: str) -> SearchCategory:
    """
    Classify *query* into a SearchCategory using the hybrid strategy:
      1. Fast keyword pass
      2. LLM fallback (only when keywords return UNKNOWN)

    Returns a SearchCategory (never raises).
    """
    category = _keyword_classify(query)
    logger.info(
        "Keyword classifier returned query category",
        category=category.value,
    )
    if category is SearchCategory.UNKNOWN:
        logger.info("Keyword classifier returned UNKNOWN — invoking LLM classifier")
        category = await _llm_classify(query)
    return category
