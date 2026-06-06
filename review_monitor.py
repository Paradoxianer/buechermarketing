"""
review_monitor.py v3.0 (AI Scoring)
✅ Amazon + LovelyBooks + Web
✅ AI-basierter Relevanzscore (0–100)
✅ nur Treffer >= 75 werden übernommen
✅ kompatibel mit telegram_controller
"""

import re
import time
import requests
import traceback
from datetime import datetime
from ddgs import DDGS
from urllib.parse import urlparse

import utils_system as utils

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen3:8b"

MIN_SCORE = 75

REVIEWS_TAB = "Rezension"
LOG_TAB = "Logbuch"


# -----------------------------
# LOGGING
# -----------------------------

def log(level, message):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level}] {message}")
    try:
        utils.write_to_sheet(LOG_TAB, [[ts, "review_monitor.py", level, message]])
    except:
        pass


# -----------------------------
# TELEGRAM
# -----------------------------

def send_telegram(msg):
    try:
        utils.send_telegram(msg)
    except Exception as e:
        log("WARNUNG", f"Telegram Fehler: {e}")


# -----------------------------
# LLM (OLLAMA)
# -----------------------------

def generate(prompt):
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False
        })
        return r.json().get("response", "")
    except Exception as e:
        log("WARNUNG", f"LLM Fehler: {e}")
        return ""


# -----------------------------
# BOOK DATA (inkl. Beschreibung!)
# -----------------------------

def get_book():
    books = utils.get_sheet_data("Books")

    if not books:
        return {}

    b = books[0]

    return {
        "titel": b.get("titel", ""),
        "autorin": b.get("autorin", ""),
        "beschreibung": b.get("beschreibung", ""),
        "genre": b.get("genre", ""),
        "amazon_link": b.get("amazon_link", ""),
        "lovelybooks_url": b.get("lovelybooks_url", "")
    }


# -----------------------------
# QUICK FILTER (Performance!)
# -----------------------------

def is_german(text):
    text = text.lower()

    german_words = ["und", "der", "die", "das", "nicht", "ein", "eine", "buch"]

    hits = sum(1 for w in german_words if w in text)
    return hits >= 2


def is_noise(text):
    noise = ["song", "lyrics", "spotify", "album", "musik"]
    t = text.lower()
    return any(n in t for n in noise)


# -----------------------------
# AI SCORE 🔥
# -----------------------------

def ai_score(book, text, link):
    prompt = f"""
Du bist ein Bewertungssystem für Buch-Referenzen.

BUCH:
Titel: {book.get("titel")}
Autor: {book.get("autorin")}
Genre: {book.get("genre")}
Beschreibung:
{book.get("beschreibung")}

TEXT:
{text}

Link:
{link}

AUFGABE:
Bewerte von 0 bis 100 wie wahrscheinlich es ist, dass dieser Text genau dieses Buch beschreibt.

WICHTIG:
- Sprache ist Deutsch
- Song/Film etc. = niedriger Score
- echte Rezension = hoher Score

ANTWORTE NUR JSON:

{{
 "score": 0-100,
 "reason": "kurz"
}}
"""

    raw = generate(prompt)

    try:
        json_text = re.search(r"\{.*\}", raw, re.DOTALL).group()
        import json
        return json.loads(json_text)
    except:
        return {"score": 0, "reason": "parse_error"}


# -----------------------------
# AMAZON
# -----------------------------

def get_amazon_review_url(url):
    match = re.search(r"/dp/([A-Z0-9]+)", str(url))
    if not match:
        return None
    return f"https://www.amazon.de/product-reviews/{match.group(1)}"


def fetch_amazon(book):
    url = get_amazon_review_url(book.get("amazon_link"))

    if not url:
        return []

    log("INFO", f"Amazon: {url}")

    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        html = r.text
    except:
        return []

    if "captcha" in html.lower():
        log("WARNUNG", "Amazon blockiert")
        return []

    reviews = []

    blocks = re.findall(r'data-hook="review-body".*?>(.*?)</span>', html, re.DOTALL)

    for t in blocks[:5]:
        clean = re.sub(r"<.*?>", "", t).strip()
        reviews.append({
            "source": "Amazon",
            "text": clean,
            "link": url
        })

    return reviews


