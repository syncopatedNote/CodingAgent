import tabula
from typing import Optional
import pandas as pd
from logger import setup_logger
import pymupdf
from tqdm import tqdm
import base64
from IPython.display import Image, display
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = setup_logger(__name__)

_TEXT_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=1500,
    chunk_overlap=300,
    separators=["\n\n", "\n", ". ", " ", ""],
    length_function=len,
)


def split_text(text: str) -> list[str]:
    """Split text into chunks using the shared text splitter configuration."""
    return _TEXT_SPLITTER.split_text(text)


def extract_tables_from_pdf(
    file_path: str,
    guess: bool = True,
    lattice: bool = True,
    stream: bool = True,
) -> list[dict]:
    """Extract tables from a PDF, returning each table with its 0-indexed page number.

    Returns a list of dicts: {"page": int, "table": pd.DataFrame}
    Page numbers are 0-indexed to match the convention used by extract_text_from_pdf.
    """
    doc = pymupdf.open(file_path)
    num_pages = len(doc)
    result = []

    logger.info(f"Extracting tables from PDF: {file_path} ({num_pages} pages)")

    for page_num in range(1, num_pages + 1):  # tabula uses 1-indexed pages
        try:
            page_tables = tabula.read_pdf(
                file_path,
                pages=str(page_num),
                guess=guess,
                lattice=lattice,
                stream=stream,
                multiple_tables=True,
            )
            for table in page_tables:
                if not table.empty:
                    result.append({"page": page_num - 1, "table": table})
        except Exception as e:
            logger.warning(f"Table extraction failed on page {page_num}: {e}")
            continue

    logger.info(f"Successfully extracted {len(result)} tables")
    return result


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


def extract_text_from_pdf(filepath: str = None, pages: Optional[str] = "all") -> list:
    """Extract text from each PDF page, including form field values.

    page.get_text() only reads the content stream and silently skips AcroForm
    widget annotations (text inputs, checkboxes). We collect those separately
    via page.widgets() and merge both sources by visual position so the
    reconstructed text reads in natural top-to-bottom, left-to-right order.
    """
    doc = pymupdf.open(filepath)
    num_pages = len(doc)
    result = []
    LINE_TOL = 5  # points — spans within this vertical distance share a line

    for page_num in tqdm(range(num_pages), desc="Processing PDF pages"):
        page = doc[page_num]
        items = []  # (y0, x0, text)

        # Regular text spans with exact bounding boxes
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:  # skip image blocks
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = span["text"].strip()
                    if t:
                        bbox = span["bbox"]
                        items.append((bbox[1], bbox[0], t))

        # Form field values (AcroForm widgets — invisible to get_text)
        for widget in page.widgets() or []:
            val = widget.field_value
            if val is not None and str(val).strip():
                r = widget.rect
                items.append((r.y0, r.x0, str(val).strip()))

        # Sort by bucketed y (line grouping) then x (left-to-right)
        items.sort(key=lambda it: (round(it[0] / LINE_TOL) * LINE_TOL, it[1]))

        # Group into visual lines and reconstruct as plain text
        lines = []
        cur_y = None
        cur_parts = []
        for y, _x, t in items:
            bucketed = round(y / LINE_TOL) * LINE_TOL
            if cur_y is None or abs(bucketed - cur_y) > LINE_TOL:
                if cur_parts:
                    lines.append(" ".join(cur_parts))
                cur_y = bucketed
                cur_parts = [t]
            else:
                cur_parts.append(t)
        if cur_parts:
            lines.append(" ".join(cur_parts))

        page_text = "\n".join(lines)
        if page_text.strip():
            for chunk in _TEXT_SPLITTER.split_text(page_text):
                result.append({"page": page_num, "type": "text", "text": chunk})

    return result
