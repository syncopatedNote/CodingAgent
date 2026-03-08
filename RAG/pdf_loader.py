import uuid
from os import path
from framework_base.llm_base import LLMFactory
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain.retrievers.multi_vector import MultiVectorRetriever

# from langchain.storage import InMemoryStore
from framework_base.doc_store import get_document_store
from langchain.schema.document import Document
from framework_base.vector_store import get_vector_store
from utils import (
    extract_tables_from_pdf,
    extract_images_from_pdf,
    extract_text_from_pdf,
)


from logger import setup_logger


logger = setup_logger(__name__)

filename = "YOUR_FILE_NAME"


def extract_data():
    # read the pdf file.
    current_dir = path.dirname(path.abspath(__file__))
    file_path = path.join(
        current_dir,
        "pdf_files",
        "BP_Service_Order_Orchestration_Technical_Guide_24-08.pdf",
    )

    logger.info(f"file_path is {file_path}")

    tables = extract_tables_from_pdf(file_path=file_path)
    images_b64 = extract_images_from_pdf(filepath=file_path)
    texts = extract_text_from_pdf(filepath=file_path)

    logger.info(f"Total tables extracted: {len(tables)}")
    logger.info(f"Total images extracted: {len(images_b64)}")
    logger.info(f"Total texts extracted: {len(texts)}")

    prompt_text = """
    You are an assistant tasked with summarizing tables and text.
    Give a concise summary of the table or text.

    Respond only with the summary, no additionnal comment.
    Do not start your message by saying "Here is a summary" or anything like that.
    Just give the summary as it is.

    Table or text chunk: {element}

    """
    model = LLMFactory.create_llm(
        provider="ollama", model_name="llama3:8b", model_type="chat", temperature=0.5
    )

    prompt = ChatPromptTemplate.from_template(prompt_text)

    # Tables and Text Summary chain
    summarize_chain = {"element": lambda x: x} | prompt | model | StrOutputParser()

    tables_html = [table.to_html() for table in tables]
    print("STARTING TABLE AND TEXT SUMMARIZATION")
    table_summaries = summarize_chain.batch(tables_html, {"max_concurrency": 3})
    text_summaries = summarize_chain.batch(texts, {"max_concurrency": 3})

    # Summarize images
    # image_prompt_template = """Describe the image in detail. For context,
    #                         the image is part of a Ciena Blue Planet Service Order Orchestrator.
    #                         Be specific about graphs, such as bar plots."""
    # messages = [
    #     (
    #         "user",
    #         [
    #             {"type": "text", "text": image_prompt_template},
    #             {
    #                 "type": "image_url",
    #                 "image_url": {"url": "data:image/jpeg;base64,{image}"},
    #             },
    #         ],
    #     )
    # ]

    messages = [
        """
        You are an expert image analyst. The following is a base64-encoded image in data URI format.

        Image:
        {image}

        Describe the image in detail. For context,
        the image is part of a Ciena Blue Planet Service Order Orchestrator guide.
        Be specific about graphs, such as bar graphs or plots.
        Do not start your message by saying "Here is a summary" or anything like that.
        Just give the summary as it is.
        """
    ]

    images_prompt = ChatPromptTemplate.from_messages(messages)

    image_summary_chain = images_prompt | model | StrOutputParser()
    logger.info("STARTING IMAGE SUMMARIZATION")
    image_summaries = image_summary_chain.batch(images_b64)

    logger.info(f"first image summary is {image_summaries[0]}")
    logger.info(f"second image summary is {image_summaries[1]}")
    load_data(
        images=images_b64,
        image_summaries=image_summaries,
        texts=texts,
        text_summaries=text_summaries,
        tables=tables,
        table_summaries=table_summaries,
    )


def load_data(
    images: list,
    image_summaries: list,
    texts: list,
    text_summaries: list,
    tables: list,
    table_summaries: list,
):
    vectorstore = get_vector_store()
    # store = InMemoryStore()
    store = get_document_store()
    id_key = "doc_id"

    retriever = MultiVectorRetriever(
        vectorstore=vectorstore,
        docstore=store,
        id_key=id_key,
    )
    # Add texts
    doc_ids = [str(uuid.uuid4()) for _ in texts]
    summary_texts = [
        Document(page_content=summary, metadata={id_key: doc_ids[i]})
        for i, summary in enumerate(text_summaries)
    ]
    retriever.vectorstore.add_documents(summary_texts)
    retriever.docstore.mset(list(zip(doc_ids, texts)))

    # Add tables
    table_ids = [str(uuid.uuid4()) for _ in tables]
    summary_tables = [
        Document(page_content=summary, metadata={id_key: table_ids[i]})
        for i, summary in enumerate(table_summaries)
    ]
    retriever.vectorstore.add_documents(summary_tables)
    retriever.docstore.mset(list(zip(table_ids, tables)))

    # Add image summaries
    img_ids = [str(uuid.uuid4()) for _ in images]
    summary_img = [
        Document(page_content=summary, metadata={id_key: img_ids[i]})
        for i, summary in enumerate(image_summaries)
    ]
    retriever.vectorstore.add_documents(summary_img)
    retriever.docstore.mset(list(zip(img_ids, images)))


if __name__ == "__main__":
    extract_data()
    # initialize_retriever()