# -----------------------------
# LOVELYBOOKS
# -----------------------------

def fetch_lovely(book):
    url = book.get("lovelybooks_url")

    if not url:
        return []

    log("INFO", f"LovelyBooks: {url}")

    try:
        html = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}).text
    except:
        return []

    reviews = []

    blocks = re.findall(r'<div class="user-content">(.*?)</div>', html, re.DOTALL)

    for t in blocks[:5]:
        clean = re.sub(r"<.*?>", "", t).strip()
        if len(clean) > 50:
            reviews.append({
                "source": "LovelyBooks",
                "text": clean,
                "link": url
            })

    return reviews


# -----------------------------
# WEB SEARCH
# -----------------------------

def search_web(book):
    ddgs = DDGS()

    title = book.get("titel")
    author = book.get("autorin")

    queries = [
        f'"{title}" "{author}" rezension',
        f'"{title}" "{author}" buch',
        f'"{title}" "{author}"'
    ]

    results = []

    for q in queries:
        log("INFO", f"Suche: {q}")

        try:
            for r in ddgs.text(q, max_results=5):
                text = r.get("body", "")
                link = r.get("href", "")

                if not text or not link:
                    continue

                # schnellfilter
                if not is_german(text):
                    continue

                if is_noise(text):
                    continue

                # AI entscheidung
                score_data = ai_score(book, text, link)

                score = score_data.get("score", 0)

                log("INFO", f"SCORE {score} → {text[:40]}")

                if score < MIN_SCORE:
                    continue

                results.append({
                    "source": urlparse(link).netloc,
                    "text": text,
                    "link": link,
                    "score": score,
                    "reason": score_data.get("reason", "")
                })

        except Exception as e:
            log("FEHLER", f"Search Fehler: {e}")

    return results


# -----------------------------
# SUMMARY
# -----------------------------

def summary(book, reviews):
    msg = f"📚 Review Monitor\n\n"
    msg += f"{book.get('titel')}\n"
    msg += f"Treffer: {len(reviews)}\n\n"

    for r in reviews[:5]:
        msg += f"• {r['source']} ({r.get('score', '')})\n"
        msg += f"{r['text'][:100]}...\n\n"

    return msg


# -----------------------------
# MAIN
# -----------------------------

def run():
    try:
        log("INFO", "🚀 Start Review Monitor AI")

        book = get_book()

        log("INFO", f"Buch: {book.get('titel')}")

        all_results = []

        # AMAZON
        amazon = fetch_amazon(book)
        all_results.extend(amazon)

        time.sleep(2)

        # LOVELYBOOKS
        lovely = fetch_lovely(book)
        all_results.extend(lovely)

        # WEB + AI
        web = search_web(book)
        all_results.extend(web)

        if not all_results:
            send_telegram("⚠️ Keine relevanten Rezensionen gefunden")
            return

        # dedupe
        seen = set()
        unique = []

        for r in all_results:
            if r["link"] in seen:
                continue
            seen.add(r["link"])
            unique.append(r)

        # speichern
        rows = []

        for i, r in enumerate(unique):
            rows.append([
                str(i+1),
                datetime.now().strftime("%Y-%m-%d"),
                r["source"],
                "Rezension",
                r["link"],
                r["text"],
                "",
                "Neu",
                r.get("score", ""),
                r.get("reason", "")
            ])

        utils.write_to_sheet(REVIEWS_TAB, rows)

        log("INFO", f"{len(rows)} gespeichert")

        send_telegram(summary(book, unique))

    except Exception as e:
        log("FEHLER", "KRITISCH")
        log("FEHLER", str(e))
        traceback.print_exc()


# -----------------------------
# START
# -----------------------------

if __name__ == "__main__":
    run()
