"""
pitch_generator.py — Buchmarketing Agentur
═══════════════════════════════════════════════════════════════
Erzeugt individuelle Pitch-Entwürfe auf Basis der Kontakte in
Google Sheets und schreibt die Ergebnisse in Kampagnen_Tracking.

Ziele:
- KEIN geprüfte_kontakte.json mehr
- KEIN kampagnen_status.json mehr
- Rohdaten → Kampagnen_Tracking
- LLM-generierte Betreffzeile + Pitch-Text
- Telegram-Zusammenfassung am Ende

Starten:
    python pitch_generator.py
═══════════════════════════════════════════════════════════════
"""

import json
import re
from datetime import datetime

from langchain_ollama import OllamaLLM

import utils_system as utils


# ─────────────────────────────────────────────────────────────
# KONFIGURATION
# ─────────────────────────────────────────────────────────────

RAW_TAB = "Rohdaten"
TRACKING_TAB = "Kampagnen_Tracking"
GENERAL_TAB = "Allgemeines"
CONFIG_TAB = "Konfiguration"
LOG_TAB = "Logbuch"

DEFAULT_MODEL = "llama3:8b"
DEFAULT_TEMP = 0.7
ELIGIBLE_RAW_STATUSES = {"Top-Treffer", "Manuell prüfen"}
SKIP_TRACKING_STATUSES = {
    "Entwurf",
    "Freigabe_ausstehend",
    "Freigegeben",
    "Gesendet",
    "Geöffnet",
    "Reagiert_positiv",
    "Reagiert_negativ",
    "Abgelehnt",
}


# ─────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────

def log(level: str, message: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{level}] {ts} — {message}", flush=True)
    try:
        utils.write_to_sheet(LOG_TAB, [[ts, "pitch_generator.py", level, message]])
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


def build_llm():
    model = get_config_value("ollama_model", DEFAULT_MODEL)
    temp_raw = get_config_value("ollama_temperature", str(DEFAULT_TEMP))
    try:
        temperature = float(temp_raw)
    except:
        temperature = DEFAULT_TEMP
    return OllamaLLM(model=model, temperature=temperature)


def get_raw_contacts():
    try:
        return utils.get_sheet_data(RAW_TAB)
    except Exception as e:
        log("FEHLER", f"Rohdaten konnten nicht geladen werden: {e}")
        return []


def get_existing_tracking_rows():
    try:
        return utils.get_sheet_data(TRACKING_TAB)
    except Exception as e:
        log("WARNUNG", f"Kampagnen_Tracking konnte nicht geladen werden: {e}")
        return []


def build_existing_tracking_keys():
    keys = set()
    rows = get_existing_tracking_rows()
    for row in rows:
        status = str(row.get("Status", "")).strip()
        if status and status not in SKIP_TRACKING_STATUSES:
            continue

        typ = str(row.get("Typ", "")).strip().lower()
        medium = str(row.get("Medium/Name", "")).strip().lower()
        email = str(row.get("E-Mail", "")).strip().lower()
        if medium or email:
            keys.add((typ, medium, email))
    return keys


def append_tracking_rows(rows):
    if not rows:
        return 0
    utils.write_to_sheet(TRACKING_TAB, rows)
    return len(rows)


def update_raw_status_by_key(typ: str, medium_name: str, email: str, new_status: str):
    try:
        client = utils.get_google_client()
        sheet = client.open_by_key(utils.SPREADSHEET_ID).worksheet(RAW_TAB)
        records = sheet.get_all_records()

        for idx, row in enumerate(records, start=2):
            row_typ = str(row.get("Typ", "")).strip().lower()
            row_medium = str(row.get("Medium/Name", "")).strip().lower()
            row_email = str(row.get("E-Mail", "")).strip().lower()

            if row_typ == typ.lower() and row_medium == medium_name.lower() and row_email == email.lower():
                sheet.update_cell(idx, 9, new_status)
                return True
    except Exception as e:
        log("WARNUNG", f"Rohdaten-Status konnte nicht aktualisiert werden ({medium_name}): {e}")
    return False


# ─────────────────────────────────────────────────────────────
# SELEKTION / KLASSIFIKATION
# ─────────────────────────────────────────────────────────────

