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

    def _get_auth_headers(self):
        """Create proper authentication headers"""
        auth_string = f"{self.username}:{self.api_key}"
        encoded_auth = base64.b64encode(auth_string.encode()).decode()
        return {
            "Authorization": f"Basic {encoded_auth}",
            "Accept": "application/json"
        }

    def extract_tables_from_html(self, doc: Document) -> List[str]:
        """Extract tables from HTML content"""
        html_content = doc.page_content
        soup = BeautifulSoup(html_content, 'html.parser')
        tables = soup.find_all('table')
        if tables:
            return [str(table) for table in tables]
        else:
            return []

    def extract_images_from_html(self, doc: Document) -> List[str]:
        """Extract images from HTML content and convert to base64"""
        html_content = doc.page_content
        page_id = doc.metadata.get("id")
        print(f"PAGE ID IS {page_id}")
        print(f"HTML CONTENT IS {html_content}")
        print(f"DOC IS: {doc}")
        base64_images = []

        headers = self._get_auth_headers()

        # Create directory for storing images
        image_dir = "confluence_images"
        os.makedirs(image_dir, exist_ok=True)

        # Create a session to maintain cookies
        session = requests.Session()
        session.headers.update(headers)

        try:
            # Get page data with attachments
            endpoint = f"{self.confluence_url}/rest/api/content/{page_id}?expand=body.storage,children.attachment"
            print(f"Getting attachments from: {endpoint}")

            response = session.get(endpoint, timeout=30)
            print(f"Response status: {response.status_code}")

            if response.status_code != 200:
                print(f"Failed to get page data: {response.status_code} - {response.text[:200]}")
                return base64_images

            page_data = response.json()

            # Extract attachments
            attachments = []
            if 'children' in page_data and 'attachment' in page_data['children']:
                attachments = page_data['children']['attachment'].get('results', [])
                print(f"Found {len(attachments)} attachments")
            else:
                print("No attachments found in page data")
                return base64_images

            if page_data and 'body' in page_data and 'storage' in page_data['body']:
                page_data = page_data
                print(f"page data is {page_data}")
                # Get the HTML content from body.storage.value
                html_content = page_data['body']['storage']['value']

                # Parse the HTML content
                soup = BeautifulSoup(html_content, 'lxml')

                # Find all ri:attachment tags within ac:image tags
                image_tags = soup.find_all('ri:attachment')
                print(f"Found {len(image_tags)} image attachment references")
                print(f"Image tags: {image_tags}")

                # Process attachments (already retrieved above)
                if attachments:
                    attachment_map = {att['title']: att.get('_links', {}).get('download', '') for att in attachments}
                    print(f"attachment_map is {attachment_map}")

                    for img_tag in image_tags:
                        filename = img_tag.get('ri:filename')
                        print(f"searching for filename {filename} in attachment_map")
                        if filename and filename in attachment_map:
                            dl_path = attachment_map[filename]
                            download_url = f"{self.confluence_url}{dl_path}"

                            try:
                                print(f"Attempting download with URL: {download_url}")
                                response = session.get(download_url, allow_redirects=True, timeout=30)
                                print(f"Download status: {response.status_code}")

                                if response.status_code == 200:
                                    image_data = response.content

                                    # Check image size - skip if too large for MongoDB (>15MB)
                                    image_size_mb = len(image_data) / (1024 * 1024)
                                    if image_size_mb > 15:
                                        print(f"Skipping large image {filename}: {image_size_mb:.1f}MB\
                                              (exceeds 15MB limit)")
                                        continue

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
                                    print(f"Failed to download image {filename}.\
                                          Final status: {response.status_code if response else 'No response'}")
                                    if response:
                                        print(f"Response headers: {dict(response.headers)}")
                                        print(f"Response text: {response.text[:500]}")
                            except Exception as e:
                                print(f"Error downloading image {filename}: {str(e)}")
                else:
                    print("No attachments found in page data")
            else:
                print("No body.storage found in page data")

        except Exception as e:
            print(f"Error processing page: {str(e)}")
            logger.exception(f"Error processing page: {str(e)}")
        finally:
            session.close()

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
        if clean_chunks:
            return [{"page": page_id, "type": "text", "text": clean_chunks[0]}]
        else:
            return []

    def get_child_pages(self, page_id: str, max_depth: int = 1, current_depth: int = 0) -> List[str]:
        """Recursively get all child page IDs for a given page"""
        if current_depth >= max_depth:
            return []

        child_page_ids = []
        headers = self._get_auth_headers()

        try:
            # Get child pages using Confluence REST API
            endpoint = f"{self.confluence_url}/rest/api/content/{page_id}/child/page"
            response = requests.get(endpoint, headers=headers, timeout=30)

            if response.status_code == 200:
                data = response.json()
                children = data.get('results', [])

                logger.info(f"Found {len(children)} child pages for page {page_id}")

                for child in children:
                    child_id = child['id']
                    child_page_ids.append(child_id)
                    logger.info(f"Found child page: {child['title']} (ID: {child_id})")

                    # Recursively get grandchildren
                    grandchildren = self.get_child_pages(child_id, max_depth, current_depth + 1)
                    child_page_ids.extend(grandchildren)
            else:
                logger.warning(f"Failed to get child pages for {page_id}: {response.status_code}")

        except Exception as e:
            logger.error(f"Error getting child pages for {page_id}: {str(e)}")

        return child_page_ids

    def extract_data(self) -> Tuple[List[str], List[str], List[str]]:
        """Extract all content from Confluence pages"""
        # Get all page IDs (parent + children)
        all_page_ids = [self.page_id]

        # Get child pages recursively
        logger.info(f"Getting child pages for parent page: {self.page_id}")
        child_page_ids = self.get_child_pages(self.page_id)
        all_page_ids.extend(child_page_ids)

        logger.info(f"Total pages to process: {len(all_page_ids)} (1 parent + {len(child_page_ids)} children)")

        # Load all pages using ConfluenceLoader
        documents = self.loader.load(page_ids=all_page_ids)

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
        if all_images:
            logger.info(f"First image info: {all_images[0] if all_images else 'None'}")
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
    # print("*****************************TEXTS EXTRACTED FROM PAGE ARE*******************************")
    # print(texts)
    # print("*****************************TEXTS EXTRACTED FROM PAGE ARE*******************************")
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
        processed_texts.append({"element": text_dict["text"]})

    # Generate summaries only for non-empty data
    table_summaries = []
    text_summaries = []
    image_summaries = []

    if tables:
        logger.info("Starting table summarization")
        table_summaries = text_table_chain.batch(tables, {"max_concurrency": 3})
    else:
        logger.info("No tables found to summarize")

    if processed_texts:
        logger.info("Starting text summarization")
        text_summaries = text_table_chain.batch(
            processed_texts, {"max_concurrency": 3})
    else:
        logger.info("No text content found to summarize")

    if images:
        logger.info("Starting image summarization")
        image_summaries = image_chain.batch(images, {"max_concurrency": 3})
        for img_summary in image_summaries:
            print(f"image summary is: {img_summary}")
    else:
        logger.info("No images found to summarize")

    # Store in vector store and document store
    vectorstore = get_vector_store()
    store = get_document_store()

    retriever = MultiVectorRetriever(
        vectorstore=vectorstore,
        docstore=store,
        id_key="doc_id",
    )

    # Store texts only if they exist
    if texts and text_summaries:
        logger.info(f"Storing {len(texts)} text documents in vector store")
        doc_ids = [str(uuid.uuid4()) for _ in texts]
        summary_texts = [
            Document(page_content=summary, metadata={"doc_id": doc_ids[i]})
            for i, summary in enumerate(text_summaries)
        ]
        print("")
        retriever.vectorstore.add_documents(summary_texts)
        retriever.docstore.mset(list(zip(doc_ids, texts)))
    else:
        logger.info("No text content to store")

    # Store tables only if they exist
    if tables and table_summaries:
        logger.info(f"Storing {len(tables)} table documents in vector store")
        table_ids = [str(uuid.uuid4()) for _ in tables]
        summary_tables = [
            Document(page_content=summary, metadata={"doc_id": table_ids[i]})
            for i, summary in enumerate(table_summaries)
        ]
        retriever.vectorstore.add_documents(summary_tables)
        retriever.docstore.mset(list(zip(table_ids, tables)))
    else:
        logger.info("No table content to store")

    # Store images only if they exist
    if images and image_summaries:
        logger.info(f"Storing {len(images)} image documents in vector store")
        img_ids = [str(uuid.uuid4()) for _ in images]
        summary_img = [
            Document(page_content=summary, metadata={"doc_id": img_ids[i]})
            for i, summary in enumerate(image_summaries)
        ]
        retriever.vectorstore.add_documents(summary_img)
        # Convert base64 strings to proper document format for MongoDB
        image_docs = [{"base64_data": img} for img in images]
        retriever.docstore.mset(list(zip(img_ids, image_docs)))
    else:
        logger.info("No image content to store")

    logger.info("Data storage completed successfully")


if __name__ == "__main__":
    # Load these from environment variables in production
    CONFLUENCE_URL = "https://confluence.com"
    API_KEY = ""
    SPACE_KEY = None
    PAGE_ID = ""
    USERNAME = ""

    load_confluence_content(
        confluence_url=CONFLUENCE_URL,
        username=USERNAME,
        api_key=API_KEY,
        space_key=SPACE_KEY,
        page_id=PAGE_ID
    )
