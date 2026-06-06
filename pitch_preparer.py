"""
pitch_preparer.py — Buchmarketing Agentur
═══════════════════════════════════════════════════════════════
Recherchiert offene Zielgruppen-Aufgaben aus Google Sheets,
scraped Suchtreffer, extrahiert Kontaktinfos und bewertet sie
mit lokalem Ollama-LLM.

Ziele:
- KEIN kampagnen_status.json mehr
- Google Sheets = Single Point of Truth
- Aufgaben aus Tab 'Aufgaben' lesen/schreiben
- Treffer in Tab 'Rohdaten' eintragen
- Konfiguration aus Tab 'Konfiguration' lesen
- Fortschritt & Zusammenfassung an Telegram senden

Starten:
    python pitch_preparer.py
═══════════════════════════════════════════════════════════════
"""

import json
import re
import time
import urllib.request
from datetime import datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from ddgs import DDGS
from langchain_ollama import OllamaLLM

import utils_system as utils


# ─────────────────────────────────────────────────────────────
# KONFIGURATION
# ─────────────────────────────────────────────────────────────

TASK_TAB = "Aufgaben"
RAW_TAB = "Rohdaten"
CONFIG_TAB = "Konfiguration"
GENERAL_TAB = "Allgemeines"
PLAN_TAB = "Marketing_Plan"
LOG_TAB = "Logbuch"
SEARCH_HISTORY_TAB = "Suchhistorie"

DEFAULT_MODEL = "llama3:8b"
DEFAULT_TEMP = 0.1
DEFAULT_MAX_RESULTS = 10
DEFAULT_MIN_SCORE = 40
DEFAULT_TOP_SCORE = 80
DEFAULT_TARGET_SIZE = 50

# Diese Seiten eher meiden, weil sie häufig paywall/aggregiert/irrelevant für Kontaktsuche sind
BLACKLIST_DOMAINS = {
    "faz.net",
    "stern.de",
    "spiegel.de",
    "zeit.de",
    "welt.de",
    "sueddeutsche.de",
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "tiktok.com",
    "linkedin.com",
    "pinterest.com",
}


# ─────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────

def log(level: str, message: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{level}] {ts} — {message}", flush=True)
    try:
        utils.write_to_sheet(LOG_TAB, [[ts, "pitch_preparer.py", level, message]])
    except Exception as e:
        print(f"[WARNUNG] Logbuch konnte nicht geschrieben werden: {e}", flush=True)


# ─────────────────────────────────────────────────────────────
# SHEETS / CONFIG HELPERS
# ─────────────────────────────────────────────────────────────

def get_general_value(key: str, default=""):
    try:
        value = utils.get_value_by_key(GENERAL_TAB, key)
        return value if value not in (None, "") else default
    except:
        return default


def get_config_value(key: str, default=""):
    try:
        value = utils.get_value_by_key(CONFIG_TAB, key)
        return value if value not in (None, "") else default
    except:
        return default


def get_existing_raw_urls():
    try:
        rows = utils.get_sheet_data(RAW_TAB)
        urls = set()
        for row in rows:
            url = str(row.get("URL", "")).strip()
            if url:
                urls.add(url.lower())
        return urls
    except Exception as e:
        log("WARNUNG", f"Rohdaten konnten nicht geladen werden: {e}")
        return set()


def get_open_tasks():
    try:
        tasks = utils.get_sheet_data(TASK_TAB)
        return [
            t for t in tasks
            if str(t.get("Status", "")).strip() == "bereit_fuer_recherche"
        ]
    except Exception as e:
        log("FEHLER", f"Aufgaben konnten nicht geladen werden: {e}")
        return []


def update_task_status(task_id: str, status: str, beendet_am: str = "", ergebnis_anzahl=None):
    try:
        client = utils.get_google_client()
        sheet = client.open_by_key(utils.SPREADSHEET_ID).worksheet(TASK_TAB)
        records = sheet.get_all_records()

        for idx, row in enumerate(records, start=2):
            if str(row.get("ID", "")) == str(task_id):
                sheet.update_cell(idx, 5, status)  # Status
                if beendet_am:
                    sheet.update_cell(idx, 7, beendet_am)  # Beendet_Am
                if ergebnis_anzahl is not None:
                    sheet.update_cell(idx, 8, ergebnis_anzahl)  # Ergebnis_Anzahl
                return True
    except Exception as e:
        log("WARNUNG", f"Task-Status konnte nicht aktualisiert werden ({task_id}): {e}")
    return False


