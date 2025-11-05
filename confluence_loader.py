import os
import uuid
from typing import List, Tuple
from bs4 import BeautifulSoup
import base64
import requests
from langchain_community.document_loaders import ConfluenceLoader
from langchain_core.documents.base import Document
from framework_base.llm_base import LLMFactory
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain.retrievers.multi_vector import MultiVectorRetriever
from framework_base.doc_store import get_document_store
from framework_base.vector_store import get_vector_store
from logger import setup_logger

logger = setup_logger(__name__)


class ConfluenceExtractor:
    def __init__(
        self,
        confluence_url: str,
        username: str,
        api_key: str,
        space_key: str,
        page_id: str
    ):
        self.confluence_url = confluence_url
        self.api_key = api_key
        self.space_key = space_key
        self.page_id = page_id
        self.username = username
        self.loader = ConfluenceLoader(
            url=confluence_url,
            username=username,
            api_key=api_key,
            space_key=space_key
        )

    def extract_tables_from_html(self, doc: Document) -> List[str]:
        """Extract tables from HTML content"""
        html_content = doc.page_content
        soup = BeautifulSoup(html_content, 'html.parser')
        tables = soup.find_all('table')
        return [str(table) for table in tables]

    def extract_images_from_html(self, doc: Document) -> List[str]:
        """Extract images from HTML content and convert to base64"""
        html_content = doc.page_content
        page_id = doc.metadata.get("id")
        print(f"PAGE ID IS {page_id}")
        print(f"HTML CONTENT IS {html_content}")
        print(f"DOC IS: {doc}")
        base64_images = []

        headers = {
            "Authorization": f"Basic {self.api_key}",
            "Accept": "application/json"
        }
        # Create directory for storing images
        image_dir = "confluence_images"
        os.makedirs(image_dir, exist_ok=True)

        try:
            # First get the page content with expanded attachments
            page_url = f"{self.confluence_url}/rest/api/content/{page_id}?expand=body.storage,children.attachment"
            page_response = requests.get(page_url, headers=headers)

            if page_response.status_code == 200:
                page_data = page_response.json()
                print(f"page data is {page_data}")
                # Get the HTML content from body.storage.value
                if 'body' in page_data and 'storage' in page_data['body']:
                    html_content = page_data['body']['storage']['value']

                    # Parse the HTML content
                    soup = BeautifulSoup(html_content, 'lxml')

                    # Find all ri:attachment tags within ac:image tags
                    image_tags = soup.find_all('ri:attachment')
                    print(f"Found {len(image_tags)} image attachment references")
                    print(f"Image tags: {image_tags}")

                    # Get all attachments
                    if 'children' in page_data and 'attachment' in page_data['children']:
                        attachments = page_data['children']['attachment']['results']
                        attachment_map = {att['title']: att.get('_links', {}).get('download', '') for att in attachments}
                        print(f"attachment_map is {attachment_map}")

                        for img_tag in image_tags:
                            filename = img_tag.get('ri:filename')
                            print(f"searching for filename {filename} in attachment_map")
                            if filename and filename in attachment_map:
                                dl_path = attachment_map[filename]
                                # download_url = f"{self.confluence_url}/rest/api/content/{page_id}/child/attachment/{attachment_id}/download"
                                download_url = f"{self.confluence_url}{dl_path}"

                                try:
                                    response = requests.get(
                                        download_url,
                                        headers=headers,
                                        allow_redirects=True)

                                    if response.status_code == 200:
                                        image_data = response.content
                                        # Save the image file
                                        file_path = os.path.join(image_dir, filename)
                                        with open(file_path, 'wb') as f:
                                            f.write(image_data)
                                        print(f"Saved image to {file_path}")
                                        base64_image = base64.b64encode(image_data).decode('utf-8')
                                        base64_images.append({
                                            'filename': filename,
                                            'base64_data': base64_image
                                        })
                                        print(f"Successfully downloaded image: {filename}")
                                    else:
                                        print(f"Failed to download image {filename}. Status: {response.status_code}")
                                except Exception as e:
                                    print(f"Error downloading image {filename}: {str(e)}")
                    else:
                        print("No attachments found in page data")
                else:
                    print("No body.storage found in page data")
            else:
                print(f"Failed to get page content. Status: {page_response.status_code}")

        except Exception as e:
            print(f"Error processing page: {str(e)}")
            logger.exception(f"Error processing page: {str(e)}")

        print(f"Total images processed: {len(base64_images)}")
        return base64_images

    def extract_text_from_html(self, doc: Document) -> List[str]:
        """Extract text content from HTML"""
        html_content = doc.page_content
        soup = BeautifulSoup(html_content, 'html.parser')
        page_id = doc.metadata.get('page_id')
        # Remove script and style elements
        for element in soup(['script', 'style']):
            element.decompose()

        # Get text and split into meaningful chunks
        text = soup.get_text(separator=' ', strip=True)

        chunks = [chunk.strip()
                  for chunk in text.split('\n\n') if chunk.strip()]
        final_text = ""
        clean_chunks = [final_text+chunk for chunk in chunks]
        return [{"page": page_id, "type": "text", "text": clean_chunks[0]}]

    def extract_data(self) -> Tuple[List[str], List[str], List[str]]:
        """Extract all content from Confluence pages"""
        # Load main page and all child pages
        # Set to true to download child pages
        documents = self.loader.load(
            page_ids=[self.page_id], include_children=False)

        all_tables = []
        all_images = []
        all_texts = []

        for doc in documents:
            # html_content = doc.page_content

            # Extract content
            tables = self.extract_tables_from_html(doc)
            images = self.extract_images_from_html(doc)
            texts = self.extract_text_from_html(doc)

            all_tables.extend(tables)
            all_images.extend(images)
            all_texts.extend(texts)

        logger.info(f"Total tables extracted: {len(all_tables)}")
        logger.info(f"Total images extracted: {len(all_images)}")
        logger.info(f"Total texts extracted: {len(all_texts)}")
        logger.info(f"Images extracted are: {all_images[1]}")
        return all_tables, all_images, all_texts


