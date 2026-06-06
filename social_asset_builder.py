"""
social_asset_builder.py — Buchmarketing Agentur
═══════════════════════════════════════════════════════════════
Erzeugt einfache, template-basierte Social-Media-Grafiken aus den
Einträgen der Social_Media_Queue.

Ziel:
- Zitatkarten, Hook-Cover und Story-Grafiken lokal rendern
- Buchcover aus Books.cover_datei und agentur_wissen/bilder verwenden
- fertige Bilder lokal speichern
- Bildpfade in Social_Media_Queue unter Bild_URLs eintragen
- nutzt aktuell gezielt das Kampagnenbuch 'What is Love?'
"""

import os
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

import utils_system as utils

LOG_TAB = "Logbuch"
QUEUE_TAB = "Social_Media_Queue"
BOOKS_TAB = "Books"
OUTPUT_DIR = "generated_assets"
ASSETS_DIR = "assets"
BOOK_IMAGES_DIR = os.path.join("agentur_wissen", "bilder")
DEFAULT_STATUS_FILTER = "Freigabe_ausstehend"
CAMPAIGN_BOOK_TITLE = "What is Love?"
CAMPAIGN_AUTHOR = "Anni E. Lindner"

INSTAGRAM_POST_SIZE = (1080, 1080)
STORY_SIZE = (1080, 1920)
CAROUSEL_SIZE = (1080, 1080)
BACKGROUND = (247, 241, 233)
ACCENT = (88, 58, 42)
TEXT = (35, 27, 20)
MUTED = (120, 96, 81)
WHITE = (255, 255, 255)


def log(level: str, message: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{level}] {ts} — {message}", flush=True)
    try:
        utils.write_to_sheet(LOG_TAB, [[ts, "social_asset_builder.py", level, message]])
    except Exception as e:
        print(f"[WARNUNG] Logbuch konnte nicht geschrieben werden: {e}", flush=True)


def get_rows(tab_name: str):
    try:
        return utils.get_sheet_data(tab_name)
    except Exception as e:
        log("WARNUNG", f"Tab konnte nicht geladen werden ({tab_name}): {e}")
        return []


def pick_value(row, candidates):
    for key in candidates:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def get_campaign_book_row():
    books = get_rows(BOOKS_TAB)
    for row in books:
        row_title = pick_value(row, ["titel", "Titel", "Buchtitel", "buchtitel"])
        row_cover = pick_value(row, ["cover_datei", "Cover_Datei", "cover", "Cover"])
        log("INFO", f"Books-Kandidat: titel='{row_title}' | cover='{row_cover}'")
        if row_title.strip() == CAMPAIGN_BOOK_TITLE:
            log("INFO", f"Kampagnenbuch gefunden: {CAMPAIGN_BOOK_TITLE}")
            return row

    log("WARNUNG", f"Kampagnenbuch nicht gefunden in Books: {CAMPAIGN_BOOK_TITLE}")
    return None


def ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def load_font(size: int, bold: bool = False):
    candidates = []
    if bold:
        candidates.extend([
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        ])
    else:
        candidates.extend([
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ])

    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size=size)

    return ImageFont.load_default()


def find_cover_image():
    book_row = get_campaign_book_row()
    if book_row:
        cover_file = pick_value(book_row, ["cover_datei", "Cover_Datei", "cover", "Cover"])
        log("INFO", f"Ermittelte cover_datei aus Books: '{cover_file}'")
        if cover_file:
            candidate = os.path.join(BOOK_IMAGES_DIR, cover_file)
            log("INFO", f"Prüfe Cover-Pfad: {candidate}")
            if os.path.exists(candidate):
                return candidate
            log("WARNUNG", f"cover_datei gefunden, Datei aber nicht vorhanden: {candidate}")

    fallback_candidates = [
        os.path.join(ASSETS_DIR, "book_cover.png"),
        os.path.join(ASSETS_DIR, "book_cover.jpg"),
        os.path.join(ASSETS_DIR, "book_cover.jpeg"),
    ]
    for path in fallback_candidates:
        log("INFO", f"Prüfe Fallback-Cover: {path}")
        if os.path.exists(path):
            return path
    return None


