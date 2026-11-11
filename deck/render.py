"""Render the slides in this folder to a PDF, one 1920x1080 page per slide.

    python deck/render.py            # writes deck/<name>.pdf

Slides are plain HTML fragments in deck/slides/, ordered by deck/deck.json.
Needs: pip install playwright && playwright install chromium
"""
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
CSS = """
@page { size: 1920px 1080px; margin: 0 }
* { margin: 0; box-sizing: border-box }
html, body { padding: 0 }
section { width: 1920px; height: 1080px; position: relative; overflow: hidden; break-after: page }
aside { display: none }
th, td { padding: 10px 16px; vertical-align: top }
table { border-collapse: collapse }
ul, ol { padding-left: 1.2em }
img { max-width: 100% }
"""


def build_html(extra_css=""):
    deck = json.loads((HERE / "deck.json").read_text())
    links = "".join(f'<link rel="stylesheet" href="{f["href"]}">' for f in deck.get("faces", {}).values())
    slides = "\n".join((HERE / "slides" / f"{s}.html").read_text() for s in deck["order"])
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>{deck["title"]}</title>'
            f"{links}<style>{CSS}{extra_css}</style></head><body>{slides}</body></html>")


def render(extra_css=""):
    from playwright.sync_api import sync_playwright
    deck = json.loads((HERE / "deck.json").read_text())
    out = HERE / (re.sub(r"[^a-z0-9]+", "-", deck["title"].lower()).strip("-") + ".pdf")
    tmp = HERE / "_print.html"
    tmp.write_text(build_html(extra_css))
    try:
        with sync_playwright() as p:
            page = p.chromium.launch().new_page(viewport={"width": 1920, "height": 1080})
            page.goto(tmp.as_uri(), wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.pdf(path=str(out), width="1920px", height="1080px", print_background=True)
    finally:
        tmp.unlink()
    print(out)


if __name__ == "__main__":
    render(sys.argv[1] if len(sys.argv) > 1 else "")
