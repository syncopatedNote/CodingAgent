#!/usr/bin/env python3
"""
Enhanced Chat Interface with Simplified Supervisor Agent
Uses the new supervisor that routes between search and coding agents.
"""

import streamlit as st
import asyncio
from typing import List, Dict
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from agents.supervisor_agent import SupervisorAgent
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Page configuration
st.set_page_config(
    page_title="AI Assistant - Simplified Supervisor",
    page_icon="🤖",
    layout="wide"
)


@st.cache_resource
def initialize_supervisor():
    """Initialize the simplified supervisor agent"""
    return SupervisorAgent()


def convert_streamlit_to_langchain_messages(messages: List[Dict]) -> List[BaseMessage]:
    """Convert Streamlit message format to LangChain message format"""
    langchain_messages = []
    for msg in messages:
        if msg["role"] == "user":
            langchain_messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            langchain_messages.append(AIMessage(content=msg["content"]))
    return langchain_messages


async def run_supervisor_async(supervisor, user_input, conversation_history):
    """Run the supervisor agent asynchronously"""
    return await supervisor.run(user_input, conversation_history)


def run_supervisor_sync(supervisor, user_input, conversation_history):
    """Wrapper to run async supervisor in sync context"""
    try:
        # Try to get the current event loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're in an async context, but Streamlit runs sync
            # Use asyncio.run in a thread to avoid conflicts
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run, 
                    run_supervisor_async(supervisor, user_input, conversation_history)
                )
                return future.result()
        else:
            # No event loop running, safe to use asyncio.run
            return asyncio.run(run_supervisor_async(supervisor, user_input, conversation_history))
    except RuntimeError:
        # No event loop, safe to use asyncio.run
        return asyncio.run(run_supervisor_async(supervisor, user_input, conversation_history))


def display_task_analysis(result: Dict):
    """Display task analysis information in sidebar"""
    with st.sidebar:
        st.subheader("🧠 Task Analysis")

        task_type = result.get("task_type")
        confidence = result.get("confidence", 0)

        if task_type:
            # Display task type with emoji
            task_emoji = {
                "search_operation": "🔍",
                "code_generation": "💻", 
                "general_chat": "💬"
            }

            task_name = task_type.value if hasattr(task_type, 'value') else str(task_type)
            emoji = task_emoji.get(task_name, "❓")

            st.write(f"**Detected Task:** {emoji} {task_name.replace('_', ' ').title()}")
            st.write(f"**Confidence:** {confidence:.2f}")

            # Display extracted Jira tickets
            jira_tickets = result.get("extracted_jira_tickets", [])
            if jira_tickets:
                st.write("**Jira Tickets Found:**")
                for ticket in jira_tickets:
                    st.write(f"- {ticket}")

        # Display agent results summary
        if result.get("search_agent_result"):
            st.write("**🔍 Search Agent:** Executed")
            search_type = result["search_agent_result"].get("search_type")
            if search_type:
                st.write(f"- Search Type: {search_type.value if hasattr(search_type, 'value') else str(search_type)}")

        if result.get("coding_agent_result"):
            st.write("**💻 Coding Agent:** Executed")


def display_help_section():
    """Display help section in sidebar"""
    with st.sidebar:
        st.header("🚀 What I Can Do")

        st.subheader("🔍 Search Operations")
        st.markdown("""
        - **Find Confluence docs:** "Search for API documentation"
        - **Look up Jira tickets:** "Show me ticket PROJ-123"
        - **Search issues:** "Find recent bugs in DEV project"
        - **General search:** "Look for deployment guides"
        """)

        st.subheader("💻 Code Generation")
        st.markdown("""
        - **From Jira ticket:** "Generate code for DEV-456"
        - **Implement feature:** "Implement the feature in STORY-789"
        - **Build component:** "Write code for TASK-123"
        """)

        st.subheader("💬 General Help")
        st.markdown("""
        - Ask about capabilities
        - Get guidance on workflows
        - Learn about available tools
        """)


def display_example_queries():
    """Display example queries as clickable buttons"""
    with st.sidebar:
        st.header("📝 Try These Examples")

        examples = [
            ("🔍 Search API docs", "Search for API authentication documentation"),
            ("🎫 Find ticket", "Show me details for PROJ-123"),
            ("💻 Generate code", "Generate code for CBP-8446"),
            ("🐛 Find bugs", "Search for recent bugs in production"),
            ("📚 Confluence search", "Find confluence pages about deployment"),
            ("❓ Get help", "What can you help me with?")
        ]

        for label, query in examples:
            if st.button(label, key=f"example_{query}", use_container_width=True):
                st.session_state.example_query = query


