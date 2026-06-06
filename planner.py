"""
planner.py — Buchmarketing Agentur
═══════════════════════════════════════════════════════════════
Plant die nächsten Recherche-Aufgaben mit lokalem Ollama-LLM
und schreibt sie direkt in Google Sheets.

Ziel:
- kampagnen_status.json nicht mehr verwenden
- neue Nischen/Zielgruppen automatisch ableiten
- Aufgaben sauber in den Tab 'Aufgaben' schreiben
- Fortschritt in 'Marketing_Plan' und 'Logbuch' dokumentieren

Starten:
    python planner.py

Optional:
    python planner.py "Christliche Medien"
    python planner.py "Jugendbuch Blogger Instagram"

Wenn ein Argument übergeben wird, dient es als Fokus/Schwerpunkt
für die nächste Planungsrunde.
═══════════════════════════════════════════════════════════════
"""

import json
import re
import sys
from datetime import datetime

from langchain_ollama import OllamaLLM

import utils_system as utils


# ─────────────────────────────────────────────────────────────
# KONFIGURATION
# ─────────────────────────────────────────────────────────────

DEFAULT_MODEL = "llama3:8b"
DEFAULT_TEMP = 0.3
PLAN_TAB = "Marketing_Plan"
TASK_TAB = "Aufgaben"
LOG_TAB = "Logbuch"
CONFIG_TAB = "Konfiguration"
GENERAL_TAB = "Allgemeines"
HISTORY_TAB = "Suchhistorie"


# ─────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────

def log(level: str, message: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{level}] {ts} — {message}", flush=True)
    try:
        utils.write_to_sheet(LOG_TAB, [[ts, "planner.py", level, message]])
    except Exception as e:
        print(f"[WARNUNG] Logbuch konnte nicht geschrieben werden: {e}", flush=True)


# ─────────────────────────────────────────────────────────────
# HELPERS: SHEETS
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


def get_existing_tasks():
    try:
        return utils.get_sheet_data(TASK_TAB)
    except Exception as e:
        log("WARNUNG", f"Aufgaben konnten nicht geladen werden: {e}")
        return []


def get_history_terms(limit: int = 20):
    """
    Holt die letzten Suchbegriffe aus Suchhistorie und Aufgaben,
    damit das LLM nicht immer dieselben Nischen produziert.
    """
    terms = []

    try:
        rows = utils.get_sheet_data(HISTORY_TAB)
        for row in rows[-limit:]:
            term = str(row.get("Suchbegriff", "")).strip()
            if term:
                terms.append(term)
    except Exception:
        pass

    try:
        tasks = utils.get_sheet_data(TASK_TAB)
        for row in tasks[-limit:]:
            q = str(row.get("Such_Query", "")).strip()
            if q:
                terms.append(q)
    except Exception:
        pass

    # Reihenfolge erhalten, Dubletten entfernen
    seen = set()
    unique = []
    for t in terms:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return unique[-limit:]


def find_active_plan_step_id(default="1"):
    """
    Sucht den ersten offenen/in_fortschritt-Schritt in Marketing_Plan.
    Fallback ist '1' (Recherche-Phase).
    """
    try:
        plan_rows = utils.get_sheet_data(PLAN_TAB)
        for row in plan_rows:
            status = str(row.get("Status", "")).strip().lower()
            if status in ("offen", "in_fortschritt"):
                return str(row.get("ID", default))
    except Exception as e:
        log("WARNUNG", f"Marketing_Plan konnte nicht geladen werden: {e}")
    return default


def set_plan_step_in_progress(plan_id: str):
    """
    Setzt einen Schritt in Marketing_Plan auf 'in_fortschritt'.
    Nutzt gspread direkt, da utils bislang append-orientiert ist.
    """
    try:
        client = utils.get_google_client()
        sheet = client.open_by_key(utils.SPREADSHEET_ID).worksheet(PLAN_TAB)
        records = sheet.get_all_records()

        for idx, row in enumerate(records, start=2):
            if str(row.get("ID", "")) == str(plan_id):
                current_status = str(row.get("Status", "")).strip().lower()
                if current_status != "in_fortschritt":
                    sheet.update_cell(idx, 4, "in_fortschritt")
                return True
    except Exception as e:
        log("WARNUNG", f"Marketing_Plan konnte nicht aktualisiert werden: {e}")
    return False


