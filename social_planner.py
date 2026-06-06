"""
social_planner.py — Buchmarketing Agentur
═══════════════════════════════════════════════════════════════
Plant die nächsten sinnvollen Social-Media-Post-Ideen für die Kampagne
und schreibt strategische Vorschläge in den Tab 'Social_History'.

Ziel:
- bestehende Rezensionen, Trends, Queue und Buchbeschreibung berücksichtigen
- Wiederholungen vermeiden
- Content-Mix ausbalancieren
- 5 verwertbare Social-Ideen für den Agenten vorbereiten
- Instagram-first denken; Facebook meist mitnutzbar, nicht separat erzwingen

Starten:
    python social_planner.py
    python social_planner.py "Instagram Rezensionen"
═══════════════════════════════════════════════════════════════
"""

import json
import re
import sys
from datetime import datetime

from langchain_ollama import OllamaLLM

import utils_system as utils

LOG_TAB = "Logbuch"
CONFIG_TAB = "Konfiguration"
GENERAL_TAB = "Allgemeines"
BOOKS_TAB = "Books"
REVIEWS_TAB = "Rezension"
TRENDS_TAB = "Social_Trends"
QUEUE_TAB = "Social_Media_Queue"
HISTORY_TAB = "Social_History"

DEFAULT_MODEL = "qwen3:8b"
DEFAULT_TEMP = 0.35
LAST_PLAN_KEY = "letzter_social_plan_run"
DEFAULT_PLATFORM = "Instagram"


def log(level: str, message: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{level}] {ts} — {message}", flush=True)
    try:
        utils.write_to_sheet(LOG_TAB, [[ts, "social_planner.py", level, message]])
    except Exception as e:
        print(f"[WARNUNG] Logbuch konnte nicht geschrieben werden: {e}", flush=True)


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


def set_config_value(key: str, value: str):
    try:
        client = utils.get_google_client()
        sheet = client.open_by_key(utils.SPREADSHEET_ID).worksheet(CONFIG_TAB)
        cell = sheet.find(key, in_column=1)
        if cell:
            sheet.update_cell(cell.row, 2, str(value))
        else:
            sheet.append_row([key, str(value), "Automatisch gesetzt durch social_planner.py"])
    except Exception as e:
        log("WARNUNG", f"Konfiguration konnte nicht gespeichert werden ({key}): {e}")


def get_rows(tab_name: str):
    try:
        return utils.get_sheet_data(tab_name)
    except Exception as e:
        log("WARNUNG", f"Tab konnte nicht geladen werden ({tab_name}): {e}")
        return []


def build_llm():
    model = get_config_value("social_ollama_model", get_config_value("ollama_model", DEFAULT_MODEL))
    temp_raw = get_config_value("social_ollama_temperature", str(DEFAULT_TEMP))
    try:
        temperature = float(temp_raw)
    except:
        temperature = DEFAULT_TEMP
    return OllamaLLM(model=model, temperature=temperature)


def pick_value(row, candidates):
    for key in candidates:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def get_book_context():
    titel = get_general_value("buchtitel", get_general_value("book_name", "Unbekannt"))
    autorin = get_general_value("autorin_name", "Unbekannt")
    genre = get_general_value("genre", "Jugendbuch")
    zielsetzung = get_general_value("zielsetzung", "Bekanntheit steigern")
    website_url = get_general_value("website_url", "")

    beschreibung = ""
    books = get_rows(BOOKS_TAB)
    ziel_titel = titel.strip().lower()
    for row in books:
        row_titel = pick_value(row, ["titel", "Titel", "Buchtitel", "buchtitel"]).lower()
        if ziel_titel and row_titel == ziel_titel:
            beschreibung = pick_value(row, ["beschreibung", "Beschreibung", "Klappentext", "Kurzbeschreibung"])
            if beschreibung:
                break

    return {
        "autorin": autorin,
        "buchtitel": titel,
        "genre": genre,
        "zielsetzung": zielsetzung,
        "website_url": website_url,
        "beschreibung": beschreibung,
    }


def summarize_reviews(limit: int = 12):
    rows = get_rows(REVIEWS_TAB)
    filtered = []
    for row in rows:
        status = str(row.get("Status", "")).strip().lower()
        if status in ("neu gefunden", "geprüft", "veröffentlicht", "für social verwenden"):
            zitat = str(row.get("Zitat", "")).strip()
            if len(zitat) < 20:
                continue
            filtered.append({
                "medium": str(row.get("Medium/Name", "")).strip(),
                "typ": str(row.get("Typ", "")).strip(),
                "zitat": zitat,
                "score": str(row.get("AI Score", "")).strip(),
                "begruendung": str(row.get("AI Begründung", "")).strip(),
            })
    return filtered[-limit:]


