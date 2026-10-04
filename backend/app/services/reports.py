import io
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import Flowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

IST = timezone(timedelta(hours=5, minutes=30))
PAGE_W, PAGE_H = A4
MARGIN = 16 * mm
WIDTH = PAGE_W - 2 * MARGIN
NAVY = colors.HexColor("#0b1220")
INK = colors.HexColor("#1b2333")
MUTED = colors.HexColor("#5b667a")
LINE = colors.HexColor("#d9dee8")
SOFT = colors.HexColor("#f3f5f9")
SAFFRON = colors.HexColor("#ff9933")
GREEN = colors.HexColor("#1f9d55")
LEVEL = [colors.HexColor("#2fa36b"), colors.HexColor("#d9a400"), colors.HexColor("#e8741a"), colors.HexColor("#d92f4a")]
VERDICT = {"go": LEVEL[0], "caution": LEVEL[1], "hold": LEVEL[3]}
RISK = {"Low": 0, "Moderate": 1, "High": 2, "Severe": 3}
SWAPS = {"\u2192": "to", "\u2013": "-", "\u2014": "-", "\u2265": ">=", "\u2264": "<=", "\u20b9": "Rs ", "\u2022": "-", "\u2026": "...", "\u2011": "-", "\u00a0": " ", "\u202f": " ", "\u2032": "'", "\u2248": "about ", "\u2713": "", "\u2212": "-"}

BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=INK, spaceAfter=5)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8, leading=10.5, textColor=MUTED, spaceAfter=3)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=8, leading=10, spaceAfter=0)
CELL_B = ParagraphStyle("cellb", parent=CELL, fontName="Helvetica-Bold")
HEAD = ParagraphStyle("head", parent=CELL, fontName="Helvetica-Bold", textColor=colors.white)
H1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=NAVY, spaceAfter=2)
SUB = ParagraphStyle("sub", parent=BODY, fontSize=10.5, textColor=MUTED, spaceAfter=8)
H2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=NAVY, spaceBefore=10, spaceAfter=5)
H3 = ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=NAVY, spaceBefore=6, spaceAfter=3)
BULLET = ParagraphStyle("bullet", parent=BODY, leftIndent=12, bulletIndent=2, spaceAfter=3)
LABEL = ParagraphStyle("label", parent=SMALL, fontSize=7, leading=9, textColor=MUTED, spaceAfter=1)
VALUE = ParagraphStyle("value", parent=BODY, fontName="Helvetica-Bold", fontSize=10.5, leading=13, spaceAfter=0)
RIGHT = ParagraphStyle("right", parent=SMALL, alignment=TA_RIGHT)


def clean(value: Any) -> str:
    text = "" if value is None else str(value)
    for old, new in SWAPS.items():
        text = text.replace(old, new)
    return text.encode("cp1252", "replace").decode("cp1252")


def para(value: Any, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(escape(clean(value)), style)


def markup(value: str) -> str:
    text = escape(clean(value))
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)


