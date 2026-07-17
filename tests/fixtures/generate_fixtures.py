"""
[MODULE]   tests/fixtures/generate_fixtures.py
[TASK]     T5.1 — Test suite completion
[SUBTASKS] T5.1.1 assemble 7 synthetic test fixtures — no real patient data
[SUMMARY]  One-shot generator for the 7 binary fixtures IMPLEMENTATION_PLAN.md §2 lists
           under tests/fixtures/: native.pdf, scanned.pdf, printed_report.jpg,
           handwritten.jpg, medicine_box.jpg, password.pdf, blurry.jpg. All document
           content comes from ground_truth.py's LAB_REPORT_LINES/HANDWRITTEN_LINES —
           fabricated names/diagnoses, never real patient data (CLAUDE.md, plan R7).
           native.pdf/scanned.pdf/printed_report.jpg share the same fabricated lab
           report (a real PyMuPDF text layer, a 4-page rasterized/image-only PDF, and
           a standalone printed-style JPEG, respectively); password.pdf is the same
           report AES-256-encrypted (PyMuPDF sets `needs_pass` on open without a
           password); handwritten.jpg renders a shorter prescription note in a cursive
           system font; medicine_box.jpg is a drawn (not photographed) box + blister
           pack; blurry.jpg is printed_report.jpg with a heavy Gaussian blur applied,
           for the "unreadable document" / all-fields-null scenario. Font paths point
           at this Windows dev box's system fonts (T3.2.4-style dev-environment note:
           this script is a local generation tool, not part of the runtime pipeline in
           app/, so it is not expected to run on the Linux deployment target) and fall
           back to PIL's built-in bitmap font if a path is missing, so it still runs
           (with lower visual fidelity) on a machine without those fonts. Deterministic
           — no randomness — so re-running reproduces the committed files byte-for-byte.
           Run once from the project root: `.venv\\Scripts\\python.exe -m
           tests.fixtures.generate_fixtures`.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T5.1.1; §2 (tests/fixtures/ layout)
[HISTORY]  2026-07-17  T5.1.1  initial fixture generator + committed output files
"""

from pathlib import Path

import cv2
import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from tests.fixtures.ground_truth import HANDWRITTEN_LINES, LAB_REPORT_LINES

FIXTURES_DIR = Path(__file__).parent

# [T5.1.1] Local Windows system fonts — see [SUMMARY] re: this being dev-only tooling.
_ARIAL = "C:/Windows/Fonts/arial.ttf"
_ARIAL_BOLD = "C:/Windows/Fonts/arialbd.ttf"
_SEGOE_SCRIPT = "C:/Windows/Fonts/segoesc.ttf"

_PDF_PAGE_SIZE = (595, 842)  # A4 in points, for the fitz-generated PDFs


def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


# [T5.1.1] Renders a list of text lines top-to-bottom onto a blank RGB canvas —
# shared by printed_report.jpg (printed font) and handwritten.jpg (cursive font).
def _render_text_image(
    lines: list[str],
    font_path: str,
    font_size: int,
    size: tuple[int, int],
    bg: tuple[int, int, int] = (255, 255, 255),
    fg: tuple[int, int, int] = (0, 0, 0),
    line_spacing: float = 1.4,
    margin: int = 80,
) -> Image.Image:
    img = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(img)
    font = _load_font(font_path, font_size)
    y = margin
    for line in lines:
        draw.text((margin, y), line, font=font, fill=fg)
        bbox = draw.textbbox((margin, y), line if line else "Ag", font=font)
        line_h = bbox[3] - bbox[1]
        y += int(line_h * line_spacing) + 10
    return img


# [T5.1.1] native.pdf — a real PyMuPDF text layer (T2.1.2's >100-char native-PDF path).
def make_native_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=_PDF_PAGE_SIZE[0], height=_PDF_PAGE_SIZE[1])
    page.insert_text((72, 100), LAB_REPORT_LINES, fontsize=12, fontname="helv")
    doc.save(str(path))
    doc.close()


# [T5.1.1] password.pdf — same report, AES-256 encrypted (T2.1.1's password-protected path).
def make_password_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=_PDF_PAGE_SIZE[0], height=_PDF_PAGE_SIZE[1])
    page.insert_text((72, 100), LAB_REPORT_LINES, fontsize=12, fontname="helv")
    doc.save(
        str(path),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="synthetic-owner-pw",
        user_pw="synthetic-user-pw",
        permissions=fitz.PDF_PERM_PRINT,
    )
    doc.close()