def set_config_value(key: str, value: str, description: str = "Automatisch gesetzt"):
    try:
        client = utils.get_google_client()
        sheet = client.open_by_key(utils.SPREADSHEET_ID).worksheet(CONFIG_TAB)
        cell = sheet.find(key, in_column=1)
        if cell:
            sheet.update_cell(cell.row, 2, str(value))
        else:
            sheet.append_row([key, str(value), description])
        return True
    except Exception as e:
        log("WARNUNG", f"Konfiguration konnte nicht aktualisiert werden ({key}): {e}")
        return False


def maybe_complete_plan_step(plan_id: str, current_top_hits: int, target_size: int):
    if current_top_hits < target_size:
        return
    try:
        client = utils.get_google_client()
        sheet = client.open_by_key(utils.SPREADSHEET_ID).worksheet(PLAN_TAB)
        records = sheet.get_all_records()
        for idx, row in enumerate(records, start=2):
            if str(row.get("ID", "")) == str(plan_id):
                sheet.update_cell(idx, 4, "erledigt")
                if sheet.col_count >= 7:
                    sheet.update_cell(idx, 7, datetime.now().strftime("%Y-%m-%d"))
                log("OK", f"Marketing_Plan Schritt {plan_id} als erledigt markiert")
                return
    except Exception as e:
        log("WARNUNG", f"Marketing_Plan konnte nicht abgeschlossen werden: {e}")


def append_raw_contacts(contact_rows):
    if not contact_rows:
        return 0
    utils.write_to_sheet(RAW_TAB, contact_rows)
    return len(contact_rows)


def append_search_history(task_query: str, result_count: int, new_hits: int):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [[
        f"hist_{datetime.now().strftime('%d%H%M%S%f')}",
        ts,
        "pitch_preparer.py",
        task_query,
        "DDGS",
        result_count,
        new_hits,
    ]]
    try:
        utils.write_to_sheet(SEARCH_HISTORY_TAB, row)
    except Exception as e:
        log("WARNUNG", f"Suchhistorie konnte nicht geschrieben werden: {e}")


# ─────────────────────────────────────────────────────────────
# TEXT / SCRAPING HELPERS
# ─────────────────────────────────────────────────────────────

def extract_phone_numbers(text: str):
    pattern = r'(?:\+49|0)[1-9][0-9]{1,4}[ \-\/]*[0-9]{3,10}'
    matches = re.findall(pattern, text)
    cleaned = []
    for number in matches:
        normalized = number.strip()
        digits = re.sub(r'\D', '', normalized)
        if len(digits) >= 6:
            cleaned.append(normalized)
    return list(dict.fromkeys(cleaned))


def extract_emails(text: str):
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    sanitized = []
    blacklist = {"example.com", "domain.com", "email.com"}
    for email in emails:
        email = email.strip().rstrip('.,;:')
        if any(email.lower().endswith("@" + bad) for bad in blacklist):
            continue
        sanitized.append(email)
    return list(dict.fromkeys(sanitized))


def get_domain(url: str):
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc.replace("www.", "")
    except:
        return ""


def is_blacklisted(url: str):
    domain = get_domain(url)
    return any(domain == d or domain.endswith("." + d) for d in BLACKLIST_DOMAINS)


def scrape_website(url: str):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as response:
            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                return None
            soup = BeautifulSoup(response.read(), "html.parser")
            for s in soup(["script", "style", "noscript"]):
                s.extract()
            text = " ".join(soup.get_text(separator=" ").split())
            return text[:5000] if text else None
    except:
        return None


def build_llm():
    model = get_config_value("ollama_model", DEFAULT_MODEL)
    temp_raw = get_config_value("ollama_temperature", str(DEFAULT_TEMP))
    try:
        temperature = float(temp_raw)
    except:
        temperature = DEFAULT_TEMP
    return OllamaLLM(model=model, temperature=temperature)


