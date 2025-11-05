import streamlit as st
from framework_base.llm_base import LLMFactory
from langchain.schema import HumanMessage, AIMessage, SystemMessage
from langchain.retrievers.multi_vector import MultiVectorRetriever
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from langchain_core.prompts import ChatPromptTemplate
from framework_base.vector_store import get_vector_store
from framework_base.doc_store import get_document_store
from base64 import b64decode
from langchain_core.output_parsers import StrOutputParser


# Initialize your retriever and LLM
@st.cache_resource
def initialize_chat_components():
    vectorstore = get_vector_store()
    store = get_document_store()
    id_key = "doc_id"
    retriever = MultiVectorRetriever(
        vectorstore=vectorstore,
        docstore=store,
        id_key=id_key,
    )
    llm = LLMFactory.create_llm(
        provider="ollama",
        model_name="llama3:8b",
        model_type="chat",
        temperature=0.7
    )
    return retriever, llm


def parse_docs(docs):
    """Split base64-encoded images and texts"""
    b64 = []
    text = []
    for doc in docs:
        try:
            b64decode(doc)
            b64.append(doc)
        except Exception as e:
            text.append(doc)
    return {"images": b64, "texts": text}


def get_context(question):
    docs = retriever.invoke(question)
    # print(f"docs are {docs}")
    print("*******************CONTEXT PASSED IS ********************")
    for doc in docs:
        print(str(doc) + "\n\n" + "-" * 80)
    print("*******************END OF CONTEXT ********************")
    return docs


def build_prompt(kwargs):

    docs_by_type = kwargs["context"]
    user_question = kwargs["question"]

    context_text = ""
    if len(docs_by_type["texts"]) > 0:
        for text_element in docs_by_type["texts"]:
            context_text += text_element[text_element["type"]]

    # construct prompt with context (including images)
    prompt_template = f"""
    Answer the question based only on the following context, which can include text, tables, and the below image.
    Context: {context_text}
    Question: {user_question}
    """

    prompt_content = [{"type": "text", "text": prompt_template}]

    if len(docs_by_type["images"]) > 0:
        for image in docs_by_type["images"]:
            prompt_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image}"},
                }
            )

    prompt_template = ChatPromptTemplate.from_messages(
        [
            HumanMessage(content=prompt_content),
        ]
    )
    print("prompt template is..........")
    print(prompt_template)
    return prompt_template


def generate_response(question, context, chat_history):
    """
    Generate a response using the LLM with context and chat history.

    Args:
        question (str): The current user question
        context (list): List of documents with relevant context
        chat_history (list): List of previous message exchanges

    Returns:
        str: The LLM's response content
    """
    # Combine context into a single string
    context_text = "\n".join([doc[doc["type"]] for doc in context])

    # Create system message with context
    system_message = SystemMessage(content=f"""You are a helpful AI assistant.
    Use the following context to answer the user's questions:
    {context_text}

    If the context doesn't contain relevant information, do not use your general knowledge to answer.
    Just say that you do not know the answer because the context was not provided.
    Always maintain conversation continuity based on the chat history.""")

    # Format chat history for the conversation
    formatted_history = []

    # Add system message at the start
    formatted_history.append(system_message)

    # Add previous conversation messages
    for message in chat_history:
        formatted_history.append(message)

    # Add current question
    formatted_history.append(HumanMessage(content=question))

    print("*******************LLM PROMPT IS ****************************************")
    print("Invoking llm with prompt: ")
    print(f"{formatted_history}")
    print("*************************************************************************")
    # Get LLM response
    response = llm.invoke(formatted_history)
    return response.content


retriever, llm = initialize_chat_components()

chain = (
    {
        "context": retriever | RunnableLambda(parse_docs),
        "question": RunnablePassthrough(),
    }
    | RunnableLambda(build_prompt)
    | llm
    | StrOutputParser()
)

# Initialize session state for chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Streamlit UI
st.title("AI Chat Assistant")

# Display chat messages from history on app rerun
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Chat input
if prompt := st.chat_input("What would you like to know?"):
    # Display user message in chat message container
    st.chat_message("user").markdown(prompt)
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            context = get_context(prompt)
            response = generate_response(prompt, context, st.session_state.messages)
            # response = chain.invoke(prompt)
            st.markdown(response)
            st.session_state.messages.append({"role": "assistant", "content": response})
