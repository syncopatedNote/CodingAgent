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


def enhance_node(state: AgentState) -> AgentState:
    """
    Enhance node - rephrases the last question
    using conversation history
    """
    messages = state["messages"]
    last_message = messages[-1].content

    # Check if there's meaningful conversation history
    # (more than just the current question)
    # All messages except the current one
    conversation_history = messages[:-1]

    # If there's no conversation history,
    # return the original question unchanged
    if not conversation_history:
        state["enhanced_question"] = last_message
        return state

    # Filter out empty or very short messages that don't add context
    meaningful_history = [
        msg
        for msg in conversation_history
        if msg.content and len(msg.content.strip()) > 10
    ]

    # If no meaningful history, return original question
    if not meaningful_history:
        state["enhanced_question"] = last_message
        return state

    # Build context from meaningful conversation history
    context = "\n".join(
        [f"{msg.__class__.__name__}: {msg.content}" for msg in meaningful_history]
    )

    # Create enhancement prompt
    enhancement_prompt = f"""
                Given the conversation history and the current question,
                rephrase the question to be more specific and contextual
                for better vector store retrieval.
                Only enhance if the current question is a follow-up that
                would benefit from previous context. If the question is
                already clear and specific, return it unchanged.
                Return ONLY the enhanced question without any explanation
                or additional text.

                Conversation History:
                {context}

                Current Question: {last_message}

                Enhanced Question (add context only if needed):
                """

    llm = model
    response = llm.invoke([HumanMessage(content=enhancement_prompt)])

    # Handle both string responses and message objects
    if hasattr(response, 'content'):
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