def rich(value: str, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(markup(value), style)


def stamp(value: str | None, short: bool = False) -> str:
    if not value:
        return "-"
    try:
        moment = datetime.fromisoformat(value).astimezone(IST)
    except ValueError:
        return value
    return moment.strftime("%d %b %H:%M" if short else "%a %d %b %Y, %H:%M")


def length(minutes: float | None) -> str:
    if minutes is None:
        return "-"
    total = max(0, round(minutes))
    days, hours, mins = total // 1440, (total % 1440) // 60, total % 60
    if days:
        return f"{days} d {hours} h"
    if hours:
        return f"{hours} h {mins} min" if mins else f"{hours} h"
    return f"{mins} min"


def level_colour(level: float) -> colors.Color:
    return LEVEL[max(0, min(3, int(level)))]


def draw_logo(c: pdfcanvas.Canvas, x: float, y: float, size: float) -> None:
    u = size / 120
    cx, cy = x + size / 2, y + size / 2
    c.saveState()
    c.setStrokeColor(colors.HexColor("#f7f0e3"))
    c.setLineWidth(1.4 * u)
    c.circle(cx, cy, 44 * u, stroke=1, fill=0)
    c.setLineWidth(0.6 * u)
    c.setDash(1.5 * u, 3.2 * u)
    c.circle(cx, cy, 40 * u, stroke=1, fill=0)
    c.setDash()
    light, dark = colors.HexColor("#fff3c4"), colors.HexColor("#ffb13b")
    for turn in range(4):
        angle = math.radians(turn * 90)
        for side, shade in ((1, light), (-1, dark)):
            path = c.beginPath()
            path.moveTo(cx + 34 * u * math.sin(angle), cy + 34 * u * math.cos(angle))
            path.lineTo(cx + 5 * u * math.sin(angle) + side * 5 * u * math.cos(angle), cy + 5 * u * math.cos(angle) - side * 5 * u * math.sin(angle))
            path.lineTo(cx, cy)
            path.close()
            c.setFillColor(shade)
            c.drawPath(path, stroke=0, fill=1)
    for turn in range(4):
        angle = math.radians(45 + turn * 90)
        path = c.beginPath()
        path.moveTo(cx + 27 * u * math.sin(angle), cy + 27 * u * math.cos(angle))
        path.lineTo(cx + 3 * u * math.cos(angle), cy - 3 * u * math.sin(angle))
        path.lineTo(cx - 3 * u * math.cos(angle), cy + 3 * u * math.sin(angle))
        path.close()
        c.setFillColor(colors.HexColor("#e39a2d"))
        c.drawPath(path, stroke=0, fill=1)
    for radius, shade in ((10, "#ff6a3d"), (7, "#ffb13b"), (3.4, "#fff8e6")):
        c.setFillColor(colors.HexColor(shade))
        c.circle(cx, cy, radius * u, stroke=0, fill=1)
    peak = c.beginPath()
    peak.moveTo(cx - 14 * u, cy + 44 * u)
    peak.lineTo(cx, cy + 58.5 * u)
    peak.lineTo(cx + 14 * u, cy + 44 * u)
    peak.close()
    c.setFillColor(colors.HexColor("#6b76c9"))
    c.drawPath(peak, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#e6f4ff"))
    cap = c.beginPath()
    cap.moveTo(cx - 6.5 * u, cy + 51.3 * u)
    cap.lineTo(cx, cy + 58.5 * u)
    cap.lineTo(cx + 6.5 * u, cy + 51.3 * u)
    cap.close()
    c.drawPath(cap, stroke=0, fill=1)
    c.setStrokeColor(colors.HexColor("#ffb13b"))
    c.setLineWidth(2.2 * u)
    c.circle(cx + 44 * u, cy, 10.5 * u, stroke=1, fill=0)
    c.setFillColor(colors.HexColor("#d0283c"))
    c.circle(cx + 44 * u, cy, 2.6 * u, stroke=0, fill=1)
    kite = c.beginPath()
    kite.moveTo(cx - 44 * u, cy + 13 * u)
    kite.lineTo(cx - 33 * u, cy)
    kite.lineTo(cx - 44 * u, cy - 13 * u)
    kite.lineTo(cx - 55 * u, cy)
    kite.close()
    c.setFillColor(colors.HexColor("#ff4f8b"))
    c.drawPath(kite, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#f7f0e3"))
    for dx, dy in ((-6, -50), (0, -56), (6, -50)):
        c.circle(cx + dx * u, cy + dy * u, 2.3 * u, stroke=0, fill=1)
    c.restoreState()


class Numbered(pdfcanvas.Canvas):
    title = ""
    generated = ""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pages: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self._frame(total)
            super().showPage()
        super().save()

    def _frame(self, total: int) -> None:
        band = 19 * mm
        self.saveState()
        self.setFillColor(NAVY)
        self.rect(0, PAGE_H - band, PAGE_W, band, stroke=0, fill=1)
        for n, shade in enumerate((SAFFRON, colors.white, GREEN)):
            self.setFillColor(shade)
            self.rect(n * PAGE_W / 3, PAGE_H - band - 1.1 * mm, PAGE_W / 3, 1.1 * mm, stroke=0, fill=1)
        draw_logo(self, MARGIN - 1 * mm, PAGE_H - band + 2.6 * mm, 13.5 * mm)
        text_x = MARGIN + 16 * mm
        self.setFont("Helvetica-Bold", 15)
        self.setFillColor(colors.white)
        self.drawString(text_x, PAGE_H - band + 8.2 * mm, "Weather")
        offset = self.stringWidth("Weather", "Helvetica-Bold", 15)
        self.setFillColor(SAFFRON)
        self.drawString(text_x + offset, PAGE_H - band + 8.2 * mm, "GPT")
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#b9c2d6"))
        self.drawString(text_x, PAGE_H - band + 4.2 * mm, "Weather intelligence for India")
        self.setFont("Helvetica-Bold", 9.5)
        self.setFillColor(colors.white)
        self.drawRightString(PAGE_W - MARGIN, PAGE_H - band + 9.4 * mm, clean(self.title))
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#b9c2d6"))
        self.drawRightString(PAGE_W - MARGIN, PAGE_H - band + 5 * mm, clean(self.generated))
        self.setStrokeColor(LINE)
        self.setLineWidth(0.6)
        self.line(MARGIN, 13 * mm, PAGE_W - MARGIN, 13 * mm)
        self.setFont("Helvetica", 7)
        self.setFillColor(MUTED)
        self.drawString(MARGIN, 9 * mm, "Forecasts: Open-Meteo. Official warnings: NDMA SACHET (IMD and state authorities). Cyclones: GDACS. Routes: OpenStreetMap.")
        self.drawString(MARGIN, 6 * mm, "Decision support only. Follow official warnings and your own operating procedures.")
        self.drawRightString(PAGE_W - MARGIN, 9 * mm, f"Page {self._pageNumber} of {total}")
        self.restoreState()


class Banner(Flowable):
    def __init__(self, heading: str, kicker: str, lines: list[str], shade: colors.Color) -> None:
        super().__init__()
        self.heading, self.kicker, self.shade = heading, kicker, shade
        self.items = [Paragraph("- " + escape(clean(line)), ParagraphStyle("reason", parent=BODY, fontSize=9, leading=12, spaceAfter=1)) for line in lines]
        self.width = WIDTH

    def wrap(self, available: float, _: float) -> tuple[float, float]:
        self.inner = available - 14 * mm
        self.heights = [item.wrap(self.inner, 1000)[1] for item in self.items]
        self.height = 22 * mm + sum(self.heights) + 3 * mm
        return available, self.height

    def draw(self) -> None:
        c = self.canv
        c.setFillColor(SOFT)
        c.setStrokeColor(LINE)
        c.roundRect(0, 0, self.width, self.height, 3 * mm, stroke=1, fill=1)
        c.setFillColor(self.shade)
        c.roundRect(0, 0, 3.2 * mm, self.height, 1.4 * mm, stroke=0, fill=1)
        c.setFont("Helvetica", 7.5)
        c.setFillColor(MUTED)
        c.drawString(8 * mm, self.height - 7 * mm, clean(self.kicker).upper())
        c.setFont("Helvetica-Bold", 20)
        c.setFillColor(self.shade)
        c.drawString(8 * mm, self.height - 16.5 * mm, clean(self.heading))
        y = self.height - 21 * mm
        for item, tall in zip(self.items, self.heights):
            y -= tall
            item.drawOn(c, 8 * mm, y)


class RouteSketch(Flowable):
    def __init__(self, tracks: list[dict[str, Any]], height: float = 78 * mm, labels: list[tuple[float, float, str]] | None = None) -> None:
        super().__init__()
        self.tracks, self.height, self.labels, self.width = tracks, height, labels or [], WIDTH

    def wrap(self, available: float, _: float) -> tuple[float, float]:
        self.width = available
        return available, self.height

    def draw(self) -> None:
        c = self.canv
        every = [pt for track in self.tracks for pt in track["line"]]
        if not every:
            return
        lats, lons = [p[0] for p in every], [p[1] for p in every]
        mid = math.radians((min(lats) + max(lats)) / 2)
        squeeze = max(0.3, math.cos(mid))
        span_x = max(0.4, (max(lons) - min(lons)) * squeeze)
        span_y = max(0.4, max(lats) - min(lats))
        pad = 9 * mm
        scale = min((self.width - 2 * pad) / span_x, (self.height - 2 * pad) / span_y)
        off_x = (self.width - span_x * scale) / 2
        off_y = (self.height - span_y * scale) / 2

        def place(lat: float, lon: float) -> tuple[float, float]:
            return off_x + (lon - min(lons)) * squeeze * scale, off_y + (lat - min(lats)) * scale

        c.setFillColor(colors.HexColor("#f6f8fc"))
        c.setStrokeColor(LINE)
        c.roundRect(0, 0, self.width, self.height, 3 * mm, stroke=1, fill=1)
        c.setLineCap(1)
        c.setLineJoin(1)
        for track in self.tracks:
            line = track["line"]
            c.setStrokeColor(colors.HexColor("#c5ccda"))
            c.setLineWidth(track.get("weight", 3.2) + 1.6)
            path = c.beginPath()
            path.moveTo(*place(*line[0]))
            for pt in line[1:]:
                path.lineTo(*place(*pt))
            c.drawPath(path, stroke=1, fill=0)
        for track in self.tracks:
            marks = track.get("marks") or []
            line = track["line"]
            if not marks:
                c.setStrokeColor(level_colour(track.get("level", 0)))
                c.setLineWidth(track.get("weight", 3.2))
                path = c.beginPath()
                path.moveTo(*place(*line[0]))
                for pt in line[1:]:
                    path.lineTo(*place(*pt))
                c.drawPath(path, stroke=1, fill=0)
                continue
            nearest = [min(range(len(line)), key=lambda k: (line[k][0] - m["lat"]) ** 2 + (line[k][1] - m["lon"]) ** 2) for m in marks]
            for k in range(len(marks) - 1):
                piece = line[nearest[k]:max(nearest[k] + 2, nearest[k + 1] + 1)]
                c.setStrokeColor(level_colour(max(marks[k]["level"], marks[k + 1]["level"])))
                c.setLineWidth(track.get("weight", 3.2))
                path = c.beginPath()
                path.moveTo(*place(*piece[0]))
                for pt in piece[1:]:
                    path.lineTo(*place(*pt))
                c.drawPath(path, stroke=1, fill=0)
        c.setFont("Helvetica-Bold", 7.5)
        for lat, lon, name in self.labels:
            px, py = place(lat, lon)
            c.setFillColor(colors.white)
            c.setStrokeColor(NAVY)
            c.setLineWidth(1)
            c.circle(px, py, 2.4, stroke=1, fill=1)
            c.setFillColor(NAVY)
            text = clean(name)
            wide = c.stringWidth(text, "Helvetica-Bold", 7.5)
            c.drawString(min(max(2, px + 4), self.width - wide - 2), py + 3, text)
        x = 5 * mm
        c.setFont("Helvetica", 7)
        for n, word in enumerate(("Clear", "Moderate", "High", "Severe")):
            c.setFillColor(LEVEL[n])
            c.rect(x, 3.5 * mm, 5 * mm, 1.6 * mm, stroke=0, fill=1)
            c.setFillColor(MUTED)
            c.drawString(x + 6 * mm, 3.2 * mm, word)
            x += 24 * mm


class Bars(Flowable):
    def __init__(self, items: list[dict[str, Any]], best: str | None, height: float = 34 * mm) -> None:
        super().__init__()
        self.items, self.best, self.height, self.width = items, best, height, WIDTH

    def wrap(self, available: float, _: float) -> tuple[float, float]:
        self.width = available
        return available, self.height

    def draw(self) -> None:
        c = self.canv
        if not self.items:
            return
        base = 8 * mm
        top = self.height - 4 * mm
        peak = max(30, max(d["delay_min"] for d in self.items))
        step = self.width / len(self.items)
        c.setStrokeColor(LINE)
        c.line(0, base, self.width, base)
        every = max(1, round(len(self.items) / 8))
        for k, item in enumerate(self.items):
            tall = 3 + (item["delay_min"] / peak) * (top - base - 3)
            c.setFillColor(LEVEL[RISK.get(item["risk"], 0)])
            c.rect(k * step + step * 0.14, base, step * 0.72, tall, stroke=0, fill=1)
            if item["depart"] == self.best:
                c.setStrokeColor(NAVY)
                c.setLineWidth(1.1)
                c.rect(k * step + step * 0.06, base - 0.6, step * 0.88, tall + 1.6, stroke=1, fill=0)
            if k % every == 0:
                c.setFont("Helvetica", 6.5)
                c.setFillColor(MUTED)
                c.drawString(k * step, 2.6 * mm, stamp(item["depart"], short=True))


class Profile(Flowable):
    def __init__(self, points: list[dict[str, Any]], height: float = 36 * mm) -> None:
        super().__init__()
        self.points = [p for p in points if p.get("weather") and p["weather"].get("temp") is not None]
        self.height, self.width = height, WIDTH

    def wrap(self, available: float, _: float) -> tuple[float, float]:
        self.width = available
        return available, self.height

    def draw(self) -> None:
        c = self.canv
        if len(self.points) < 2:
            return
        temps = [p["weather"]["temp"] for p in self.points]
        dews = [p["weather"]["dew"] for p in self.points if p["weather"].get("dew") is not None]
        low, high = math.floor(min(temps + dews) - 1), math.ceil(max(temps + dews) + 1)
        left, base, top = 9 * mm, 7 * mm, self.height - 3 * mm
        far = self.points[-1]["km"] or 1

        def place(km: float, value: float) -> tuple[float, float]:
            return left + (km / far) * (self.width - left - 2 * mm), base + (value - low) / max(1, high - low) * (top - base)

        c.setFont("Helvetica", 6.5)
        c.setFillColor(MUTED)
        c.setStrokeColor(LINE)
        c.setLineWidth(0.4)
        for tick in range(4):
            value = low + (high - low) * tick / 3
            y = place(0, value)[1]
            c.line(left, y, self.width - 2 * mm, y)
            c.drawRightString(left - 1.5 * mm, y - 2, f"{value:.0f}")
        for tick in range(5):
            km = far * tick / 4
            c.drawCentredString(place(km, low)[0], 2 * mm, f"km {km:.0f}")
        for key, shade, weight in (("dew", colors.HexColor("#3f8cff"), 1.1), ("temp", colors.HexColor("#e8741a"), 1.6)):
            series = [(p["km"], p["weather"][key]) for p in self.points if p["weather"].get(key) is not None]
            if len(series) < 2:
                continue
            c.setStrokeColor(shade)
            c.setLineWidth(weight)
            path = c.beginPath()
            path.moveTo(*place(*series[0]))
            for item in series[1:]:
                path.lineTo(*place(*item))
            c.drawPath(path, stroke=1, fill=0)
        c.setFillColor(colors.HexColor("#e8741a"))
        c.drawString(left + 2, top - 2, "Air temperature (deg C)")
        c.setFillColor(colors.HexColor("#3f8cff"))
        c.drawString(left + 82, top - 2, "Dew point (deg C)")


def table(header: list[str], rows: list[list[Any]], widths: list[float], shades: list[colors.Color | None] | None = None) -> Table:
    total = sum(widths)
    cols = [WIDTH * w / total for w in widths]
    data = [[Paragraph(escape(clean(h)), HEAD) for h in header]]
    for row in rows:
        data.append([cell if isinstance(cell, Flowable) else Paragraph(escape(clean(cell)), CELL) for cell in row])
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SOFT]), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for n, shade in enumerate(shades or []):
        if shade is not None:
            style.append(("LINEBEFORE", (0, n + 1), (0, n + 1), 2.4, shade))
    made = Table(data, colWidths=cols, repeatRows=1)
    made.setStyle(TableStyle(style))
    return made


def facts(pairs: list[tuple[str, str]], columns: int = 3) -> Table:
    cells = [[Paragraph(escape(clean(label)).upper(), LABEL), Paragraph(escape(clean(value)), VALUE)] for label, value in pairs]
    while len(cells) % columns:
        cells.append([Spacer(1, 1)])
    rows = [cells[i:i + columns] for i in range(0, len(cells), columns)]
    made = Table(rows, colWidths=[WIDTH / columns] * columns)
    made.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return made


def bullets(lines: list[str]) -> list[Flowable]:
    return [Paragraph(escape(clean(line)), BULLET, bulletText="-") for line in lines]


def markdown(text: str) -> list[Flowable]:
    out: list[Flowable] = []
    for raw in re.sub(r"<speak>.*?</speak>", "", text, flags=re.S).splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = re.match(r"^#{1,4}\s+(.*)$", line)
        item = re.match(r"^(?:[-*•]|\d+[.)])\s+(.*)$", line)
        if heading:
            out.append(rich(heading.group(1).strip("*"), H3))
        elif item:
            out.append(Paragraph(markup(item.group(1)), BULLET, bulletText="-"))
        else:
            out.append(rich(line))
    return out


def render(title: str, story: list[Flowable]) -> bytes:
    buffer = io.BytesIO()
    now = datetime.now(IST)

    class Page(Numbered):
        pass

    Page.title = title
    Page.generated = f"Generated {now.strftime('%d %b %Y, %H:%M')} IST"
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=27 * mm, bottomMargin=18 * mm, title=f"WeatherGPT - {title}", author="WeatherGPT")
    doc.build(story, canvasmaker=Page)
    return buffer.getvalue()


