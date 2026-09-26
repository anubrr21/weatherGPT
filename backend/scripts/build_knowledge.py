import html
import json
import re
import shutil
import urllib.request
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent / "knowledge"
RAW = ROOT / "raw"
CHUNK_CHARS = 1100
MIN_CHARS = 180


class TextExtractor(HTMLParser):
    SKIP = {"script", "style", "nav", "header", "footer", "noscript", "form", "button", "select", "svg"}
    BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "br", "div", "td", "th", "section", "article"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 WeatherGPT knowledge builder"})
    with urllib.request.urlopen(request, timeout=180) as response, open(dest, "wb") as out:
        shutil.copyfileobj(response, out)


def clean_line(line: str) -> str:
    line = re.sub(r"\s+", " ", line).strip()
    line = re.sub(r"\.{4,}.*$", "", line)
    line = re.sub(r"…{2,}.*$", "", line)
    return line.strip()


def useful(line: str) -> bool:
    if len(line) < 3 or re.fullmatch(r"[\d\s.\-–|()ivxIVX]+", line):
        return False
    letters = sum(c.isalpha() for c in line)
    return letters >= max(3, len(line) * 0.35)


def html_pages(path: Path) -> list[tuple[int, list[str]]]:
    parser = TextExtractor()
    parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    lines = [clean_line(l) for l in html.unescape("".join(parser.parts)).split("\n")]
    return [(0, [l for l in lines if useful(l)])]


def pdf_pages(path: Path) -> list[tuple[int, list[str]]]:
    reader = PdfReader(str(path), strict=False)
    pages = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        if text.count("…") + text.count("....") > 12:
            continue
        text = re.sub(r"-\n(\w)", r"\1", text)
        lines = [clean_line(l) for l in text.split("\n")]
        pages.append((number, [l for l in lines if useful(l)]))
    return pages


def paragraphs(lines: list[str]) -> list[str]:
    paras: list[str] = []
    current = ""
    for line in lines:
        starts_new = line.startswith("- ") or re.match(r"^(\(?[ivx\d]+[.)]|[A-Z][A-Za-z ]{2,40}:$)", line)
        if current and (starts_new or current.endswith((".", ":", ";")) and len(current) > 200):
            paras.append(current)
            current = line
        else:
            current = f"{current} {line}".strip()
    if current:
        paras.append(current)
    return paras


def chunk(source: dict, pages: list[tuple[int, list[str]]]) -> list[dict]:
    chunks: list[dict] = []
    buffer: list[str] = []
    first_page = None
    size = 0

    def flush() -> None:
        nonlocal buffer, size, first_page
        text = " ".join(buffer).strip()
        if len(text) >= MIN_CHARS:
            chunks.append({
                "id": f"{source['id']}#{len(chunks) + 1}",
                "source_id": source["id"],
                "title": source["title"],
                "publisher": source["publisher"],
                "url": source["url"],
                "page": first_page or None,
                "text": text,
            })
        buffer = buffer[-1:] if buffer and len(buffer[-1]) < CHUNK_CHARS // 3 else []
        size = sum(len(b) for b in buffer)
        first_page = None

    for number, lines in pages:
        for para in paragraphs(lines):
            if first_page is None:
                first_page = number
            buffer.append(para)
            size += len(para)
            if size >= CHUNK_CHARS:
                flush()
    flush()
    return chunks


def strip_boilerplate(docs: dict[str, list[tuple[int, list[str]]]], sources: dict[str, dict]) -> None:
    by_publisher: dict[str, Counter] = {}
    for sid, pages in docs.items():
        if sources[sid]["type"] != "html":
            continue
        seen = {l for _, lines in pages for l in lines}
        by_publisher.setdefault(sources[sid]["publisher"], Counter()).update(seen)
    for sid, pages in docs.items():
        if sources[sid]["type"] != "html":
            continue
        counts = by_publisher[sources[sid]["publisher"]]
        total = sum(1 for s in docs if sources[s]["type"] == "html" and sources[s]["publisher"] == sources[sid]["publisher"])
        limit = max(2, int(total * 0.4))
        docs[sid] = [(n, [l for l in lines if counts[l] < limit]) for n, lines in pages]


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    sources = {s["id"]: s for s in json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))}
    docs: dict[str, list[tuple[int, list[str]]]] = {}
    for sid, source in sources.items():
        path = RAW / source["file"]
        try:
            download(source["url"], path)
            docs[sid] = pdf_pages(path) if source["type"] == "pdf" else html_pages(path)
        except Exception as exc:
            print(f"skip {sid}: {type(exc).__name__}: {exc}")
    strip_boilerplate(docs, sources)
    out = ROOT / "chunks.jsonl"
    total = 0
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        for sid, pages in docs.items():
            items = chunk(sources[sid], pages)
            total += len(items)
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
            print(f"{sid:28} {len(items):5} chunks")
    print(f"{total} chunks -> {out}")


if __name__ == "__main__":
    main()
