"""Original branded calendar cards for Telegram. No competitor assets are used."""
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, features

ROOT = Path(__file__).resolve().parent
FONTS = ROOT / "fonts"
PER_PAGE = 8
COUNTRY_CODES = {"USD": "US", "EUR": "EU", "GBP": "GB", "JPY": "JP", "AUD": "AU",
                 "CAD": "CA", "CHF": "CH", "NZD": "NZ", "CNY": "CN"}

def country_code(currency):
    return COUNTRY_CODES.get(currency, currency or "—")


def _font(size, bold=False):
    return ImageFont.truetype(str(FONTS / ("NotoSansArabic-Bold.ttf" if bold else "NotoSansArabic-Regular.ttf")), size)

def _latin(size, bold=False):
    return ImageFont.truetype(str(FONTS / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")), size)


def _fit(draw, text, font, width):
    text = str(text or "—").replace("\n", " ")
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…"


def render_card(title, date_label, events, language="fa", page=0, total=None, placeholder=False, empty_lines=None):
    """Return a seekable PNG. Callers paginate so every event remains accessible."""
    if not features.check("raqm"):
        raise RuntimeError("Pillow must be built with RAQM for Persian text")
    total = len(events) if total is None else total
    width = 1100
    height = 485 + max(2 if empty_lines and not events else 1, len(events)) * 75 + 105
    img = Image.new("RGB", (width, height), "#0a1423")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((18, 18, width - 18, height - 18), 36, fill="#101e31", outline="#30465d", width=2)
    d.rounded_rectangle((42, 40, width - 42, 156), 26, fill="#152b41")
    logo = Image.open(ROOT / "logo.jpg").convert("RGB")
    logo.thumbnail((90, 90))
    img.paste(logo, (62, 53))
    d.text((175, 58), "@ForexFactoryN_Bot", font=_latin(28, True), fill="#7eddd1")
    d.text((175, 105), "ECONOMIC CALENDAR", font=_latin(18), fill="#a9c0ce")
    rtl = language == "fa"
    x = width - 65 if rtl else 65
    anchor = "ra" if rtl else "la"
    direction = "rtl" if rtl else "ltr"
    d.text((x, 178), title, font=_font(37, True) if rtl else _latin(37, True), fill="#f4f9fa", anchor=anchor, direction=direction)
    for i, line in enumerate(date_label.split("\n")[:2]):
        d.text((x, 240 + i * 33), line, font=_font(21) if rtl else _latin(21),
               fill="#a8c2ce", anchor=anchor, direction=direction)
    d.rounded_rectangle((42, 318, width-42, 406), 20, fill="#1c3448")
    counts = {name: sum(1 for e in events if e.get("Impact") == name) for name in ("High", "Medium", "Low")}
    label = ("نمایش این صفحه" if rtl else "THIS PAGE")
    d.text((65, 337), label, font=_font(20) if rtl else _latin(20), fill="#b9cbd2", direction=direction)
    for i, (name, color) in enumerate((("High", "#f07978"), ("Medium", "#f6c36d"), ("Low", "#86b7c1"))):
        d.ellipse((435+i*190, 350, 451+i*190, 366), fill=color)
        d.text((463+i*190, 333), f"{name.upper()}  {counts[name]}", font=_latin(20, True), fill="#eaf5f6")
    if events:
        for i, ev in enumerate(events):
            y = 427 + i*75
            color = {"High": "#f07978", "Medium": "#f6c36d", "Low": "#86b7c1"}.get(ev.get("Impact"), "#90a3ad")
            d.rounded_rectangle((42, y, width-42, y+65), 14, fill="#22394a" if i % 2 == 0 else "#1a3040")
            d.rounded_rectangle((42, y, 49, y+65), 3, fill=color)
            d.text((62, y+13), _fit(d, ev.get("Time"), _latin(20, True), 95), font=_latin(20, True), fill="#ecf7f6")
            d.text((158, y+13), _fit(d, country_code(ev.get("Currency")), _latin(20, True), 75), font=_latin(20, True), fill="#7eddd1")
            event = _fit(d, ev.get("Event"), _latin(19, True), 480)
            d.text((245, y+12), event, font=_latin(19, True), fill="#f2f6f5")
            date = _fit(d, ev.get("Date"), _latin(15), 180)
            d.text((245, y+40), date, font=_latin(15), fill="#99b3c0")
            val = f"F {str(ev.get('Forecast') or '—')}  P {str(ev.get('Previous') or '—')}"
            d.text((1030, y+15), _fit(d, val, _latin(16), 285), anchor="ra", font=_latin(16), fill="#d5e3e7")
    else:
        lines = empty_lines or [("یک روز را انتخاب کن" if rtl else "Choose a day") if placeholder
                                else ("خبری ثبت نشده است" if rtl else "No events found")]
        font = _font(21) if rtl else _latin(21)
        y = 435
        for line in lines:
            words = line.split()
            chunks, current = [], ""
            for word in words:
                candidate = (current + " " + word).strip()
                if current and d.textlength(candidate, font=font, direction=direction) > 950:
                    chunks.append(current)
                    current = word
                else:
                    current = candidate
            chunks.append(current)
            for chunk in chunks:
                d.text((width//2, y), chunk, font=font, fill="#b9d1d7", anchor="ma", direction=direction)
                y += 33
    d.line((55, height-87, width-55, height-87), fill="#345368", width=2)
    footer = ("ساعت‌ها به وقت نیویورک   تقویم اقتصادی" if rtl else "NEW YORK TIME  •  ECONOMIC CALENDAR")
    d.text((width//2, height-75), footer, font=_font(18) if rtl else _latin(18), fill="#9bb6c2", anchor="ma", direction=direction)
    d.text((width//2, height-43), f"@ForexFactoryN_Bot   •   {page+1} / {max(1, (total+PER_PAGE-1)//PER_PAGE)}",
           font=_latin(17, True), fill="#65d3c8", anchor="ma")
    out = BytesIO()
    out.name = "calendar.png"
    img.save(out, "PNG", optimize=True)
    out.seek(0)
    return out