def near(item: dict[str, Any], key: str = "near") -> str:
    return f" near {item[key]}" if item.get(key) else ""


def shipment_report(result: dict[str, Any], index: int = 0, analysis: str | None = None, ref: str | None = None) -> bytes:
    route = result["routes"][index]
    origin, destination = result["origin"]["name"], result["destination"]["name"]
    what = " · ".join(x for x in (result["mode_label"], result.get("vehicle_label"), result["cargo_label"]) if x)
    story: list[Flowable] = [
        para("Shipment weather risk report", H1),
        para(f"{origin} to {destination}" + (f"   |   Reference {ref}" if ref else ""), SUB),
        Banner(route["verdict"]["label"], what, route["verdict"]["reasons"], VERDICT[route["verdict"]["code"]]),
        Spacer(1, 4 * mm),
        facts([
            ("Dispatch (IST)", stamp(route["depart"])), ("Expected arrival (IST)", stamp(route["arrive"])), ("Latest arrival (IST)", stamp(route["arrive_latest"])),
            ("Distance", f"{route['distance_km']:,.0f} km"), ("Door to door", length(route["duration_min"])), ("Moving time, clear weather", length(route["base_min"])),
            ("Weather delay", f"{length(route['delay_min'])} (up to {length(route['delay_worst_min'])})" if route["delay_worst_min"] else "None"),
            ("Driver rest", length(route["rest_min"]) if route["rest_min"] else "None"), ("Route risk", f"{route['risk']['label']} ({route['risk']['score']:.2f})"),
            ("Cargo status", {"ok": "Safe", "watch": "Watch", "risk": "At risk"}[route["cargo"]["status"]]),
            ("Forecast confidence", f"{route['confidence']['label']} ({route['confidence']['score']}/100)"), ("Route", route["summary"]),
        ]),
        para("Summary", H2),
    ]
    story += [para(line) for line in route["narrative"]]

    if route.get("geometry"):
        ends = [(route["points"][0]["lat"], route["points"][0]["lon"], origin), (route["points"][-1]["lat"], route["points"][-1]["lon"], destination)]
        named: dict[str, dict[str, Any]] = {}
        for p in route["points"][1:-1]:
            if p.get("place") and p["place"] not in (origin, destination) and not origin.startswith(p["place"]) and not destination.startswith(p["place"]):
                named.setdefault(p["place"], p)
        middle = list(named.values())
        labels = ends + [(p["lat"], p["lon"], p["place"]) for p in middle[:: max(1, len(middle) // 4)][:4]]
        story.append(KeepTogether([para("Route and hazard map", H2), RouteSketch([{"line": route["geometry"], "marks": route["points"]}], height=58 * mm, labels=labels), para("The line is coloured by the worst weather forecast for each stretch at the hour the shipment passes it.", SMALL)]))

    if route["actions"]:
        story.append(para("Recommended actions", H2))
        story += bullets(route["actions"])

    if analysis:
        story.append(para("WeatherGPT analysis", H2))
        story += markdown(analysis)

    story.append(para("Delay and hazard breakdown", H2))
    if route["breakdown"]:
        story.append(table(
            ["Cause", "Severity", "Distance affected", "Time affected", "Delay added", "Worst condition"],
            [[row["label"], row["severity"], f"{row['km']} km", f"{row['hours']:g} h", length(row["delay_min"]) if row["delay_min"] else "-", row["worst"]] for row in route["breakdown"]],
            [20, 13, 15, 13, 13, 46], [level_colour(row["level"]) for row in route["breakdown"]],
        ))
    else:
        story.append(para("No weather on this route slows the shipment or reaches a hazard threshold."))

    if route["hazards"]:
        story.append(para("Hazard stretches", H2))
        story.append(table(
            ["Stretch", "When (IST)", "Condition", "Severity", "Advice"],
            [[f"km {h['from_km']:.0f}-{h['to_km']:.0f}{near(h)}", f"{stamp(h['from_eta'], True)} to {stamp(h['to_eta'], True)[-5:]}", h["detail"], h["severity"], h.get("advice") or "-"] for h in route["hazards"]],
            [22, 19, 30, 11, 38], [level_colour(h["level"]) for h in route["hazards"]],
        ))

    if route.get("stages"):
        sea = result["mode"] == "sea"
        story.append(para("Stage by stage", H2))
        story.append(table(
            ["Stage", "Window (IST)", "Sky", "Temp", "Rain", "Gusts", "Waves" if sea else "Visibility", "Speed loss", "Main concern"],
            [[
                f"km {st['from_km']:.0f}-{st['to_km']:.0f}" + (f" ({st['from']} to {st['to']})" if st.get("from") and st.get("to") else ""),
                f"{stamp(st['from_eta'], True)} to {stamp(st['to_eta'], True)[-5:]}" + (" (night)" if st["night"] else ""), st["sky"],
                f"{st['temp_min']}-{st['temp_max']} C" if st["temp_min"] is not None else "-", f"{st['rain_mm']:g} mm", f"{st['gust_max']} km/h" if st["gust_max"] is not None else "-",
                (f"{st['wave_max']} m" if st["wave_max"] is not None else "-") if sea else (f"{st['vis_min'] / 1000:.0f} km" if (st["vis_min"] or 0) >= 1000 else f"{st['vis_min']} m" if st["vis_min"] is not None else "-"),
                f"{st['slow_pct']}%" if st["slow_pct"] else "-", st["worst"] or "None",
            ] for st in route["stages"]],
            [24, 20, 13, 10, 9, 10, 12, 10, 24], [level_colour(st["level"]) for st in route["stages"]],
        ))

    if len(route["departures"]) >= 3:
        best = route["best_departure"]["depart"] if route["best_departure"] else None
        block: list[Flowable] = [para("Dispatch window, next 48 hours", H2), Bars(route["departures"], best), para("Bar height is the weather delay for a dispatch at that hour; colour is the route risk. The outlined bar is the recommended time.", SMALL)]
        story.append(KeepTogether(block))
        if route.get("top_departures"):
            story.append(table(
                ["Dispatch (IST)", "Arrival (IST)", "Risk", "Weather delay", "Share in darkness"],
                [[stamp(d["depart"]), stamp(d["arrive"]), d["risk"], length(d["delay_min"]) if d["delay_min"] else "None", f"{d['night'] * 100:.0f}%"] for d in route["top_departures"]],
                [26, 26, 14, 18, 16], [LEVEL[RISK.get(d["risk"], 0)] for d in route["top_departures"]],
            ))

    cargo = route["cargo"]
    story.append(para(f"Cargo exposure: {cargo['label']}", H2))
    if cargo["metrics"]:
        story.append(facts([(m["label"], m["value"]) for m in cargo["metrics"]], columns=min(3, len(cargo["metrics"]))))
        story.append(Spacer(1, 2 * mm))
    story += bullets(cargo["notes"]) if cargo["notes"] else [para("Nothing in the forecast threatens this cargo on this trip.")]
    if route.get("points") and route["points"][0].get("weather"):
        story.append(KeepTogether([para("Temperature and dew point along the route", H3), Profile(route["points"])]))

    if route["warnings"] or route["cyclones"]:
        story.append(para("Official warnings and cyclones on the route", H2))
        rows = [[f"Cyclone {c.get('name') or 'system'}", "-", f"near km {c['route_km']:.0f}", f"Passes within {c['closest_km']} km" + (f" around {stamp(c['closest_time'])} IST" if c.get("closest_time") else ""), "Yes"] for c in route["cyclones"]]
        rows += [[w["event"], w["severity"] or "-", f"km {w['from_km']}-{w['to_km']}", f"{w.get('issuer') or ''}; valid until {stamp(w.get('expires'))} IST", "Yes" if w["active_on_arrival"] else "Expires first"] for w in route["warnings"]]
        story.append(table(["Warning", "Severity", "Stretch", "Issued by and validity", "In force on arrival"], rows, [26, 12, 14, 34, 14]))

    if route["rests"]:
        story.append(para("Driver rest plan", H2))
        story.append(table(
            ["Stop", "At (IST)", "Location", "Duration"],
            [["Overnight halt" if r["kind"] == "halt" else "Break", stamp(r["at"]), f"km {r['km']:.0f}{near(r)}", length(r["minutes"])] for r in route["rests"]],
            [20, 28, 36, 16],
        ))
        if route.get("other_crew"):
            other = route["other_crew"]
            story.append(para(f"With {'two drivers' if other['crew'] == 2 else 'one driver'} the shipment would arrive {stamp(other['arrive'])} IST after {length(other['duration_min'])}, with {length(other['rest_min'])} of rest.", SMALL))

    if route.get("model_check"):
        story.append(para("Agreement between weather models", H2))
        story.append(table(
            ["Checkpoint", "Date", "Confidence", "Rain agreement", "Rain by model", "Max temp by model"],
            [[
                f"{c['where']}" + (f" ({c['place']})" if c.get("place") else ""), c["date"], f"{c['label']} ({c['score']}/100)", c["rain_agreement"],
                "; ".join(f"{m['name']} {m['rain_mm']:g} mm" for m in c["models"] if m["rain_mm"] is not None), "; ".join(f"{m['name']} {m['tmax']:.0f} C" for m in c["models"] if m["tmax"] is not None),
            ] for c in route["model_check"]],
            [18, 12, 14, 20, 20, 20],
        ))

    if route.get("extremes"):
        story.append(para("Extremes on the route", H2))
        story.append(table(["Measure", "Value", "Where", "When (IST)"], [[e["label"], e["value"], f"km {e['km']:.0f}{near(e, 'place')}", stamp(e["eta"])] for e in route["extremes"]], [22, 16, 36, 26]))

    if len(result["routes"]) > 1:
        story.append(para("Route alternatives", H2))
        story.append(table(
            ["Route", "Distance", "Door to door", "Weather delay", "Risk", "Verdict"],
            [[r["summary"], f"{r['distance_km']:,.0f} km", length(r["duration_min"]), length(r["delay_min"]) if r["delay_min"] else "None", r["risk"]["label"], r["verdict"]["label"]] for r in result["routes"]],
            [30, 13, 16, 15, 11, 18], [VERDICT[r["verdict"]["code"]] for r in result["routes"]],
        ))

    if route.get("points") and "weather" in route["points"][0]:
        sea = result["mode"] == "sea"
        story += [PageBreak(), para("Full route log", H2), para("Forecast at each sample point for the hour the shipment is expected there.", SMALL)]
        rows = []
        for p in route["points"]:
            w = p.get("weather") or {}
            sight = w.get("visibility")
            rows.append([
                f"{p['km']:.0f}", p.get("place") or "-", stamp(p["eta"], True), w.get("label") or "-", f"{w['temp']:.0f}" if w.get("temp") is not None else "-",
                f"{w['rain_mmh']:g}" if w.get("rain_mmh") is not None else "-", f"{w['gust']:.0f}" if w.get("gust") is not None else "-",
                (f"{w['wave']:g}" if w.get("wave") is not None else "-") if sea else ("-" if sight is None else f"{sight / 1000:.0f} km" if sight >= 1000 else f"{sight:.0f} m"),
                f"{p['slow_pct']}%" if p.get("slow_pct") else "-", "; ".join(h["detail"] for h in p.get("hazards") or []) or "-",
            ])
        story.append(table(["km", "Near", "ETA (IST)", "Sky", "C", "mm/h", "Gust", "Waves m" if sea else "Visibility", "Slower", "Hazard"], rows, [7, 16, 12, 14, 5, 8, 7, 12, 10, 30], [level_colour(p["level"]) for p in route["points"]]))

    story.append(para("How this was worked out", H2))
    method = result["method"]
    notes = [route["source"] + ".", method["eta"]]
    if result["mode"] == "road":
        notes += [method["road_speed"], method["driver_hours"]]
    notes += [route["confidence"]["note"], method["limits"]]
    story += bullets(notes)
    return render("Shipment weather risk report", story)


def fleet_report(board: dict[str, Any]) -> bytes:
    s = board["summary"]
    done = [r for r in board["shipments"] if r["ok"]]
    story: list[Flowable] = [
        para("Fleet weather board", H1),
        para(f"{s['total']} shipments assessed against the weather on their routes", SUB),
        facts([("Go", str(s["go"])), ("Go with caution", str(s["caution"])), ("Hold or reroute", str(s["hold"])), ("Could not be assessed", str(s["failed"])), ("Total weather delay", length(s["delay_min"]) if s["delay_min"] else "None"), ("Shipments", str(s["total"]))]),
        para("Shipments", H2),
        table(
            ["Reference", "Route", "Mode and cargo", "Dispatch (IST)", "Arrival (IST)", "Delay", "Verdict"],
            [[r.get("ref") or "-", f"{r['origin']['name']} to {r['destination']['name']} ({r['distance_km']:,.0f} km)", " / ".join(x for x in (r["mode_label"], r.get("vehicle_label"), r["cargo_label"]) if x), stamp(r["depart"], True), stamp(r["arrive"], True), length(r["delay_min"]) if r["delay_min"] else "None", r["verdict"]["label"]] for r in done],
            [14, 28, 24, 13, 13, 9, 14], [VERDICT[r["verdict"]["code"]] for r in done],
        ),
    ]
    flagged = [r for r in done if r["verdict"]["code"] != "go" or r.get("worst") or r.get("best_departure")]
    if flagged:
        story.append(para("Shipments needing attention", H2))
        for r in flagged:
            lines = list(r["verdict"]["reasons"])
            if r.get("worst"):
                lines.append(f"Worst stretch: {r['worst']['detail']} between km {r['worst']['from_km']:.0f} and {r['worst']['to_km']:.0f}{near(r['worst'])}.")
            if r.get("warnings"):
                lines.append(f"{r['warnings']} official warning(s) in force on the route.")
            if r.get("cargo_status") == "risk":
                lines.append("The cargo is at risk from the weather on this trip.")
            if r.get("best_departure"):
                lines.append(r["best_departure"]["why"])
            story.append(KeepTogether([para(f"{r.get('ref') or ''}  {r['origin']['name']} to {r['destination']['name']}: {r['verdict']['label']}", H3), *bullets(lines)]))
    failed = [r for r in board["shipments"] if not r["ok"]]
    if failed:
        story.append(para("Not assessed", H2))
        story += bullets([f"{r.get('ref') or 'Shipment'}: {r.get('error')}" for r in failed])
    tracks = [{"line": [(p["lat"], p["lon"]) for p in r["track"]], "marks": r["track"], "weight": 2.4} for r in done if len(r.get("track") or []) > 1]
    if tracks:
        story.append(KeepTogether([para("Routes", H2), RouteSketch(tracks, height=95 * mm)]))
    return render("Fleet weather board", story)


def network_report(board: dict[str, Any]) -> bytes:
    s = board["summary"]
    lanes = board["lanes"]
    cities: dict[str, tuple[float, float]] = {}
    for lane in lanes:
        cities[lane["from"]["name"]] = (lane["from"]["lat"], lane["from"]["lon"])
        cities[lane["to"]["name"]] = (lane["to"]["lat"], lane["to"]["lon"])
    story: list[Flowable] = [
        para("Freight corridor weather status", H1),
        para(f"{s['total']} road corridors, {board['vehicle'].lower()} with two drivers leaving now", SUB),
        facts([("Corridors affected", f"{s['affected']} of {s['total']}"), ("Running clear", str(s["clear"])), ("Weather delay across the network", length(s["delay_min"]) if s["delay_min"] else "None"), ("Worst corridor", s["worst"] or "None"), ("Status time (IST)", stamp(board["generated_at"])), ("Outlook", "Leaving now and in 6, 12, 24 and 36 hours")]),
        Spacer(1, 3 * mm),
        RouteSketch([{"line": lane["geometry"], "marks": lane["segments"], "weight": 2.6} for lane in sorted(lanes, key=lambda l: l["risk"]["score"])], height=120 * mm, labels=[(lat, lon, name) for name, (lat, lon) in cities.items()]),
        para("Corridors, worst first", H2),
        table(
            ["Corridor", "Distance", "Trip time now", "Weather delay", "Risk", "Delay if leaving later", "Worst condition", "Warnings"],
            [[
                lane["name"], f"{lane['distance_km']:,} km", length(lane["duration_min"]), f"{length(lane['delay_min'])} (up to {length(lane['delay_worst_min'])})" if lane["delay_min"] else "None", lane["risk"]["label"],
                ", ".join(f"+{o['hours']}h {o['delay_min']}m" for o in lane["outlook"][1:]) or "-", f"{lane['worst']['detail']} around km {lane['worst']['km']:.0f}" if lane["worst"] else "None",
                ", ".join(sorted({w["event"] for w in lane["warnings"]})) or "-",
            ] for lane in lanes],
            [19, 12, 12, 16, 13, 19, 27, 14], [level_colour(lane["level"]) for lane in lanes],
        ),
        para("Trip times include a 20 minute break every 5 hours. Traffic, tolls and loading time are not modelled.", SMALL),
    ]
    return render("Freight corridor weather status", story)


KIND = {"port": "Port", "airport": "Airport", "hub": "Hub"}


def facilities_report(board: dict[str, Any], heading: str = "Ports, cargo airports and logistics hubs") -> bytes:
    s = board["summary"]
    sites = board["sites"]
    dates = [d["date"] for d in sites[0]["days"]] if sites else []
    day_names = [datetime.fromisoformat(d).strftime("%a %d") for d in dates]

    def chip(day: dict[str, Any]) -> Paragraph:
        shade = LEVEL[day["level"]].hexval()[2:]
        text = day["status"] if day["level"] else "Normal"
        extra = f"<br/>{day['lost_hours']} h lost" if day["lost_hours"] else (f"<br/>{day['slow_hours']} h slow" if day["slow_hours"] else "")
        return Paragraph(f'<font color="#{shade}"><b>{escape(text)}</b></font>{extra}', CELL)

    story: list[Flowable] = [
        para("Facility operations outlook", H1),
        para(f"{heading}: five-day outlook for {s['total']} sites", SUB),
        facts([("Disruption likely, next 2 days", f"{s['disrupted']} of {s['total']}"), ("On watch", str(s["watch"])), ("Normal", str(s["normal"]))]),
        para("Outlook by site, worst first", H2),
        table(
            ["Site", "Type", "Now"] + day_names,
            [[
                Paragraph(f"<b>{escape(clean(site['name']))}</b>" + (f"<br/>{escape(clean(site['area']))}" if site.get("area") else ""), CELL), KIND[site["kind"]],
                f"{site['now']['label']}, {site['now']['temp']:.0f} C" if site["now"].get("temp") is not None else site["now"]["label"],
                *[chip(day) for day in site["days"]],
            ] for site in sites],
            [30, 9, 17] + [11] * len(day_names), [LEVEL[site["level"]] for site in sites],
        ),
    ]
    affected = [site for site in sites if site["level"] >= 1]
    if affected:
        for n, site in enumerate(affected):
            block: list[Flowable] = [para("Sites needing attention", H2)] if n == 0 else []
            block.append(para(f"{site['name']} ({KIND[site['kind']]}): {site['status']}", H3))
            lines = []
            if site.get("cyclone"):
                lines.append(f"Cyclone {site['cyclone'].get('name') or 'system'} passes within {site['cyclone']['closest_km']} km.")
            lines += [f"Official warning: {w['event']} ({w['severity']}), {w.get('issuer') or ''}, until {stamp(w.get('expires'))} IST." for w in site["warnings"]]
            for day in site["days"]:
                if day["level"]:
                    detail = "; ".join(day["reasons"]) or "conditions near operating limits"
                    detail = detail[0].upper() + detail[1:]
                    lines.append(f"{datetime.fromisoformat(day['date']).strftime('%a %d %b')}: {day['status']}, {day['lost_hours']} h lost and {day['slow_hours']} h slow. {detail}. Rain {day['rain_mm']:g} mm, gusts {day['gust_max']} km/h" + (f", waves {day['wave_max']} m" if day.get("wave_max") is not None else "") + ".")
            block += bullets(lines)
            story.append(KeepTogether(block))
    story.append(para("Operating limits used", H2))
    story += bullets(list(board["rules"].values()))
    return render("Facility operations outlook", story)