# [T5.1.1] printed_report.jpg — standalone printed-style image (Branch A candidate).
def make_printed_report_jpg(path: Path) -> Image.Image:
    img = _render_text_image(LAB_REPORT_LINES, _ARIAL, 32, size=(1000, 1400))
    img.save(str(path), "JPEG", quality=92)
    return img


# [T5.1.1] handwritten.jpg — cursive-font prescription note (Branch B candidate).
def make_handwritten_jpg(path: Path) -> None:
    img = _render_text_image(
        HANDWRITTEN_LINES, _SEGOE_SCRIPT, 40, size=(1100, 1400),
        bg=(250, 248, 238), fg=(20, 20, 90),
    )
    img.save(str(path), "JPEG", quality=90)


# [T5.1.1] medicine_box.jpg — drawn box + blister pack (Branch B candidate).
def make_medicine_box_jpg(path: Path) -> None:
    img = Image.new("RGB", (900, 700), (235, 235, 235))
    draw = ImageDraw.Draw(img)
    draw.rectangle([60, 60, 840, 640], fill=(30, 90, 160), outline=(10, 40, 90), width=6)
    draw.text((100, 100), "ParaCure", font=_load_font(_ARIAL_BOLD, 48), fill=(255, 255, 255))
    sub_font = _load_font(_ARIAL, 32)
    draw.text((100, 175), "PARACETAMOL 500mg Tablets", font=sub_font, fill=(255, 255, 255))
    draw.text((100, 225), "10 x 10 Tablets", font=sub_font, fill=(230, 230, 230))
    draw.rectangle([100, 320, 800, 560], fill=(210, 210, 215), outline=(120, 120, 120), width=3)
    for row in range(2):
        for col in range(8):
            cx, cy = 140 + col * 85, 380 + row * 120
            draw.ellipse(
                [cx - 30, cy - 30, cx + 30, cy + 30],
                fill=(245, 245, 250), outline=(140, 140, 150), width=2,
            )
    img.save(str(path), "JPEG", quality=92)


# [T5.1.1] blurry.jpg — printed_report.jpg heavily blurred (T4.1.5's all-fields-null /
# unreadable-document scenario).
def make_blurry_jpg(path: Path, source_img: Image.Image) -> None:
    arr = cv2.cvtColor(np.array(source_img), cv2.COLOR_RGB2BGR)
    blurred = cv2.GaussianBlur(arr, (45, 45), 20)
    cv2.imwrite(str(path), blurred, [cv2.IMWRITE_JPEG_QUALITY, 85])


# [T5.1.1] scanned.pdf — 4 image-only pages (no text layer), same lab-report image
# repeated per page, so extract_native_text() falls through to the scanned/pdf2image
# branch (T2.1.3) and MAX_PDF_PAGES_CONVERT=5/MAX_PDF_PAGES_OCR=3 truncation has a
# real (non-mocked) 4-page fixture to exercise.
def make_scanned_pdf(path: Path, page_image: Image.Image, num_pages: int = 4) -> None:
    doc = fitz.open()
    # JPEG (not PNG) keeps the fixture small — a mostly-white scanned page compresses
    # far better than the same content saved as a lossless PNG (~4 MB vs ~150 KB here).
    tmp_jpg = FIXTURES_DIR / "_scanned_page_tmp.jpg"
    page_image.save(str(tmp_jpg), "JPEG", quality=85)
    try:
        for _ in range(num_pages):
            page = doc.new_page(width=_PDF_PAGE_SIZE[0], height=_PDF_PAGE_SIZE[1])
            page.insert_image(fitz.Rect(0, 0, *_PDF_PAGE_SIZE), filename=str(tmp_jpg))
        doc.save(str(path))
    finally:
        doc.close()
        tmp_jpg.unlink()


def main() -> None:
    make_native_pdf(FIXTURES_DIR / "native.pdf")
    make_password_pdf(FIXTURES_DIR / "password.pdf")
    printed_img = make_printed_report_jpg(FIXTURES_DIR / "printed_report.jpg")
    make_handwritten_jpg(FIXTURES_DIR / "handwritten.jpg")
    make_medicine_box_jpg(FIXTURES_DIR / "medicine_box.jpg")
    make_blurry_jpg(FIXTURES_DIR / "blurry.jpg", printed_img)
    make_scanned_pdf(FIXTURES_DIR / "scanned.pdf", printed_img, num_pages=4)
    print(f"Generated 7 fixtures in {FIXTURES_DIR}")


if __name__ == "__main__":
    main()