def normalize_contact(row: dict):
    return {
        "typ": str(row.get("Typ", "")).strip() or "Unbekannt",
        "medium": str(row.get("Medium/Name", "")).strip() or "Unbekannt",
        "url": str(row.get("URL", "")).strip(),
        "beschreibung": str(row.get("Beschreibung", "")).strip(),
        "email": str(row.get("E-Mail", "")).strip(),
        "telefon": str(row.get("Telefon", "")).strip(),
        "ansprechpartner": str(row.get("Ansprechpartner", "")).strip() or "Unbekannt",
        "score": str(row.get("Score", "")).strip(),
        "status": str(row.get("Status", "")).strip(),
    }


def infer_outreach_style(typ: str, medium: str, beschreibung: str):
    text = " ".join([typ, medium, beschreibung]).lower()

    presse_keywords = [
        "presse", "magazin", "zeitung", "redaktion", "feuilleton",
        "radio", "podcast", "journal", "medien", "portal"
    ]
    blogger_keywords = [
        "blog", "bookstagram", "influencer", "instagram", "booktok",
        "rezension", "community", "booktube"
    ]
    christlich_keywords = [
        "christlich", "kirche", "glaube", "jesus", "evangelisch", "katholisch"
    ]

    if any(k in text for k in blogger_keywords):
        return "creator"
    if any(k in text for k in christlich_keywords):
        return "christlich"
    if any(k in text for k in presse_keywords):
        return "presse"
    return "allgemein"


def select_contacts_for_pitching():
    raw_rows = get_raw_contacts()
    existing_keys = build_existing_tracking_keys()

    selected = []
    for row in raw_rows:
        normalized = normalize_contact(row)
        if normalized["status"] not in ELIGIBLE_RAW_STATUSES:
            continue
        if not normalized["email"] or normalized["email"] == "Manuell suchen":
            continue

        dedupe_key = (
            normalized["typ"].lower(),
            normalized["medium"].lower(),
            normalized["email"].lower(),
        )
        if dedupe_key in existing_keys:
            continue

        normalized["outreach_style"] = infer_outreach_style(
            normalized["typ"],
            normalized["medium"],
            normalized["beschreibung"],
        )
        selected.append(normalized)
        existing_keys.add(dedupe_key)

    return selected


# ─────────────────────────────────────────────────────────────
# PROMPTING
# ─────────────────────────────────────────────────────────────

def build_style_rules(outreach_style: str, ansprechpartner: str):
    unknown = ansprechpartner.lower() == "unbekannt"

    if outreach_style == "presse":
        anrede = "Sehr geehrte Damen und Herren," if unknown else f"Guten Tag {ansprechpartner},"
        rules = [
            "Nutze ein professionelles, höfliches 'Sie'.",
            "Betone klar den journalistischen oder redaktionellen Mehrwert.",
            "Schlage Rezension, Interview, Kurzvorstellung oder Themenbezug vor.",
            "Halte den Ton sachlich, sympathisch und präzise.",
        ]
    elif outreach_style == "christlich":
        anrede = "Guten Tag," if unknown else f"Guten Tag {ansprechpartner},"
        rules = [
            "Nutze einen warmen, respektvollen, professionellen Ton.",
            "Betone Werte, junge Menschen, Orientierung, Identität, Familie oder Glaube nur wenn passend.",
            "Vermeide aufdringliche Frömmigkeit; schreibe anschlussfähig und offen.",
            "Schlage Rezension, Vorstellung, Interview oder redaktionelle Erwähnung vor.",
        ]
    elif outreach_style == "creator":
        anrede = "Hallo," if unknown else f"Hallo {ansprechpartner},"
        rules = [
            "Nutze einen freundlichen, persönlichen Ton auf Augenhöhe.",
            "Zeige knapp, warum der Kanal / Blog thematisch gut passt.",
            "Biete ein Rezensionsexemplar oder weitere Infos an.",
            "Schreibe locker, aber nicht anbiedernd.",
        ]
    else:
        anrede = "Guten Tag," if unknown else f"Guten Tag {ansprechpartner},"
        rules = [
            "Nutze einen freundlichen, professionellen Ton.",
            "Betone knapp, warum das Buch für dieses Medium interessant sein könnte.",
            "Biete Rezensionsexemplar, Infos oder Rückfragen an.",
        ]

    return anrede, rules