def create_tasks(task_items, plan_id: str):
    """
    Schreibt neue Aufgaben in den Aufgaben-Tab.
    task_items = [{zielgruppen_typ, such_query, begruendung}, ...]
    """
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    rows = []

    for index, item in enumerate(task_items, start=1):
        task_id = f"task_{now.strftime('%d%H%M')}_{index:02d}"
        zieltyp = item.get("zielgruppen_typ", "Unbekannte Nische").strip()
        query = item.get("such_query", "").strip()
        rows.append([
            task_id,
            str(plan_id),
            zieltyp,
            query,
            "bereit_fuer_recherche",
            today,
            "",
            ""
        ])

    if rows:
        utils.write_to_sheet(TASK_TAB, rows)
    return len(rows)


def write_history_entries(task_items):
    """Schreibt neue Suchbegriffe in Suchhistorie."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for item in task_items:
        rows.append([
            f"hist_{datetime.now().strftime('%d%H%M%S%f')}",
            ts,
            "planner.py",
            item.get("such_query", ""),
            "Allgemein",
            "",
            ""
        ])
    if rows:
        utils.write_to_sheet(HISTORY_TAB, rows)


# ─────────────────────────────────────────────────────────────
# HELPERS: LLM
# ─────────────────────────────────────────────────────────────

def build_llm():
    model = get_config_value("ollama_model", DEFAULT_MODEL)
    temperature_raw = get_config_value("ollama_temperature", str(DEFAULT_TEMP))
    try:
        temperature = float(temperature_raw)
    except:
        temperature = DEFAULT_TEMP
    return OllamaLLM(model=model, temperature=temperature)


def build_prompt(fokus: str = ""):
    autorin = get_general_value("autorin_name", "Unbekannt")
    buchtitel = get_general_value("buchtitel", "Unbekannt")
    genre = get_general_value("genre", "Jugendbuch")
    zielsetzung = get_general_value("zielsetzung", "Bekanntheit steigern")

    last_terms = get_history_terms(limit=20)
    offene_aufgaben = get_existing_tasks()
    offene_aufgaben = [
        a for a in offene_aufgaben
        if str(a.get("Status", "")).strip() in ("bereit_fuer_recherche", "in_recherche")
    ]

    offene_typen = [str(a.get("Zielgruppen_Typen", "")).strip() for a in offene_aufgaben if a.get("Zielgruppen_Typen")]
    offene_queries = [str(a.get("Such_Query", "")).strip() for a in offene_aufgaben if a.get("Such_Query")]

    fokus_text = fokus.strip() if fokus else "kein spezieller Fokus"

    return f"""
Du bist Campaign Strategist einer lokalen Buchmarketing-Agentur.

AUFGABE:
Plane die NÄCHSTEN 5 sinnvollen Recherche-Aufgaben für die Vermarktung eines Buches.

BUCHDATEN:
- Autorin: {autorin}
- Titel: {buchtitel}
- Genre: {genre}
- Zielsetzung: {zielsetzung}
- Zusätzlicher Fokus des Nutzers: {fokus_text}

WICHTIGE REGELN:
- Denke in realen Kontakt-Kategorien, z.B. Buchblogger, Bookstagram, Feuilleton, christliche Medien, Jugendmagazine, Podcasts, Radiosender, lokale Presse, Influencer, Pädagogik/Schule, Buchhandlungen, Bibliotheken.
- Liefere unterschiedliche Nischen, nicht fünf Varianten derselben Idee.
- Vermeide Wiederholungen gegenüber bereits verwendeten Suchbegriffen.
- Vermeide Themen, die aktuell schon offen in Bearbeitung sind.
- Suchqueries sollen kompakt sein, natürlich klingen und in DuckDuckGo/Google funktionieren.
- Suche bevorzugt deutschsprachige Kontakte für den DACH-Raum.
- Besonders passend für ein Jugendbuch / Coming-of-Age / Romantik denken.
- Wenn ein Nutzer-Fokus angegeben ist, soll MINDESTENS 1 Aufgabe direkt dazu passen.

BEREITS VERWENDETE SUCHBEGRIFFE:
{json.dumps(last_terms, ensure_ascii=False, indent=2)}

AKTUELL OFFENE ZIELGRUPPEN:
{json.dumps(offene_typen, ensure_ascii=False, indent=2)}

AKTUELL OFFENE QUERIES:
{json.dumps(offene_queries, ensure_ascii=False, indent=2)}