def summarize_trends(limit: int = 10):
    rows = get_rows(TRENDS_TAB)
    items = []
    for row in rows[-limit:]:
        items.append({
            "plattform": str(row.get("Plattform", "")).strip(),
            "trend": str(row.get("Trend", "")).strip(),
            "quelle": str(row.get("Quelle", "")).strip(),
            "beschreibung": str(row.get("Kurzbeschreibung", "")).strip(),
            "relevanz": str(row.get("Relevanz", "")).strip(),
            "status": str(row.get("Status", "")).strip(),
        })
    return items


def summarize_queue(limit: int = 15):
    rows = get_rows(QUEUE_TAB)
    items = []
    for row in rows[-limit:]:
        items.append({
            "plattform": str(row.get("Plattform", "")).strip(),
            "format": str(row.get("Format", "")).strip(),
            "text": str(row.get("Post_Text", "")).strip()[:220],
            "status": str(row.get("Status", "")).strip(),
            "geplant": str(row.get("Geplant_Fuer", "")).strip(),
        })
    return items


def summarize_history(limit: int = 20):
    rows = get_rows(HISTORY_TAB)
    items = []
    for row in rows[-limit:]:
        items.append({
            "plattform": str(row.get("Plattform", "")).strip(),
            "typ": str(row.get("Typ", "")).strip(),
            "hook": str(row.get("Hook", "")).strip(),
            "status": str(row.get("Status", "")).strip(),
            "notiz": str(row.get("Notiz", "")).strip(),
            "performance": str(row.get("Performance", "")).strip(),
        })
    return items


def build_prompt(fokus: str = ""):
    book = get_book_context()
    reviews = summarize_reviews()
    trends = summarize_trends()
    queue = summarize_queue()
    history = summarize_history()
    fokus_text = fokus.strip() if fokus else "kein spezieller Fokus"

    return f"""
Du bist Social Media Strategist einer lokalen Buchmarketing-Agentur.

AUFGABE:
Plane die NÄCHSTEN 5 sinnvollen Social-Media-Post-Ideen für die aktuelle Buchkampagne.

KAMPAGNENKONTEXT:
- Autorin: {book['autorin']}
- Titel: {book['buchtitel']}
- Genre: {book['genre']}
- Zielsetzung: {book['zielsetzung']}
- Website: {book['website_url']}
- Buchbeschreibung: {book['beschreibung']}
- Nutzer-Fokus: {fokus_text}

AKTUELLE REZENSIONEN / ERWÄHNUNGEN:
{json.dumps(reviews, ensure_ascii=False, indent=2)}

AKTUELLE TRENDS:
{json.dumps(trends, ensure_ascii=False, indent=2)}

AKTUELLE QUEUE / ENTWÜRFE:
{json.dumps(queue, ensure_ascii=False, indent=2)}

BISHERIGE SOCIAL-HISTORY:
{json.dumps(history, ensure_ascii=False, indent=2)}

WICHTIGE REGELN:
- Denke Instagram-first. Facebook ist mitnutzbar, muss aber nicht separat geplant werden.
- Plane abwechslungsreich, aber BUCHNAH.
- Vermeide generische Hooks wie 'Die Macht des Lesens', 'Das Lesen verändert uns', 'Entdecken Sie das Buch'.
- Beziehe dich konkret auf Figuren, Konflikte, Gefühle, Fragen oder Spannungen aus der Buchbeschreibung.
- Mindestens 1 Idee soll trendnah sein, wenn Trends vorhanden sind.
- Mindestens 1 Idee soll eine Rezension / Erwähnung sinnvoll nutzen, wenn Rezensionen vorhanden sind.
- Denke in echten Formaten: Feed, Story, Carousel, Reel-Skript, Zitatkarte, Community-Frage.
- Schreibe NICHT die finalen Posts, sondern strategische Ideen.
- Wenn Nutzer-Fokus angegeben ist, soll mindestens 1 Idee direkt dazu passen.
- Die Ideen sollen emotional, konkret, modern und social-tauglich sein.
- Nutze das LLM gründlich und strategisch. Qualität ist wichtiger als Geschwindigkeit.

ANTWORTFORMAT: NUR JSON
{{
  "ideen": [
    {{
      "plattform": "Instagram",
      "format": "Carousel",
      "typ": "Rezensionszitat",
      "hook": "Wenn Liebe weh tut, bevor sie schön wird",
      "kernidee": "Mehrere Slides zeigen emotionale Spannungen oder Fragen aus dem Buch und verbinden sie mit einer echten Leserreaktion.",
      "quelle": "Rezension",
      "trendbezug": "Kein direkter Trend",
      "begruendung": "Warum diese Idee aktuell sinnvoll ist"
    }}
  ]
}}

WICHTIG:
- Gib GENAU 5 Ideen zurück.
- Plattform standardmäßig Instagram.
- Keine generischen Allgemeinplätze.
- Kein Markdown.
- Kein zusätzlicher Text.
""".strip()