def score_contact_with_llm(llm, genre: str, zielsetzung: str, typ: str, titel: str, url: str, text: str):
    prompt = f"""
Du bewertest Web-Treffer für eine Buchmarketing-Agentur.

KONTEXT:
- Buchgenre: {genre}
- Zielsetzung: {zielsetzung}
- Kontaktkategorie: {typ}
- Medium/Name: {titel}
- URL: {url}

WEBSEITEN-INHALT (AUSZUG):
{text[:3500]}

AUFGABE:
Bewerte von 0 bis 100, wie relevant dieser Kontakt für PR, Rezensionen,
Interviews, Blogger-Outreach oder Reichweitenaufbau für dieses Buch ist.

Achte auf:
- Passt die Zielgruppe zu Jugendbuch / Coming-of-Age / Romantik?
- Gibt es Hinweise auf Rezensionen, Bücher, Kultur, Feuilleton, Buchblog, Podcast, Magazin, Influencer?
- Wirkt die Seite wie ein echter erreichbarer Kontakt und nicht wie ein irrelevantes Portal?
- Gibt es Hinweise auf Kontaktmöglichkeit oder Ansprechpartner?

ANTWORTE NUR ALS JSON:
{{
  "score": 0,
  "begruendung": "kurze konkrete Einschätzung",
  "ansprechpartner": "Name oder Unbekannt"
}}
""".strip()

    raw = llm.invoke(prompt).strip()
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        raise ValueError("Kein JSON in LLM-Antwort")
    data = json.loads(match.group(0))
    score = int(data.get("score", 0))
    if score < 0:
        score = 0
    if score > 100:
        score = 100
    return {
        "score": score,
        "begruendung": str(data.get("begruendung", "")).strip(),
        "ansprechpartner": str(data.get("ansprechpartner", "Unbekannt")).strip() or "Unbekannt",
    }


# ─────────────────────────────────────────────────────────────
# TELEGRAM REPORTING
# ─────────────────────────────────────────────────────────────

def send_task_summary(task_name: str, query: str, added_count: int, top_count: int, skipped_count: int):
    message = (
        f"🔎 <b>Recherche abgeschlossen</b>\n\n"
        f"<b>Segment:</b> {task_name}\n"
        f"<b>Query:</b> <code>{query}</code>\n\n"
        f"✅ Neue Kontakte: {added_count}\n"
        f"⭐ Top-Treffer: {top_count}\n"
        f"⏭️ Übersprungen/Dubletten: {skipped_count}"
    )
    try:
        utils.send_telegram(message, parse_mode="HTML")
    except Exception as e:
        log("WARNUNG", f"Telegram-Task-Report fehlgeschlagen: {e}")


def send_final_summary(total_added: int, total_top_hits: int, current_top_hits: int, target_size: int):
    message = (
        f"📬 <b>Pitch Preparer beendet</b>\n\n"
        f"✅ Neue Kontakte insgesamt: {total_added}\n"
        f"⭐ Neue Top-Treffer in diesem Lauf: {total_top_hits}\n"
        f"📊 Aktueller Stand Top-Treffer: {current_top_hits} / {target_size}\n\n"
        f"Bitte im Tab <b>Rohdaten</b> prüfen und ggf. ergänzen."
    )
    try:
        utils.send_telegram(message, parse_mode="HTML")
    except Exception as e:
        log("WARNUNG", f"Telegram-Endreport fehlgeschlagen: {e}")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────��───────────

