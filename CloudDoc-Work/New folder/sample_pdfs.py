"""Builders for small sample resume PDFs used by the tests (and handy for manual checks)."""
from __future__ import annotations

import io

import pymupdf

RESUME_LINES = [
    "AARAV MEHTA",
    "Email: aarav.mehta@example.com | Phone: +91 98765 43210",
    "LinkedIn: linkedin.com/in/aaravmehta | GitHub: github.com/aaravmehta",
    "",
    "SUMMARY",
    "Final year computer science student interested in cloud infrastructure and backend systems.",
    "",
    "EDUCATION",
    "B.Tech in Computer Science and Engineering",
    "Sapphire University of Technology, Bengaluru",
    "2022 - 2026 | CGPA: 8.7 / 10",
    "Higher Secondary: Greenfield Public School, 2022, 93 percent",
    "",
    "EXPERIENCE",
    "Cloud Engineering Intern - Orion Cloud Labs",
    "May 2025 - July 2025",
    "Automated deployments with Terraform and reduced release time by 40 percent.",
    "",
    "SKILLS",
    "Python, Java, SQL, Docker, Kubernetes, Terraform, AWS, Git",
    "",
    "PROJECTS",
    "College Event Portal - a campus event management web app built with Flask and PostgreSQL.",
    "Smart Parking Tracker - IoT based parking availability dashboard.",
    "",
    "CERTIFICATIONS",
    "AWS Certified Cloud Practitioner, 2025",
]

# Facts the tests look for, keyed by question intent.
EXPECTED = {
    "college": "Sapphire University of Technology",
    "university": "Sapphire University of Technology",
    "degree": "B.Tech in Computer Science",
    "skills": "Python, Java, SQL",
    "intern": "Orion Cloud Labs",
    "email": "aarav.mehta@example.com",
}


def make_text_resume(lines: list[str] | None = None) -> bytes:
    """A normal text-based, single-column resume PDF."""
    doc = pymupdf.open()
    page = doc.new_page()
    y = 60
    for line in lines or RESUME_LINES:
        if line:
            page.insert_text((50, y), line, fontsize=11)
        y += 17
    data = doc.tobytes()
    doc.close()
    return data


def make_two_column_resume() -> bytes:
    """Sidebar-style layout: skills + contact on the left, education + experience on the right."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(40, 30, 555, 80), "ISHA RAO", fontsize=18)
    left = [
        (60, "CONTACT\nisha.rao@example.com\n+91 91234 56789"),
        (160, "SKILLS\nGo, Rust, Linux,\nPostgreSQL"),
        (260, "LANGUAGES\nEnglish, Hindi"),
    ]
    right = [
        (90, "EDUCATION\nM.Tech in Data Science\nRiverbend Institute of Technology\n2021 - 2023"),
        (230, "EXPERIENCE\nData Engineer at Lumen Analytics\n2023 - 2025 building ETL pipelines"),
        (360, "PROJECTS\nFraud Detection Pipeline using Spark"),
    ]
    for y, text in left:
        page.insert_textbox(pymupdf.Rect(40, y + 20, 230, y + 120), text, fontsize=11)
    for y, text in right:
        page.insert_textbox(pymupdf.Rect(300, y, 555, y + 120), text, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def make_image_resume(lines: list[str] | None = None) -> bytes:
    """An image-only PDF (like a scanned / Canva export): no text layer at all."""
    from PIL import Image, ImageDraw, ImageFont

    width, height = 1500, 1500
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=34)
    y = 60
    for line in lines or RESUME_LINES:
        if line:
            draw.text((70, y), line, fill="black", font=font)
        y += 50
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=595)
    page.insert_image(page.rect, stream=buf.getvalue())
    data = doc.tobytes(deflate=True)
    doc.close()
    return data


def make_pdf(pages: list[str]) -> bytes:
    """Simple multi-page text PDF (one textbox per page)."""
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(72, 72, 523, 770), text, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data