def main():
    # Initialize supervisor agent
    supervisor = initialize_supervisor()

    # App header
    st.title("🤖 AI Assistant - Simplified Supervisor")
    st.markdown("*Intelligent routing between search and code generation*")

    # Display help and examples in sidebar
    display_help_section()
    display_example_queries()

    # Initialize session state
    if "messages" not in st.session_state:
        st.session_state.messages = []

    if "supervisor_state" not in st.session_state:
        st.session_state.supervisor_state = None

    # Display chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Handle example query selection
    if hasattr(st.session_state, 'example_query'):
        user_input = st.session_state.example_query
        del st.session_state.example_query
    else:
        user_input = st.chat_input("What would you like me to help you with?")

    # Process user input
    if user_input:
        # Display user message
        st.chat_message("user").markdown(user_input)
        st.session_state.messages.append({"role": "user", "content": user_input})

        with st.chat_message("assistant"):
            # Create a placeholder for progressive updates
            response_placeholder = st.empty()
            
            with st.spinner("🔄 Processing your request..."):
                try:
                    # Convert messages to LangChain format
                    conversation_history = convert_streamlit_to_langchain_messages(
                        st.session_state.messages[:-1]  # Exclude the current message
                    )

                    # Show initial processing message
                    response_placeholder.markdown("🔄 **Processing your request...**")

                    # Run supervisor agent (now handling async properly)
                    result = run_supervisor_sync(supervisor, user_input, conversation_history)
                    st.session_state.supervisor_state = result

                    # Display the response with proper formatting
                    response = result.get("final_response", "I'm sorry, I couldn't process your request.")
                    
                    # Clear the placeholder and show the final response
                    response_placeholder.empty()
                    st.markdown(response)

                    # Add to message history
                    st.session_state.messages.append({"role": "assistant", "content": response})

                    # Display task analysis in sidebar
                    display_task_analysis(result)

                    # Show additional info if user input is required
                    if result.get("requires_user_input"):
                        st.info("💡 **Additional Information Needed** - Please provide the requested details in your next message.")

                except Exception as e:
                    error_msg = f"## ❌ Error\n\nAn error occurred while processing your request:\n\n```\n{str(e)}\n```\n\nPlease try again or rephrase your request."
                    response_placeholder.empty()
                    st.error("An error occurred while processing your request.")
                    st.markdown(error_msg)
                    st.session_state.messages.append({"role": "assistant", "content": error_msg})

    # Display current state info (for debugging)
    if st.session_state.supervisor_state:
        with st.expander("🔧 Debug Information", expanded=False):
            col1, col2 = st.columns(2)

            with col1:
                st.subheader("Task Classification")
                st.json({
                    "task_type": str(st.session_state.supervisor_state.get("task_type", "")),
                    "confidence": st.session_state.supervisor_state.get("confidence", 0),
                    "jira_tickets": st.session_state.supervisor_state.get("extracted_jira_tickets", [])
                })

            with col2:
                st.subheader("Agent Results")
                agent_info = {}
                if st.session_state.supervisor_state.get("search_agent_result"):
                    agent_info["search_agent"] = "executed"
                if st.session_state.supervisor_state.get("coding_agent_result"):
                    agent_info["coding_agent"] = "executed"
                st.json(agent_info)

    # Footer with controls
    st.markdown("---")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if st.button("🗑️ Clear Chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.supervisor_state = None
            st.rerun()

    with col2:
        if st.button("📊 Show Full Debug", use_container_width=True):
            if st.session_state.supervisor_state:
                st.json(st.session_state.supervisor_state)

    with col3:
        if st.button("💾 Export Chat", use_container_width=True):
            chat_export = "\n".join([
                f"{msg['role'].upper()}: {msg['content']}" 
                for msg in st.session_state.messages
            ])
            st.download_button(
                label="Download",
                data=chat_export,
                file_name="chat_history.txt",
                mime="text/plain",
                use_container_width=True
            )

    with col4:
        # Environment status
        # env_status = "🟢" if os.getenv("OPENAI_API_KEY") and os.getenv("GITLAB_PROJECT_ID") else "🟡"
        env_status = "🟢"
        st.button(f"{env_status} Coding Agent", disabled=False, use_container_width=True)

    # Status bar at bottom
    st.markdown("---")
    status_col1, status_col2, status_col3 = st.columns(3)

    with status_col1:
        st.caption("🔍 Search Agent: Always Available")

    with status_col2:
        # coding_status = "Available" if os.getenv("OPENAI_API_KEY") and os.getenv("GITLAB_PROJECT_ID") else "Needs Configuration"
        st.caption(f"💻 Coding Agent: configured")

    with status_col3:
        message_count = len(st.session_state.messages)
        st.caption(f"💬 Messages: {message_count}")


if __name__ == "__main__":
    main()
