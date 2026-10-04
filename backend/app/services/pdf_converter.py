from pathlib import Path

import pdfplumber

from app.core.logging import logger


def convert_pdf(pdf_path: Path) -> tuple[Path, str]:
    """Extract text from a PDF and save it as a .txt file next to it.

    Returns (txt_path, text_content).
    """
    pages_text: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            pages_text.append(page.extract_text() or "")

    text_content = "\n\n".join(pages_text).strip()

    txt_path = pdf_path.with_suffix(".txt")
    txt_path.write_text(text_content, encoding="utf-8")
    logger.info("pdf_converted pdf=%s txt=%s chars=%s", pdf_path, txt_path, len(text_content))
    return txt_path, text_content