ANTWORTE AUSSCHLIESSLICH ALS JSON IM FORMAT:
{{
  "aufgaben": [
    {{
      "zielgruppen_typ": "Jugendbuch Blogger",
      "such_query": "jugendbuch blog rezension kontakt",
      "begruendung": "Warum diese Nische strategisch sinnvoll ist"
    }},
    {{
      "zielgruppen_typ": "Christliche Zeitschriften",
      "such_query": "christliche zeitschrift kultur buch kontakt",
      "begruendung": "Warum diese Nische strategisch sinnvoll ist"
    }}
  ]
}}

WICHTIG:
- Gib GENAU 5 Aufgaben zurück.
- Kein Markdown.
- Kein erklärender Text vor oder nach dem JSON.
""".strip()


def parse_llm_json(raw_text: str):
    """Extrahiert robust JSON aus möglichem Zusatztext des LLM."""
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


def normalize_tasks(data: dict):
    """
    Validiert und normalisiert LLM-Ausgabe.
    Gibt maximal 5 saubere Aufgaben zurück.
    """
    items = data.get("aufgaben", [])
    if not isinstance(items, list):
        raise ValueError("Feld 'aufgaben' ist keine Liste.")

    normalized = []
    seen_queries = set()

    for item in items:
        if not isinstance(item, dict):
            continue

        ziel = str(item.get("zielgruppen_typ", "")).strip()
        query = str(item.get("such_query", "")).strip()
        begr = str(item.get("begruendung", "")).strip()

        if not ziel or not query:
            continue

        qkey = query.lower()
        if qkey in seen_queries:
            continue
        seen_queries.add(qkey)

        normalized.append({
            "zielgruppen_typ": ziel,
            "such_query": query,
            "begruendung": begr or "Strategisch passend für die aktuelle Kampagne."
        })

        if len(normalized) == 5:
            break

    if len(normalized) < 3:
        raise ValueError("Zu wenige brauchbare Aufgaben aus der LLM-Antwort extrahiert.")

    return normalized


# ─────────────────────────────────────────────────────────────
# TELEGRAM REPORTING
# ─────────────────────────────────────────────────────────────

def send_summary_to_telegram(task_items, fokus: str = ""):
    lines = [
        "🧠 <b>Neue Kampagnen-Planung erstellt</b>",
        "",
    ]

    if fokus:
        lines.extend([
            f"<b>Fokus:</b> {fokus}",
            "",
        ])

    for idx, item in enumerate(task_items, start=1):
        lines.append(f"<b>{idx}. {item['zielgruppen_typ']}</b>")
        lines.append(f"🔎 {item['such_query']}")
        if item.get("begruendung"):
            lines.append(f"💡 {item['begruendung']}")
        lines.append("")

    lines.append("Die Aufgaben liegen jetzt im Tab <b>Aufgaben</b> bereit.")

    try:
        utils.send_telegram("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        log("WARNUNG", f"Telegram-Zusammenfassung fehlgeschlagen: {e}")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    fokus = " ".join(sys.argv[1:]).strip()
    if fokus:
        log("INFO", f"Planung mit Nutzer-Fokus gestartet: {fokus}")
    else:
        log("INFO", "Planung ohne expliziten Fokus gestartet")

    try:
        llm = build_llm()
        prompt = build_prompt(fokus)

        log("INFO", "LLM plant neue Recherche-Nischen...")
        raw = llm.invoke(prompt).strip()
        data = parse_llm_json(raw)
        tasks = normalize_tasks(data)

        plan_id = find_active_plan_step_id(default="1")
        set_plan_step_in_progress(plan_id)

        created_count = create_tasks(tasks, plan_id)
        write_history_entries(tasks)

        log("OK", f"{created_count} neue Aufgaben angelegt (Plan-ID {plan_id})")
        send_summary_to_telegram(tasks, fokus=fokus)

        print("\nNeue Aufgaben:")
        for idx, item in enumerate(tasks, start=1):
            print(f"{idx}. {item['zielgruppen_typ']} -> {item['such_query']}")

    except Exception as e:
        log("FEHLER", f"Planungsfehler: {e}")
        try:
            utils.send_telegram(
                f"❌ <b>Planner-Fehler</b>\n<code>{str(e)}</code>",
                parse_mode="HTML"
            )
        except:
            pass
        raise


if __name__ == "__main__":
    main()