def open_and_fit_cover(size):
    cover_path = find_cover_image()
    if not cover_path:
        return None

    img = Image.open(cover_path).convert("RGB")
    img.thumbnail(size)
    return img


def clean_post_text(text: str):
    text = str(text or "").strip()
    if "[Bildidee:" in text:
        text = text.split("[Bildidee:", 1)[0].strip()
    return text


def get_hook_from_text(text: str):
    text = clean_post_text(text)
    first_line = text.splitlines()[0].strip() if text.splitlines() else text
    if len(first_line) > 80:
        first_line = first_line[:77].rstrip() + "..."
    return first_line


def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines = []
    current = ""

    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        width = bbox[2] - bbox[0]
        if width <= max_width or not current:
            current = test
        else:
            lines.append(current)
            current = word

    if current:
        lines.append(current)
    return lines


def extract_quote_or_excerpt(text: str, max_chars: int = 220):
    text = clean_post_text(text)
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    candidate = ""
    for p in paragraphs:
        if len(p) > 40:
            candidate = p
            break
    if not candidate:
        candidate = text
    if len(candidate) > max_chars:
        candidate = candidate[:max_chars].rstrip() + "..."
    return candidate


def draw_header(draw, title, author, width):
    title_font = load_font(42, bold=True)
    meta_font = load_font(24)
    draw.text((70, 60), title, fill=ACCENT, font=title_font)
    draw.text((70, 115), author, fill=MUTED, font=meta_font)
    draw.rounded_rectangle((70, 155, width - 70, 162), radius=4, fill=ACCENT)


def render_quote_card(post, title, author, size=INSTAGRAM_POST_SIZE):
    img = Image.new("RGB", size, BACKGROUND)
    draw = ImageDraw.Draw(img)
    draw_header(draw, title, author, size[0])

    quote = extract_quote_or_excerpt(post.get("Post_Text", ""), max_chars=240)
    quote_font = load_font(44, bold=True)
    small_font = load_font(28)
    lines = wrap_text(draw, f'“{quote}”', quote_font, size[0] - 160)

    y = 240
    for line in lines[:8]:
        draw.text((80, y), line, fill=TEXT, font=quote_font)
        y += 58

    draw.text((80, size[1] - 120), "Rezensionsinspirierter Post", fill=MUTED, font=small_font)

    cover = open_and_fit_cover((250, 350))
    if cover:
        img.paste(cover, (size[0] - cover.width - 70, size[1] - cover.height - 70))

    return img


def render_hook_cover(post, title, author, size=INSTAGRAM_POST_SIZE):
    img = Image.new("RGB", size, WHITE)
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, size[0], size[1]), fill=WHITE)
    draw.rounded_rectangle((50, 50, size[0] - 50, size[1] - 50), radius=30, fill=BACKGROUND, outline=ACCENT, width=4)
    draw_header(draw, title, author, size[0])

    hook = get_hook_from_text(post.get("Post_Text", ""))
    hook_font = load_font(52, bold=True)
    body_font = load_font(28)
    lines = wrap_text(draw, hook, hook_font, 720)

    y = 280
    for line in lines[:6]:
        draw.text((90, y), line, fill=TEXT, font=hook_font)
        y += 64

    body = extract_quote_or_excerpt(post.get("Post_Text", ""), max_chars=180)
    body_lines = wrap_text(draw, body, body_font, 720)
    y += 25
    for line in body_lines[:6]:
        draw.text((90, y), line, fill=MUTED, font=body_font)
        y += 38

    cover = open_and_fit_cover((300, 420))
    if cover:
        img.paste(cover, (size[0] - cover.width - 90, size[1] - cover.height - 90))

    return img


