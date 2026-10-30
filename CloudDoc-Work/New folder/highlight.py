"""Highlight the evidence of a retrieved chunk on its PDF page.

The original file is never modified: a copy is produced in memory with highlight annotations,
which any PDF viewer (including the browser's built-in one) draws on top of the text.

* Text-layer pages: every line of the chunk is located with PyMuPDF's text search.
* Image-only pages (read by OCR): the page is OCR'd again for word boxes, and the chunk's words are
  matched against them.
"""
from __future__ import annotations

import difflib
import io
import re
from typing import Any

import pymupdf

from config import OCR_DPI, OCR_LANG
from ocr import find_tesseract, is_ocr_available

HIGHLIGHT_COLOR = (1.0, 0.85, 0.1)
HIGHLIGHT_OPACITY = 0.45
MIN_LINE_CHARS = 8
LONG_LINE_CHARS = 25
BAND_MARGIN = 60  # points: short lines only count when they sit near the long lines


def _chunk_lines(chunk: dict[str, Any]) -> list[str]:
    body = chunk.get("body")
    if not body:  # chunks stored by an older version: drop the "Document: … | Section: …" prefix line
        text = chunk.get("text", "")
        body = text.split("\n", 1)[1] if text.startswith("Document:") and "\n" in text else text
    lines = []
    for raw in str(body).split("\n"):
        line = re.sub(r"^[\s•●▪◦‣·\-–—*]+", "", raw)
        line = " ".join(line.split())
        if len(line) >= MIN_LINE_CHARS or len(line.split()) >= 2:
            lines.append(line)
    return lines


def _quad_rect(quad: pymupdf.Quad) -> pymupdf.Rect:
    return quad.rect


def _text_layer_quads(page: pymupdf.Page, lines: list[str]) -> list[pymupdf.Quad]:
    long_hits: list[pymupdf.Quad] = []
    short_lines: list[str] = []
    for line in lines:
        if len(line) >= LONG_LINE_CHARS:
            long_hits.extend(page.search_for(line, quads=True))
        else:
            short_lines.append(line)

    quads = list(long_hits)
    if long_hits:
        top = min(_quad_rect(q).y0 for q in long_hits) - BAND_MARGIN
        bottom = max(_quad_rect(q).y1 for q in long_hits) + BAND_MARGIN
    else:
        top, bottom = float("-inf"), float("inf")

    for line in short_lines:
        for quad in page.search_for(line, quads=True):
            rect = _quad_rect(quad)
            if top <= rect.y0 and rect.y1 <= bottom:
                quads.append(quad)
    return quads


def _norm(token: str) -> str:
    return re.sub(r"\W+", "", token.lower())


def _ocr_quads(page: pymupdf.Page, lines: list[str]) -> list[pymupdf.Quad]:
    """Word boxes from a fresh OCR pass, matched against the chunk's words."""
    if not is_ocr_available():
        return []
    import pytesseract  # type: ignore
    from PIL import Image

    pytesseract.pytesseract.tesseract_cmd = find_tesseract() or "tesseract"
    pix = page.get_pixmap(dpi=OCR_DPI)
    image = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
    data = pytesseract.image_to_data(image, lang=OCR_LANG, output_type=pytesseract.Output.DICT)

    words = []
    for i, text in enumerate(data["text"]):
        token = _norm(text)
        if token:
            words.append({
                "token": token,
                "box": (data["left"][i], data["top"][i], data["width"][i], data["height"][i]),
                "line": (data["block_num"][i], data["par_num"][i], data["line_num"][i]),
            })
    wanted = [t for t in (_norm(w) for line in lines for w in line.split()) if t]
    if not words or not wanted:
        return []

    matcher = difflib.SequenceMatcher(None, [w["token"] for w in words], wanted, autojunk=False)
    picked: list[dict] = []
    for block in matcher.get_matching_blocks():
        if block.size >= 3:
            picked.extend(words[block.a : block.a + block.size])

    by_line: dict[tuple, list[dict]] = {}
    for word in picked:
        by_line.setdefault(word["line"], []).append(word)

    scale = 72.0 / OCR_DPI
    quads = []
    for group in by_line.values():
        x0 = min(w["box"][0] for w in group)
        y0 = min(w["box"][1] for w in group)
        x1 = max(w["box"][0] + w["box"][2] for w in group)
        y1 = max(w["box"][1] + w["box"][3] for w in group)
        quads.append(pymupdf.Rect(x0 * scale, y0 * scale, x1 * scale, y1 * scale).quad)
    return quads


def highlight_chunk(pdf_bytes: bytes, chunk: dict[str, Any]) -> tuple[bytes, int]:
    """Return (pdf with the chunk's evidence highlighted, number of highlighted spans).

    If nothing could be located the original bytes are returned unchanged with a count of 0.
    """
    page_number = int(chunk.get("page", 1))
    lines = _chunk_lines(chunk)
    if not lines:
        return pdf_bytes, 0

    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        if not 1 <= page_number <= doc.page_count:
            return pdf_bytes, 0
        page = doc[page_number - 1]
        if page.rotation:
            return pdf_bytes, 0  # rotated pages are left as they are

        quads = _text_layer_quads(page, lines)
        if not quads and len(page.get_text("text").strip()) < 50:
            quads = _ocr_quads(page, lines)
        if not quads:
            return pdf_bytes, 0

        annot = page.add_highlight_annot(quads=quads)
        annot.set_colors(stroke=HIGHLIGHT_COLOR)
        annot.set_opacity(HIGHLIGHT_OPACITY)
        annot.set_info(title="CloudDoc AI", content="Evidence")
        annot.update()
        return doc.tobytes(deflate=True), len(quads)
