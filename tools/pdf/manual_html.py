#!/usr/bin/env python3
"""docs/MANUAL.md -> a print-ready HTML page (cover, one chapter per page,
Korean fonts), for print_pdf.js. Needs the 'markdown' package
(pip install markdown). Used by: make manual-pdf."""
import datetime, os, re, sys
import markdown

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = "https://github.com/bearuse/ghazni-scope/blob/main"


def slug(text, sep="-"):
    """GitHub's heading anchors (the manual's own links use them)."""
    t = re.sub(r"<[^>]+>", "", text).strip().lower()
    t = re.sub(r"[^\w\- ]", "", t, flags=re.UNICODE)
    return t.replace(" ", sep)


def gfm(md):
    """GitHub accepts a list right after a sentence, 3-space indents and code
    fences inside list items; Python-Markdown wants a blank line before the
    list, 4 spaces, and (in a list) an indented code block. Adjust the text
    so both render the same; MANUAL.md stays as it is."""
    out, fence, in_item_code, prev = [], False, False, ""
    item = re.compile(r"^(\s*)([-*]|\d+\.) ")
    for line in md.split("\n"):
        stripped = line.lstrip()
        if in_item_code:                                            # a code block inside a list item
            if stripped.startswith("```"):
                in_item_code = False
                out.append("")
            else:
                out.append("        " + line[3:] if line.startswith("   ") else "        " + stripped)
            continue
        if stripped.startswith("```") and re.match(r"^ {1,3}```", line) and not fence:
            in_item_code = True
            out.append("")
            continue
        if stripped.startswith("```"):
            fence = not fence
        elif not fence:
            if item.match(line) and prev.strip() and not item.match(prev) and not prev.startswith((" ", "|", ">")):
                out.append("")                                      # a list right after a sentence
            if re.match(r"^ {3}\S", line) and not item.match(line):
                line = " " + line                                   # continuation of a numbered item
        out.append(line)
        prev = line
    return "\n".join(out)


def main(out):
    src = open(os.path.join(ROOT, "docs", "MANUAL.md"), encoding="utf-8").read()
    sys.path.insert(0, ROOT)
    from ghazni_scope import __version__
    title, _, body = src.partition("\n")
    title = title.lstrip("# ").strip()
    intro, _, rest = body.partition("\n---\n")             # the lead paragraph, then the rest
    rest, intro = gfm(rest), gfm(intro)
    html = markdown.markdown(rest, extensions=["tables", "fenced_code", "toc"],
                             extension_configs={"toc": {"slugify": slug}})
    lead = markdown.markdown(intro, extensions=["tables"])
    docs = os.path.join(ROOT, "docs")

    def link(m):
        attr, url = m.group(1), m.group(2)
        if url.startswith(("http", "#", "mailto:")):
            return m.group(0)
        path, _, frag = url.partition("#")
        full = os.path.normpath(os.path.join(docs, path))
        if attr == "src":                                   # images: from the files themselves
            return f'src="file://{full}"'
        rel = os.path.relpath(full, ROOT)                   # other documents: on GitHub
        return f'href="{REPO}/{rel}' + (f"#{frag}" if frag else "") + '"'
    html = re.sub(r'(href|src)="([^"]+)"', link, html)
    lead = re.sub(r'(href|src)="([^"]+)"', link, lead)
    html = html.replace("<hr />", "")
    today = datetime.date.today().isoformat()
    css = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "manual.css"), encoding="utf-8").read()
    page = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>{title}</title><style>{css}</style></head>
<body>
<section class="cover">
  <div class="mark">Ghazni Scope</div>
  <h1 class="title">사용 매뉴얼</h1>
  <p class="sub">실시간 운영체제를 브라우저로 들여다보기<br>FreeRTOS · ESP32 (ESP-IDF) · Ghazni</p>
  <img class="shot" src="file://{os.path.join(ROOT, 'screenshots', '01-trace-view.png')}">
  <p class="ver">ghazni-scope {__version__} · {today}<br>https://github.com/bearuse/ghazni-scope · MIT License</p>
</section>
<section class="lead">{lead}</section>
{html}
</body></html>"""
    open(out, "w", encoding="utf-8").write(page)
    print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "manual.html")
