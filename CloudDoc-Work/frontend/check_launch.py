#!/usr/bin/env python3
"""Pre-launch check for the CloudDoc AI frontend.

Run from the project folder:   python check_launch.py
Exit code 0 means every check passed. Exit code 1 means something must be fixed.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAGES = ["index.html", "privacy.html", "terms.html"]
CODE = ["index.html", "privacy.html", "terms.html", "app.js", "styles.css", "legal.css"]
REQUIRED = PAGES + ["app.js", "styles.css", "legal.css",
                    "favicon.svg", "favicon.ico", "apple-touch-icon.png"]

EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B50\u2B06\u2728\u2B05\u27A1\u2190-\u21FF\u2300-\u23FF]")
DASH = re.compile("[\u2013\u2014]")
URL = re.compile(r"https?://[^\s\"')<>]+")
ALLOWED_URL = re.compile(r"^https?://(127\.0\.0\.1|localhost)(:\d+)?|^http://www\.w3\.org/")
BADGE = re.compile(r"(?i)\b(made with|built with|powered by|generated (?:by|with)|created with)\b")

problems, notes = [], []


def read(name):
    return (ROOT / name).read_text(encoding="utf8")


def fail(msg):
    problems.append(msg)


for name in REQUIRED:
    if not (ROOT / name).exists():
        fail(f"Missing file: {name}")

for name in CODE + ["README.md"]:
    if not (ROOT / name).exists():
        continue
    text = read(name)
    lines = text.split("\n")
    for n, line in enumerate(lines, 1):
        if DASH.search(line):
            fail(f"{name}:{n} has an em or en dash")
        if EMOJI.search(line):
            fail(f"{name}:{n} has an emoji or symbol character")
    if name == "README.md":
        continue
    if re.search(r"gradient", text, re.I):
        fail(f"{name} uses a gradient")
    for m in URL.finditer(text):
        if not ALLOWED_URL.match(m.group(0)):
            fail(f"{name} references an outside address: {m.group(0)}")
    if name.endswith((".html", ".js")):
        for n, line in enumerate(lines, 1):
            if BADGE.search(line):
                fail(f"{name}:{n} has builder or AI badge wording: {line.strip()[:80]}")
    if name.endswith(".css"):
        for n, line in enumerate(lines, 1):
            if re.search(r"border-radius:\s*(9999|999)\d*px|radius-full", line):
                fail(f"{name}:{n} uses a pill radius")
    if name == "app.js":
        for pat in ("mousemove", "pointermove", "IntersectionObserver", "countUp"):
            if pat in text:
                fail(f"app.js uses {pat} (cursor, scroll or counter effect)")
    for m in re.finditer(r"\[\[(.+?)\]\]", text):
        fail(f"{name} still has a placeholder to fill: [[{m.group(1)[:60]}]]")

if (ROOT / "index.html").exists():
    index = read("index.html")
    for needle, label in (('href="privacy.html"', "privacy link"),
                          ('href="terms.html"', "terms link"),
                          ('rel="icon"', "favicon link")):
        if needle not in index:
            fail(f"index.html has no {label}")
    if "<title>" not in index:
        fail("index.html has no title")

for name in PAGES:
    if (ROOT / name).exists() and 'rel="icon"' not in read(name):
        fail(f"{name} has no favicon link")

if (ROOT / "styles.css").exists():
    frames = re.findall(r"@keyframes\s+([\w-]+)", read("styles.css"))
    notes.append("Animations defined: " + (", ".join(frames) if frames else "none"))

print("CloudDoc AI pre-launch check")
print("-" * 30)
for note in notes:
    print("note:", note)
if problems:
    print(f"\n{len(problems)} problem(s) to fix before launch:\n")
    for p in problems:
        print(" -", p)
    sys.exit(1)
print("\nAll checks passed.")
