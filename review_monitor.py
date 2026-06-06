import re
import requests
from datetime import datetime
from ddgs import DDGS
from urllib.parse import urlparse

import utils_system as utils

MODEL_NAME = "review_monitor_v2"

# -----------------------------
# KONFIG
# -----------------------------

MIN_SCORE = 3

NOISE_KEYWORDS = [
    "song", "lyrics", "musik", "album",
    "spotify", "dance track", "remix"
]

# -----------------------------
# HELPERS
# -----------------------------

def log(msg):
    print(f"[{datetime.now()}] {msg}")

def normalize(text):
    return (text or "").lower().strip()

# -----------------------------
# QUERY GENERATION (Tiered)
# -----------------------------

def build_queries(book):
    title = book.get("titel", "")
    author = book.get("autorin", "")

    base = f'"{title}" "{author}"'

    return [
        # Tier 1 (präzise)
        f'{base} rezension',
        f'{base} review',
        f'{base} buch',

        # Tier 2 (Plattform)
        f'{base} site:amazon.de',
        f'{base} site:lovelybooks.de',
        f'{base} site:goodreads.com',

        # Tier 3 (Social vorsichtig)
        f'{base} site:instagram.com',
        f'{base} site:youtube.com',

        # fallback
        f'"{title}" "{author}"'
    ]

# -----------------------------
# MATCHING
# -----------------------------

def is_noise(text):
    t = normalize(text)
    return any(n in t for n in NOISE_KEYWORDS)

def strong_match(link, snippet, book):
    isbn = normalize(book.get("isbn"))
    amazon = normalize(book.get("amazon_url"))
    lovely = normalize(book.get("lovelybooks_url"))

    link_l = normalize(link)
    snippet_l = normalize(snippet)

    if isbn and isbn in snippet_l:
        return True
    if amazon and amazon in link_l:
        return True
    if lovely and lovely in link_l:
        return True

    return False

def soft_match(book, snippet):
    title = normalize(book.get("titel"))
    author = normalize(book.get("autorin"))
    s = normalize(snippet)

    return title in s and author in s

def relevance_score(result, book):
    score = 0
    snippet = normalize(result.get("body", ""))

    if normalize(book.get("titel")) in snippet:
        score += 2
    if normalize(book.get("autorin")) in snippet:
        score += 3
    if "rezension" in snippet or "review" in snippet:
        score += 2
    if "buch" in snippet:
        score += 1
    if is_noise(snippet):
        score -= 5

    return score

# -----------------------------
# AMAZON DIRECT SCRAPE 🔥
# -----------------------------

def fetch_amazon_reviews(book):
    url = book.get("amazon_url", "")
    if not url:
        return []

    log("→ lade Amazon Rezensionen direkt")

    reviews = []

    try:
        headers = {
            "User-Agent": "Mozilla/5.0"
        }
        r = requests.get(url, headers=headers)
        html = r.text

        # sehr simple extraction (reicht oft schon!)
        matches = re.findall(r'(\d\.\d out of 5 stars)', html)

        for m in matches[:10]:
            reviews.append({
                "source": "Amazon",
                "rating": m,
                "text": "Amazon Bewertung gefunden",
                "link": url
            })

    except Exception as e:
        log(f"Amazon Fehler: {e}")

    return reviews

# -----------------------------
# DDGS SEARCH
# -----------------------------

def search_reviews(book):
    ddgs = DDGS()
    queries = build_queries(book)

    results = []
    seen_links = set()

    for q in queries:
        log(f"Query: {q}")

        for r in ddgs.text(q, max_results=8):
            link = r.get("href")
            snippet = r.get("body", "")

            if not link or link in seen_links:
                continue

            seen_links.add(link)

            # HARD MATCH
            if strong_match(link, snippet, book):
                results.append(r)
                continue

            # NOISE
            if is_noise(snippet):
                continue

            # SOFT MATCH
            if not soft_match(book, snippet):
                continue

            # SCORE
            if relevance_score(r, book) < MIN_SCORE:
                continue

            results.append(r)

    return results

# -----------------------------
# MAIN PIPELINE
# -----------------------------

def run_monitor():
    books = utils.get_sheet_data("Books")
    book = books[0]  # aktives Buch

    log(f"Starte Monitoring für: {book.get('titel')}")

    # 1. AMAZON DIREKT
    amazon_reviews = fetch_amazon_reviews(book)

    # 2. WEB SUCHE
    web_results = search_reviews(book)

    # 3. MERGE
    all_results = []

    for r in web_results:
        all_results.append({
            "link": r.get("href"),
            "text": r.get("body"),
            "source": urlparse(r.get("href")).netloc
        })

    for a in amazon_reviews:
        all_results.append(a)

    # 4. DEDUP
    unique = []
    seen = set()

    for r in all_results:
        key = r.get("link", "")
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)

    # 5. SAVE
    rows = []

    for i, r in enumerate(unique):
        rows.append([
            str(i+1),
            datetime.now().strftime("%Y-%m-%d"),
            r.get("source"),
            "Rezension",
            r.get("link"),
            r.get("text"),
            "",
            "Neu"
        ])

    utils.write_to_sheet("Rezension", rows)

    log(f"✅ {len(rows)} relevante Treffer gespeichert")
