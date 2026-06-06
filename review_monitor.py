"""
review_monitor.py v2.5
Direkte Review-Erkennung (Amazon + LovelyBooks)
"""

import re
import time
import requests
from datetime import datetime

import utils_system as utils


# -----------------------------
# LOGGING
# -----------------------------

def log(msg):
    print(f"[{datetime.now()}] {msg}")


# -----------------------------
# AMAZON HELPERS
# -----------------------------

def get_amazon_review_url(url):
    if not url:
        return None

    match = re.search(r"/dp/([A-Z0-9]+)", url)
    if not match:
        return None

    asin = match.group(1)
    return f"https://www.amazon.de/product-reviews/{asin}"


# -----------------------------
# AMAZON SCRAPER
# -----------------------------

def fetch_amazon_reviews(book):
    url = book.get("amazon_link")

    review_url = get_amazon_review_url(url)
    if not review_url:
        log("⚠️ Keine gültige Amazon URL")
        return []

    log(f"🔍 Amazon Reviews: {review_url}")

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:
        r = requests.get(review_url, headers=headers)
        html = r.text
    except Exception as e:
        log(f"❌ Amazon Fehler: {e}")
        return []

    reviews = []

    review_blocks = re.findall(
        r'data-hook="review-body".*?>(.*?)</span>',
        html,
        re.DOTALL
    )

    ratings = re.findall(
        r'(\d,\d von 5 Sternen)',
        html
    )

    for i, text in enumerate(review_blocks[:10]):
        clean = re.sub(r"<.*?>", "", text).strip()

        if not clean:
            continue

        reviews.append({
            "source": "Amazon",
            "text": clean,
            "rating": ratings[i] if i < len(ratings) else "",
            "link": review_url
        })

    return reviews


# -----------------------------
# LOVELYBOOKS SCRAPER
# -----------------------------

def fetch_lovelybooks_reviews(book):
    url = book.get("lovelybooks_url")

    if not url:
        log("⚠️ Keine LovelyBooks URL")
        return []

    log(f"🔍 LovelyBooks: {url}")

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:
        r = requests.get(url, headers=headers)
        html = r.text
    except Exception as e:
        log(f"❌ LovelyBooks Fehler: {e}")
        return []

    reviews = []

    review_blocks = re.findall(
        r'<div class="user-content">(.*?)</div>',
        html,
        re.DOTALL
    )

    for text in review_blocks[:10]:
        clean = re.sub(r"<.*?>", "", text).strip()

        if len(clean) < 40:
            continue

        reviews.append({
            "source": "LovelyBooks",
            "text": clean,
            "rating": "",
            "link": url
        })

    return reviews


# -----------------------------
# MAIN PIPELINE
# -----------------------------

def run():
    try:
        log("🚀 Review Monitor gestartet")

        books = utils.get_sheet_data("Books")

        if not books:
            log("❌ Keine Buchdaten gefunden")
            return

        book = books[0]

        log(f"📘 Buch: {book.get('titel')}")

        all_reviews = []

        # ---------------------
        # AMAZON
        # ---------------------
        amazon_reviews = fetch_amazon_reviews(book)
        log(f"✅ Amazon Reviews gefunden: {len(amazon_reviews)}")
        all_reviews.extend(amazon_reviews)

        time.sleep(2)  # wichtig gegen Block

        # ---------------------
        # LOVELYBOOKS
        # ---------------------
        lovely_reviews = fetch_lovelybooks_reviews(book)
        log(f"✅ LovelyBooks Reviews gefunden: {len(lovely_reviews)}")
        all_reviews.extend(lovely_reviews)

        # ---------------------
        # SPEICHERN
        # ---------------------
        if not all_reviews:
            log("⚠️ Keine Reviews gefunden")
            return

        rows = []

        for i, r in enumerate(all_reviews):
            rows.append([
                str(i + 1),
                datetime.now().strftime("%Y-%m-%d"),
                r.get("source"),
                "Rezension",
                r.get("link"),
                r.get("text"),
                r.get("rating", ""),
                "Neu"
            ])

        utils.write_to_sheet("Rezension", rows)

        log(f"✅ {len(rows)} Reviews gespeichert")

    except Exception as e:
        log("🔥 KRITISCHER FEHLER")
        log(str(e))
        import traceback
        traceback.print_exc()


# -----------------------------
# START
# -----------------------------

if __name__ == "__main__":
    run()