def generate_pitch(llm, kontakt: dict, buch: dict):
    anrede, style_rules = build_style_rules(kontakt["outreach_style"], kontakt["ansprechpartner"])
    rules_text = "\n".join([f"- {r}" for r in style_rules])

    prompt = f"""
Du bist eine professionelle PR-Agentin für Buchmarketing.

Schreibe eine überzeugende, individuelle Pitch-E-Mail für folgenden Kontakt.

BUCH:
- Titel: {buch['titel']}
- Autorin: {buch['autorin']}
- Genre: {buch['genre']}
- Beschreibung: {buch['beschreibung']}
- Zielsetzung: {buch['zielsetzung']}

KONTAKT:
- Medium/Name: {kontakt['medium']}
- Typ: {kontakt['typ']}
- Ansprechpartner: {kontakt['ansprechpartner']}
- URL: {kontakt['url']}
- Beschreibung/Recherche-Kontext: {kontakt['beschreibung']}
- Score: {kontakt['score']}

ANREDE:
{anrede}

STIL-REGELN:
{rules_text}

AUFGABE:
- Verfasse eine realistische E-Mail an genau diesen Kontakt.
- Die Mail soll kurz, klar, wertschätzend und gut versendbar sein.
- Sie soll nicht generisch wirken.
- Stelle das Buch knapp und interessant vor.
- Erkläre, warum gerade dieser Kontakt gut passen könnte.
- Biete ein Rezensionsexemplar oder weitere Informationen an.
- Verwende keine übertriebenen Werbeformulierungen.

ANTWORTE AUSSCHLIESSLICH ALS JSON:
{{
  "betreff": "Betreff der E-Mail",
  "pitch_text": "kompletter E-Mail-Text ohne Signatur"
}}
""".strip()

    raw = llm.invoke(prompt).strip()
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        raise ValueError("Kein JSON in LLM-Antwort")

    data = json.loads(match.group(0))
    betreff = str(data.get("betreff", "")).strip()
    pitch_text = str(data.get("pitch_text", "")).strip()

    if not betreff or not pitch_text:
        raise ValueError("LLM-Antwort enthält keinen Betreff oder Pitch-Text")

    return betreff, pitch_text


# ─────────────────────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────────────────────

def send_summary_to_telegram(created_count: int, skipped_count: int):
    try:
        utils.send_telegram(
            f"✍️ <b>Pitch-Generator beendet</b>\n\n"
            f"✅ Neue Entwürfe in <b>Kampagnen_Tracking</b>: {created_count}\n"
            f"⏭️ Übersprungen / bereits vorhanden: {skipped_count}",
            parse_mode="HTML"
        )
    except Exception as e:
        log("WARNUNG", f"Telegram-Zusammenfassung fehlgeschlagen: {e}")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    log("INFO", "Pitch Generator gestartet")

    buch = {
        "titel": get_general_value("buchtitel", "What is Love?"),
        "autorin": get_general_value("autorin_name", "Anni E. Lindner"),
        "genre": get_general_value("genre", "Jugendbuch"),
        "beschreibung": get_general_value("zielsetzung", ""),
        "zielsetzung": get_general_value("zielsetzung", "Bekanntheit steigern"),
    }

    contacts = select_contacts_for_pitching()
    if not contacts:
        log("INFO", "Keine passenden Kontakte für neue Pitch-Entwürfe gefunden")
        send_summary_to_telegram(created_count=0, skipped_count=0)
        return

    llm = build_llm()
    created_rows = []
    created_count = 0
    skipped_count = 0

    for index, kontakt in enumerate(contacts, start=1):
        try:
            betreff, pitch_text = generate_pitch(llm, kontakt, buch)
        except Exception as e:
            skipped_count += 1
            log("WARNUNG", f"Pitch konnte nicht erzeugt werden für {kontakt['medium']}: {e}")
            continue

        created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        pitch_id = f"pitch_{datetime.now().strftime('%d%H%M%S')}_{index:02d}"

        created_rows.append([
            pitch_id,
            kontakt["typ"],
            kontakt["medium"],
            kontakt["email"],
            kontakt["ansprechpartner"],
            betreff,
            pitch_text,
            created_at,
            "",
            "",
            "Entwurf",
            f"Quelle: Rohdaten | Score: {kontakt['score']} | URL: {kontakt['url']}",
        ])

        update_raw_status_by_key(
            typ=kontakt["typ"],
            medium_name=kontakt["medium"],
            email=kontakt["email"],
            new_status="Pitch erstellt",
        )
        created_count += 1
        log("OK", f"Pitch erstellt für {kontakt['medium']} ({kontakt['email']})")

    append_tracking_rows(created_rows)
    log("OK", f"Pitch Generator beendet — {created_count} neue Entwürfe")
    send_summary_to_telegram(created_count=created_count, skipped_count=skipped_count)


if __name__ == "__main__":
    main()