def parse_llm_json(raw_text: str):
    raw_text = raw_text.strip()
    try:
        data = json.loads(raw_text)
        if isinstance(data, dict):
            return data
    except:
        pass

    match = re.search(r'\{.*\}', raw_text, re.DOTALL)
    if not match:
        raise ValueError("Kein JSON-Block in der LLM-Antwort gefunden.")
    return json.loads(match.group(0))


def normalize_ideas(data: dict):
    items = data.get("ideen", [])
    if not isinstance(items, list):
        raise ValueError("Feld 'ideen' ist keine Liste.")

    normalized = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue

        plattform = DEFAULT_PLATFORM
        format_name = str(item.get("format", "Feed")).strip() or "Feed"
        typ = str(item.get("typ", "Allgemein")).strip() or "Allgemein"
        hook = str(item.get("hook", "")).strip()
        kernidee = str(item.get("kernidee", "")).strip()
        quelle = str(item.get("quelle", "")).strip()
        trendbezug = str(item.get("trendbezug", "")).strip()
        begruendung = str(item.get("begruendung", "")).strip()

        if not hook or not kernidee:
            continue

        key = (format_name.lower(), hook.lower())
        if key in seen:
            continue
        seen.add(key)

        normalized.append({
            "plattform": plattform,
            "format": format_name,
            "typ": typ,
            "hook": hook,
            "kernidee": kernidee,
            "quelle": quelle,
            "trendbezug": trendbezug,
            "begruendung": begruendung or "Strategisch sinnvoll für die laufende Social-Kampagne.",
        })

        if len(normalized) == 5:
            break

    if len(normalized) < 3:
        raise ValueError("Zu wenige brauchbare Social-Ideen aus der LLM-Antwort extrahiert.")

    return normalized


def write_history_entries(ideas):
    ts = datetime.now()
    rows = []
    for idx, item in enumerate(ideas, start=1):
        rows.append([
            f"socialhist_{ts.strftime('%d%H%M%S')}_{idx:02d}",
            ts.strftime("%Y-%m-%d %H:%M:%S"),
            item["plattform"],
            item["typ"],
            item["hook"],
            "Geplant",
            f"Format: {item['format']} | Quelle: {item['quelle']} | Trend: {item['trendbezug']} | Idee: {item['kernidee']}",
            item["begruendung"],
        ])

    if rows:
        utils.write_to_sheet(HISTORY_TAB, rows)


def send_summary_to_telegram(ideas, fokus: str = ""):
    lines = ["📱 <b>Neue Social-Planung erstellt</b>", ""]
    if fokus:
        lines.extend([f"<b>Fokus:</b> {fokus}", ""])

    for idx, item in enumerate(ideas, start=1):
        lines.append(f"<b>{idx}. {item['format']}</b>")
        lines.append(f"🪝 {item['hook']}")
        lines.append(f"💡 {item['kernidee']}")
        if item.get("trendbezug"):
            lines.append(f"🔥 {item['trendbezug']}")
        lines.append("")

    lines.append("Die Ideen liegen jetzt in <b>Social_History</b> für den Social-Agenten bereit.")

    try:
        utils.send_telegram("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        log("WARNUNG", f"Telegram-Zusammenfassung fehlgeschlagen: {e}")


def main():
    fokus = " ".join(sys.argv[1:]).strip()
    if fokus:
        log("INFO", f"Social-Planung mit Fokus gestartet: {fokus}")
    else:
        log("INFO", "Social-Planung ohne expliziten Fokus gestartet")

    try:
        llm = build_llm()
        prompt = build_prompt(fokus)
        log("INFO", "LLM plant neue Social-Ideen...")
        raw = llm.invoke(prompt).strip()
        data = parse_llm_json(raw)
        ideas = normalize_ideas(data)
        write_history_entries(ideas)
        set_config_value(LAST_PLAN_KEY, datetime.now().isoformat(timespec="seconds"))
        log("OK", f"{len(ideas)} Social-Ideen geplant")
        send_summary_to_telegram(ideas, fokus=fokus)
    except Exception as e:
        log("FEHLER", f"Social-Planungsfehler: {e}")
        try:
            utils.send_telegram(f"❌ <b>Social Planner Fehler</b>\n<code>{str(e)}</code>", parse_mode="HTML")
        except:
            pass
        raise


if __name__ == "__main__":
    main()
