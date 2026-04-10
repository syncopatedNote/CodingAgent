from typing import TypedDict, List
from langgraph.graph.state import StateGraph, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from framework_base.llm_base import LLMFactory
from settings import settings

# Initialize LLM using settings
llm_kwargs = {"temperature": 0.5}

# Add base_url for ollama if provider is ollama
if settings.llm_provider.lower() == "ollama" and settings.ollama_base_url:
    llm_kwargs["base_url"] = settings.ollama_base_url

model = LLMFactory.create_llm(
    provider=settings.llm_provider,
    model_name=settings.llm_model_name,
    model_type=settings.llm_model_type,
    **llm_kwargs,
)


class AgentState(TypedDict):
    messages: List[BaseMessage]
    enhanced_question: str


def start_node(state: AgentState) -> AgentState:
    """Start node - validates input and prepares state"""
    if not state["messages"]:
        raise ValueError("No messages provided")
    return state


def _is_error_message(content: str) -> bool:
    """Return True if the message content is an agent error response."""
    error_markers = (
        "❌",
        "cannot perform this search",
        "search error",
        "mcp server",
        "not available",
        "i'm having trouble",
        "something went wrong",
        "i couldn't generate",
        "i encountered an error",
    )
    lowered = content.lower()
    return any(marker.lower() in lowered for marker in error_markers)


def enhance_node(state: AgentState) -> AgentState:
    """
    Enhance node - rephrases the last question using conversation history.

    Only the most recent successful exchange (1 human + 1 AI turn) is used
    as context.  Error responses are stripped out entirely so they cannot
    bleed into unrelated follow-up questions.
    """
    messages = state["messages"]
    last_message = messages[-1].content

    # All messages except the current question
    prior_messages = messages[:-1]

    # 1. Strip error / system-failure responses — they carry no useful context.
    meaningful_prior = [
        msg
        for msg in prior_messages
        if msg.content
        and len(msg.content.strip()) > 10
        and not _is_error_message(msg.content)
    ]

    # 2. No usable history → return unchanged
    if not meaningful_prior:
        state["enhanced_question"] = last_message
        return state

    # 3. Use only the single most recent exchange (last human + last AI pair)
    #    to avoid cross-contamination from older, unrelated topics.
    recent_context = meaningful_prior[-2:]  # at most [HumanMessage, AIMessage]

    context = "\n".join(
        [f"{msg.__class__.__name__}: {msg.content}" for msg in recent_context]
    )

    enhancement_prompt = f"""Your task is to rephrase a question to add useful \
context from the immediately preceding conversation exchange — but ONLY when the \
current question is a genuine follow-up to that exchange.

Rules (follow strictly):
1. If the current question targets a DIFFERENT system, service, or topic than the \
previous exchange, return it UNCHANGED.
2. If the current question is already self-contained and specific, return it UNCHANGED.
3. Only add context when the current question is a direct follow-up (e.g. "what about \
the other one?" or "give me more detail on that").
4. Never merge two unrelated topics together.
5. Return ONLY the (possibly enhanced) question — no explanation, no preamble.

Example of when NOT to enhance:
  Previous: "get broadband design docs from Confluence"
  Current:  "get details of the abc repository on GitLab"
  → Return unchanged: "get details of the abc repository on GitLab"
  (Different systems, unrelated topics.)

Example of when TO enhance:
  Previous: "get details of the abc repository on GitLab"
  Current:  "what open merge requests does it have?"
  → Enhanced: "what open merge requests does the abc repository on GitLab have?"

Recent conversation:
{context}

Current question: {last_message}

Enhanced question:"""

    llm = model
    response = llm.invoke([HumanMessage(content=enhancement_prompt)])

    # Handle both string responses and message objects
    if hasattr(response, "content"):
        enhanced_text = response.content
    else:
        enhanced_text = str(response)

    state["enhanced_question"] = enhanced_text.strip()
    return state


def end_node(state: AgentState) -> AgentState:
    """End node - finalizes the process"""
    return state


# Create the workflow
workflow = StateGraph(AgentState)

# Add nodes
workflow.add_node("start", start_node)
workflow.add_node("enhance", enhance_node)
workflow.add_node("end", end_node)

# Add edges
workflow.add_edge("start", "enhance")
workflow.add_edge("enhance", "end")
workflow.add_edge("end", END)

# Set entry point
workflow.set_entry_point("start")

# Compile the graph
enhancer_app = workflow.compile()


def enhance_question(messages: List[BaseMessage]) -> str:
    """Main function to enhance a question using conversation history"""
    initial_state = {"messages": messages, "enhanced_question": ""}
    result = enhancer_app.invoke(initial_state)
    return result["enhanced_question"]


# Example usage
if __name__ == "__main__":
    # Example conversation
    conversation = [
        HumanMessage(content="What is machine learning?"),
        AIMessage(
            content="Machine learning is a subset of AI that enables computers to learn from data."
        ),
        HumanMessage(content="How does it work in practice?"),
    ]

    enhanced = enhance_question(conversation)
    print(f"Original: {conversation[-1].content}")
    print(f"Enhanced: {enhanced}")
