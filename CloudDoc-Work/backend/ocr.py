"""OCR capability detection and local Tesseract integration (no cloud, no telemetry)."""
from __future__ import annotations

import io
import os
import shutil
from typing import Optional

from config import OCR_DPI, OCR_LANG, TESSERACT_CMD

_WINDOWS_DEFAULTS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


def find_tesseract() -> Optional[str]:
    """Locate the tesseract binary: explicit env var, PATH, then common Windows paths."""
    explicit = os.getenv("CLOUDDOC_TESSERACT_CMD", TESSERACT_CMD).strip()
    if explicit and os.path.isfile(explicit):
        return explicit
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    for candidate in _WINDOWS_DEFAULTS:
        if os.path.isfile(candidate):
            return candidate
    return None


def is_ocr_available() -> bool:
    """True only if pytesseract imports AND the tesseract binary actually runs."""
    cmd = find_tesseract()
    if not cmd:
        return False
    try:
        import pytesseract  # type: ignore

        pytesseract.pytesseract.tesseract_cmd = cmd
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def ocr_status_detail() -> str:
    cmd = find_tesseract()
    if not cmd:
        return "Tesseract binary not found (install it or set CLOUDDOC_TESSERACT_CMD)."
    try:
        import pytesseract  # type: ignore  # noqa: F401
    except Exception:
        return "Python package 'pytesseract' (and Pillow) is not installed."
    return "ready" if is_ocr_available() else "Tesseract found but could not be executed."


def ocr_page(page) -> str:
    """OCR a single PyMuPDF page; raises RuntimeError when OCR cannot run."""
    if not is_ocr_available():
        raise RuntimeError("Tesseract OCR is not installed or configured on the system.")

    import pytesseract  # type: ignore
    from PIL import Image

    pix = page.get_pixmap(dpi=OCR_DPI)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
    return pytesseract.image_to_string(img, lang=OCR_LANG)


def detect_scanned_pdf(doc) -> bool:
    """True if the document has images but (almost) no extractable text."""
    total_text_len = 0
    total_images = 0
    for page in doc:
        total_text_len += len(page.get_text("text").strip())
        total_images += len(page.get_images())
    return total_text_len < 30 and total_images > 0


def perform_ocr_on_doc(doc) -> list[str]:
    """OCR every page of a document (kept for backwards compatibility)."""
    return [ocr_page(page) for page in doc]
