"""PDF text extraction: reading-order aware, with automatic per-page OCR."""
from __future__ import annotations

from dataclasses import dataclass, field

import pymupdf

from config import MAX_PAGES, OCR_MIN_PAGE_CHARS
from ocr import is_ocr_available, ocr_page


class ExtractionError(Exception):
    """Raised for unreadable PDFs; carries the HTTP status the API should return."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class PageRecord:
    page: int
    text: str
    native_chars: int
    chars: int
    ocr: bool = False
    note: str = ""


@dataclass
class ExtractionResult:
    records: list[PageRecord] = field(default_factory=list)

    @property
    def pages(self) -> list[str]:
        return [r.text for r in self.records]

    @property
    def ocr_pages(self) -> list[int]:
        return [r.page for r in self.records if r.ocr]

    def page_dicts(self) -> list[dict]:
        return [
            {"page": r.page, "text": r.text, "native_chars": r.native_chars,
             "chars": r.chars, "ocr": r.ocr, "note": r.note}
            for r in self.records
        ]


# --------------------------------------------------------------------------- reading order
def _reading_order(blocks: list[tuple], page_width: float) -> list[tuple]:
    """Order text blocks so multi-column layouts read column by column.

    Looks for a vertical gutter crossed by few blocks with at least two blocks on
    each side that sit side by side. Blocks crossing the gutter (titles, headers)
    act as separators. Single-column pages simply read top to bottom.
    """
    def y_then_x(b):
        return (round(b[1], 1), b[0])

    if len(blocks) < 4:
        return sorted(blocks, key=y_then_x)

    n = len(blocks)
    best_x, best_cost = None, None
    lo, hi = int(page_width * 0.2), int(page_width * 0.8)
    xs = []
    for x in range(lo, hi + 1, 3):
        crossing = sum(1 for b in blocks if b[0] < x < b[2])
        left = sum(1 for b in blocks if b[2] <= x)
        right = sum(1 for b in blocks if b[0] >= x)
        if left >= 2 and right >= 2 and crossing <= max(1, int(0.25 * n)):
            xs.append((crossing, x))
    if xs:
        best_cost = min(c for c, _ in xs)
        tied = [x for c, x in xs if c == best_cost]
        best_x = tied[len(tied) // 2]

    if best_x is None:
        return sorted(blocks, key=y_then_x)

    left = [b for b in blocks if b[2] <= best_x]
    right = [b for b in blocks if b[0] >= best_x]
    spanning = [b for b in blocks if b[0] < best_x < b[2]]

    def y_range(group):
        return min(b[1] for b in group), max(b[3] for b in group)

    (l0, l1), (r0, r1) = y_range(left), y_range(right)
    overlap = min(l1, r1) - max(l0, r0)
    if overlap < 0.4 * min(l1 - l0, r1 - r0):
        return sorted(blocks, key=y_then_x)  # not truly side by side

    left.sort(key=y_then_x)
    right.sort(key=y_then_x)
    spanning.sort(key=y_then_x)

    ordered: list[tuple] = []
    for sep in spanning:
        while left and left[0][3] <= sep[1] + 1:
            ordered.append(left.pop(0))
        while right and right[0][3] <= sep[1] + 1:
            ordered.append(right.pop(0))
        ordered.append(sep)
    ordered.extend(left)
    ordered.extend(right)
    return ordered


def ordered_page_text(page) -> str:
    """Extract page text in reading order (column aware)."""
    blocks = [
        b for b in page.get_text("blocks")
        if len(b) >= 7 and b[6] == 0 and str(b[4]).strip()
    ]
    if not blocks:
        return ""
    ordered = _reading_order(blocks, float(page.rect.width))
    return "\n".join(str(b[4]).strip("\n") for b in ordered).strip()


# --------------------------------------------------------------------------- main entry
def extract_pdf(data: bytes) -> ExtractionResult:
    """Extract per-page text; pages with fewer than OCR_MIN_PAGE_CHARS characters are OCR'd."""
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise ExtractionError(400, "File is not a valid PDF.") from None

    with doc:
        if doc.needs_pass or doc.is_encrypted:
            raise ExtractionError(400, "Password-protected PDFs are not supported.")
        if doc.page_count == 0:
            raise ExtractionError(400, "PDF has no pages.")
        if doc.page_count > MAX_PAGES:
            raise ExtractionError(413, f"PDF has too many pages (max {MAX_PAGES}).")

        ocr_ready = is_ocr_available()
        result = ExtractionResult()
        low_text_pages: list[int] = []
        ocr_errors: list[str] = []

        for number, page in enumerate(doc, start=1):
            try:
                native = ordered_page_text(page)
            except Exception:
                raise ExtractionError(400, "Could not read text from this PDF.") from None

            native_chars = len(native.strip())
            record = PageRecord(page=number, text=native, native_chars=native_chars, chars=native_chars)

            if native_chars < OCR_MIN_PAGE_CHARS:
                low_text_pages.append(number)
                if ocr_ready:
                    try:
                        ocr_text = ocr_page(page).strip()
                    except Exception as exc:  # keep going; report at the end
                        ocr_errors.append(f"page {number}: {exc}")
                        record.note = "ocr_failed"
                    else:
                        if len(ocr_text) > native_chars:
                            record.text = ocr_text
                            record.chars = len(ocr_text)
                            record.ocr = True
                            record.note = "ocr"
                        else:
                            record.note = "ocr_found_nothing"
                else:
                    record.note = "low_text_no_ocr"
            result.records.append(record)

        if not any(r.chars for r in result.records):
            if ocr_errors:
                raise ExtractionError(
                    422, f"No extractable text found. OCR processing failed: {ocr_errors[0]}")
            has_images = any(page.get_images() for page in doc)
            if has_images and not ocr_ready:
                raise ExtractionError(
                    422,
                    "No extractable text found. Scanned PDF detected, "
                    "and local OCR engine (Tesseract) is not installed.",
                )
            raise ExtractionError(422, "No extractable text found in this PDF.")

        return result