def load_confluence_content(
    confluence_url: str,
    username: str,
    api_key: str,
    space_key: str,
    page_id: str
):
    """Main function to load and process Confluence content"""

    # Initialize extractor
    extractor = ConfluenceExtractor(
        confluence_url, username, api_key, space_key, page_id)

    # Extract content
    tables, images, texts = extractor.extract_data()
    images = [img['base64_data'] for img in images]
    print("*****************************TEXTS EXTRACTED FROM PAGE ARE*******************************")
    print(texts)
    print("*****************************TEXTS EXTRACTED FROM PAGE ARE*******************************")
    # Initialize LLM
    model = LLMFactory.create_llm(
        provider="ollama",
        model_name="llama3:8b",
        model_type="chat",
        temperature=0.5
    )

    # Define prompts
    text_table_prompt = """
    You are an assistant tasked with summarizing tables and text.
    Give a concise summary of the table or text.
    Respond only with the summary, no additional comment.
    Do not start your message by saying "Here is a summary" or anything like that.
    Just give the summary as it is.
    Table or text chunk: {element}
    """

    image_prompt = """
    You are an expert image analyst. The following is a base64-encoded image in data URI format.
    Image:
    {image}
    Describe the image in detail. For context, this image is from a Confluence page.
    Be specific about any diagrams, charts, or visual elements.
    Do not start your message by saying "Here is a summary" or anything like that.
    Just give the summary as it is.
    """

    # Create chains
    text_table_chain = (
        ChatPromptTemplate.from_template(text_table_prompt)
        | model
        | StrOutputParser()
    )

    image_chain = (
        ChatPromptTemplate.from_template(image_prompt)
        | model
        | StrOutputParser()
    )

    # get text from extracted texts
    processed_texts = []
    for text_dict in texts:
        processed_texts.extend({"element": text_dict["text"]})

    # Generate summaries
    logger.info("Starting table and text summarization")
    table_summaries = text_table_chain.batch(tables, {"max_concurrency": 3})
    text_summaries = text_table_chain.batch(
        processed_texts, {"max_concurrency": 3})

    logger.info("Starting image summarization")
    image_summaries = image_chain.batch(images, {"max_concurrency": 3})

    # Store in vector store and document store
    vectorstore = get_vector_store()
    store = get_document_store()

    retriever = MultiVectorRetriever(
        vectorstore=vectorstore,
        docstore=store,
        id_key="doc_id",
    )

    # Store texts
    doc_ids = [str(uuid.uuid4()) for _ in texts]
    summary_texts = [
        Document(page_content=summary, metadata={"doc_id": doc_ids[i]})
        for i, summary in enumerate(text_summaries)
    ]
    retriever.vectorstore.add_documents(summary_texts)
    retriever.docstore.mset(list(zip(doc_ids, texts)))

    # Store tables
    table_ids = [str(uuid.uuid4()) for _ in tables]
    summary_tables = [
        Document(page_content=summary, metadata={"doc_id": table_ids[i]})
        for i, summary in enumerate(table_summaries)
    ]
    retriever.vectorstore.add_documents(summary_tables)
    retriever.docstore.mset(list(zip(table_ids, tables)))

    # Store images
    img_ids = [str(uuid.uuid4()) for _ in images]
    summary_img = [
        Document(page_content=summary, metadata={"doc_id": img_ids[i]})
        for i, summary in enumerate(image_summaries)
    ]
    retriever.vectorstore.add_documents(summary_img)
    retriever.docstore.mset(list(zip(img_ids, images)))


if __name__ == "__main__":
    # Load these from environment variables in production
    CONFLUENCE_URL = "https://confluence.com"
    API_KEY = ""
    SPACE_KEY = None
    PAGE_ID = "281959511"
    USERNAME = "611235921"

    load_confluence_content(
        confluence_url=CONFLUENCE_URL,
        username=USERNAME,
        api_key=API_KEY,
        space_key=SPACE_KEY,
        page_id=PAGE_ID
    )