def render_story(post, title, author, size=STORY_SIZE):
    img = Image.new("RGB", size, BACKGROUND)
    draw = ImageDraw.Draw(img)
    draw_header(draw, title, author, size[0])

    hook = get_hook_from_text(post.get("Post_Text", ""))
    body = extract_quote_or_excerpt(post.get("Post_Text", ""), max_chars=280)
    hook_font = load_font(58, bold=True)
    body_font = load_font(34)

    y = 260
    for line in wrap_text(draw, hook, hook_font, size[0] - 140)[:6]:
        draw.text((70, y), line, fill=ACCENT, font=hook_font)
        y += 72

    y += 25
    for line in wrap_text(draw, body, body_font, size[0] - 140)[:10]:
        draw.text((70, y), line, fill=TEXT, font=body_font)
        y += 46

    draw.text((70, size[1] - 140), "Swipe / Mehr erfahren", fill=MUTED, font=load_font(28, bold=True))

    cover = open_and_fit_cover((380, 520))
    if cover:
        img.paste(cover, (size[0] - cover.width - 70, size[1] - cover.height - 90))

    return img


def render_asset(post, title, author):
    format_name = str(post.get("Format", "")).strip().lower()
    post_text = str(post.get("Post_Text", ""))

    if "story" in format_name:
        return render_story(post, title, author, size=STORY_SIZE)
    if "zitat" in post_text.lower() or "rezension" in post_text.lower():
        return render_quote_card(post, title, author, size=INSTAGRAM_POST_SIZE)
    if "carousel" in format_name:
        return render_hook_cover(post, title, author, size=CAROUSEL_SIZE)
    return render_hook_cover(post, title, author, size=INSTAGRAM_POST_SIZE)


def update_queue_image_path(row_id: str, image_path: str):
    try:
        client = utils.get_google_client()
        sheet = client.open_by_key(utils.SPREADSHEET_ID).worksheet(QUEUE_TAB)
        records = sheet.get_all_records()
        for idx, row in enumerate(records, start=2):
            if str(row.get("ID", "")).strip() == str(row_id).strip():
                sheet.update_cell(idx, 6, image_path)
                return True
    except Exception as e:
        log("WARNUNG", f"Queue konnte nicht aktualisiert werden ({row_id}): {e}")
    return False


def main():
    ensure_output_dir()
    title = CAMPAIGN_BOOK_TITLE
    author = CAMPAIGN_AUTHOR

    cover_path = find_cover_image()
    if cover_path:
        log("INFO", f"Verwendetes Cover: {cover_path}")
    else:
        log("WARNUNG", "Kein Cover gefunden — Assets werden ohne Buchcover gerendert")

    rows = get_rows(QUEUE_TAB)
    candidates = []
    for row in rows:
        status = str(row.get("Status", "")).strip()
        image_urls = str(row.get("Bild_URLs", "")).strip()
        if status == DEFAULT_STATUS_FILTER and not image_urls:
            candidates.append(row)

    if not candidates:
        log("INFO", "Keine Queue-Einträge ohne Bild gefunden")
        return

    built = []
    for row in candidates[:5]:
        row_id = str(row.get("ID", "")).strip()
        if not row_id:
            continue

        try:
            image = render_asset(row, title, author)
            file_name = f"{row_id}.png"
            output_path = os.path.join(OUTPUT_DIR, file_name)
            image.save(output_path, format="PNG")
            update_queue_image_path(row_id, output_path)
            built.append((row_id, output_path))
            log("OK", f"Asset erstellt: {output_path}")
        except Exception as e:
            log("FEHLER", f"Asset-Fehler für {row_id}: {e}")

    if built:
        lines = [
            "🖼️ <b>Social Assets erstellt</b>",
            "",
        ]
        for row_id, path in built:
            lines.append(f"• <b>{row_id}</b>: <code>{path}</code>")
        utils.send_telegram("\n".join(lines), parse_mode="HTML")


if __name__ == "__main__":
    main()
