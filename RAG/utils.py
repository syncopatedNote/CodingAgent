import tabula
from typing import Optional
import pandas as pd
from logger import setup_logger
import pymupdf
from tqdm import tqdm
import base64
from IPython.display import Image, display

# from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = setup_logger(__name__)


def extract_tables_from_pdf(
    file_path: str,
    pages: Optional[str] = "all",
    output_format: str = None,
    guess: bool = True,
    lattice: bool = True,
    stream: bool = True,
) -> pd.DataFrame:
    """
    Extract tables from the PDF file.

    Args:
        pages (str, optional): Pages to extract tables from. Defaults to 'all'.
                                Can be 'all' or a specific page number like '1' or
                                a range like '1-3'.
        guess (bool): Whether to guess the table structure. Defaults to True.
        lattice (bool): Whether to use lattice mode for table extraction.
                        Defaults to True.
        stream (bool): Whether to use stream mode for table extraction.
                        Defaults to True.

    Returns:
        List[pd.DataFrame]: List of extracted tables as pandas DataFrames
    """
    try:
        logger.info(f"Extracting tables from PDF: {file_path}")

        tables = tabula.read_pdf(
            file_path,
            pages=pages,
            guess=guess,
            output_format=output_format,
            lattice=lattice,
            stream=stream,
            multiple_tables=True,
        )

        logger.info(f"Successfully extracted {len(tables)} tables")
        return tables

    except Exception as e:
        logger.error(f"Error extracting tables from PDF: {str(e)}")
        raise


def extract_images_from_pdf(filepath: str = None) -> list:
    images = []
    doc = pymupdf.open(filepath)
    num_pages = len(doc)
    for page_num in tqdm(range(num_pages), desc="Processing PDF pages"):
        page = doc[page_num]
        b64_images = process_images(doc, page)
        images.extend(b64_images)
    return images


def process_images(doc, page) -> list:
    data = []
    images = page.get_images()
    for _, image in enumerate(images):
        xref = image[0]
        pix = pymupdf.Pixmap(doc, xref)
        # Convert to PNG bytes in memory
        png_bytes = pix.tobytes("png")
        # Convert bytes to base64 string
        encoded_image = base64.b64encode(png_bytes).decode("utf-8")
        data.append(encoded_image)
    return data


def display_base64_image(base64_code):
    # Decode the base64 string to binary
    image_data = base64.b64decode(base64_code)
    # Display the image
    display(Image(data=image_data))


# def process_text_chunks(text, text_splitter, page_num, items):
#     chunks = text_splitter.split_text(text)
#     for _, chunk in enumerate(chunks):
#         items.append({"page": page_num, "type": "text", "text": chunk})


# def extract_text_from_pdf(
#         filepath: str = None,
#         pages: Optional[str] = 'all'
# ) -> list:
#     doc = pymupdf.open(filepath)
#     num_pages = len(doc)
#     text_splitter = RecursiveCharacterTextSplitter(
#         chunk_size=700, chunk_overlap=200, length_function=len
#     )
#     extracted_text_chunks = []
#     for page_num in tqdm(range(num_pages), desc="Processing PDF pages"):
#         page = doc[page_num]
#         text = page.get_text()
#         chunks = text_splitter.split_text(text)
#         for _, chunk in enumerate(chunks):
#             extracted_text_chunks.append({"page": page_num, "type": "text", "text": chunk})

#     return extracted_text_chunks


def extract_text_from_pdf(filepath: str = None, pages: Optional[str] = "all") -> list:
    doc = pymupdf.open(filepath)
    num_pages = len(doc)
    text = []
    for page_num in tqdm(range(num_pages), desc="Processing PDF pages"):
        page = doc[page_num]
        text.append({"page": page_num, "type": "text", "text": page.get_text()})
    return text