def main():
    log("INFO", "Pitch Preparer gestartet")

    genre = get_general_value("genre", "Jugendbuch / Coming-of-Age / Romantik")
    zielsetzung = get_general_value("zielsetzung", "Bekanntheit steigern")
    buchtitel = get_general_value("buchtitel", "What is Love?")

    max_results_raw = get_config_value("max_ddgs_results", str(DEFAULT_MAX_RESULTS))
    min_score_raw = get_config_value("min_score_kontakt", str(DEFAULT_MIN_SCORE))
    top_score_raw = get_config_value("min_score_top_treffer", str(DEFAULT_TOP_SCORE))
    target_size_raw = get_config_value("ziel_datenbank_groesse", str(DEFAULT_TARGET_SIZE))
    current_top_hits_raw = get_config_value("aktuelle_hochwertige_treffer", "0")

    try:
        max_results = int(max_results_raw)
    except:
        max_results = DEFAULT_MAX_RESULTS
    try:
        min_score = int(min_score_raw)
    except:
        min_score = DEFAULT_MIN_SCORE
    try:
        top_score = int(top_score_raw)
    except:
        top_score = DEFAULT_TOP_SCORE
    try:
        target_size = int(target_size_raw)
    except:
        target_size = DEFAULT_TARGET_SIZE
    try:
        current_top_hits = int(current_top_hits_raw)
    except:
        current_top_hits = 0

    open_tasks = get_open_tasks()
    if not open_tasks:
        log("INFO", "Keine offenen Recherche-Aufträge vorhanden")
        return

    existing_urls = get_existing_raw_urls()
    llm = build_llm()

    total_added = 0
    total_new_top_hits = 0

    for task in open_tasks:
        task_id = str(task.get("ID", "")).strip()
        plan_id = str(task.get("Plan_ID", "1")).strip() or "1"
        query = str(task.get("Such_Query", "")).strip()
        typ = str(task.get("Zielgruppen_Typen", "")).strip() or "Unbekannt"

        if not task_id or not query:
            log("WARNUNG", f"Überspringe fehlerhafte Aufgabe ohne ID/Query: {task}")
            continue

        update_task_status(task_id, "in_recherche")
        log("INFO", f"Starte Recherche für '{typ}' mit Query '{query}'")

        raw_results = []
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
                for result in results:
                    raw_results.append({
                        "typ": typ,
                        "titel": result.get("title", "Unbekannt"),
                        "url": result.get("href", ""),
                        "snippet": result.get("body", ""),
                    })
        except Exception as e:
            log("FEHLER", f"Suchfehler für '{query}': {e}")
            update_task_status(task_id, "fehler")
            continue

        new_rows = []
        skipped_count = 0
        task_top_hits = 0

        for result in raw_results:
            url = str(result.get("url", "")).strip()
            title = str(result.get("titel", "Unbekannt")).strip()
            snippet = str(result.get("snippet", "")).strip()

            if not url:
                skipped_count += 1
                continue
            if is_blacklisted(url):
                skipped_count += 1
                continue
            if url.lower() in existing_urls:
                skipped_count += 1
                continue

            text = scrape_website(url)
            if not text:
                skipped_count += 1
                continue

            emails = extract_emails(text)
            email = emails[0] if emails else "Manuell suchen"
            phones = extract_phone_numbers(text)
            phone = phones[0] if phones else "Nicht gefunden"

            try:
                scored = score_contact_with_llm(
                    llm=llm,
                    genre=genre,
                    zielsetzung=zielsetzung,
                    typ=typ,
                    titel=title,
                    url=url,
                    text=text,
                )
                score = int(scored["score"])
            except Exception as e:
                log("WARNUNG", f"LLM-Bewertung fehlgeschlagen für {url}: {e}")
                skipped_count += 1
                time.sleep(0.5)
                continue

            if score < min_score:
                skipped_count += 1
                time.sleep(0.5)
                continue

            status_text = "Top-Treffer" if score >= top_score else "Manuell prüfen"
            if score >= top_score:
                task_top_hits += 1
                total_new_top_hits += 1

            description = scored.get("begruendung") or snippet[:300] or "Relevanter Recherchetreffer"
            contact_name = scored.get("ansprechpartner", "Unbekannt")

            new_rows.append([
                typ,
                title,
                url,
                description,
                email,
                phone,
                contact_name,
                score,
                status_text,
                "",
            ])
            existing_urls.add(url.lower())
            time.sleep(0.8)

        added_count = append_raw_contacts(new_rows)
        total_added += added_count

        finished_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        update_task_status(task_id, "recherche_erledigt", beendet_am=finished_at, ergebnis_anzahl=added_count)
        append_search_history(query, result_count=len(raw_results), new_hits=added_count)

        log("OK", f"Recherche abgeschlossen: {typ} — {added_count} neue Kontakte, {task_top_hits} Top-Treffer")
        send_task_summary(typ, query, added_count, task_top_hits, skipped_count)

        current_top_hits += task_top_hits
        set_config_value("aktuelle_hochwertige_treffer", str(current_top_hits), "Automatisch hochgezählt von pitch_preparer.py")
        maybe_complete_plan_step(plan_id, current_top_hits, target_size)

    send_final_summary(
        total_added=total_added,
        total_top_hits=total_new_top_hits,
        current_top_hits=current_top_hits,
        target_size=target_size,
    )

    log("OK", f"Pitch Preparer beendet — {total_added} Kontakte, {total_new_top_hits} neue Top-Treffer für '{buchtitel}'")


if __name__ == "__main__":
    main()
