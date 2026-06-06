"""
social_media_agent.py — Buchmarketing Agentur
═══════════════════════════════════════════════════════════════
Erzeugt konkrete Social-Media-Post-Entwürfe für die Kampagne und
schreibt sie in den Tab 'Social_Media_Queue'.

Ziel:
- 3 starke Vorschläge pro Lauf erzeugen
- 1 trendnaher Vorschlag, 2 normale Vorschläge
- Rezensionen, Trends und Social-History berücksichtigen
- Inhalte zuerst zur Freigabe in die Queue schreiben

Zielspalten in 'Social_Media_Queue':
ID | Erstellt_Am | Plattform | Format | Post_Text | Bild_URLs | Hashtags | Status | Freigabe_Am | Geplant_Fuer | Gepostet_Am | Post_ID_Extern

Starten:
    python social_media_agent.py
═══════════════════════════════════════════════════════════════
"""

import json
import re
from datetime import datetime

from langchain_ollama import OllamaLLM

import utils_system as utils

LOG_TAB = "Logbuch"
CONFIG_TAB = "Konfiguration"
GENERAL_TAB = "Allgemeines"
REVIEWS_TAB = "Rezension"
TRENDS_TAB = "Social_Trends"
QUEUE_TAB = "Social_Media_Queue"
HISTORY_TAB = "Social_History"

DEFAULT_MODEL = "qwen3:8b"
DEFAULT_TEMP = 0.7
DEFAULT_PLATFORM = "Instagram"
DEFAULT_STATUS = "Freigabe_ausstehend"
PLACEHOLDER_IMAGE = ""


def log(level: str, message: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{level}] {ts} — {message}", flush=True)
    try:
        utils.write_to_sheet(LOG_TAB, [[ts, "social_media_agent.py", level, message]])
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


def get_rows(tab_name: str):
    try:
        return utils.get_sheet_data(tab_name)
    except Exception as e:
        log("WARNUNG", f"Tab konnte nicht geladen werden ({tab_name}): {e}")
        return []


def build_llm():
    model = get_config_value("social_ollama_model", get_config_value("ollama_model", DEFAULT_MODEL))
    temp_raw = get_config_value("social_generation_temperature", str(DEFAULT_TEMP))
    try:
        temperature = float(temp_raw)
    except:
        temperature = DEFAULT_TEMP
    return OllamaLLM(model=model, temperature=temperature)


def get_recent_reviews(limit: int = 8):
    rows = get_rows(REVIEWS_TAB)
    items = []
    for row in rows:
        status = str(row.get("Status", "")).strip().lower()
        if status not in ("neu gefunden", "geprüft", "veröffentlicht", "für social verwenden"):
            continue
        items.append({
            "medium": str(row.get("Medium/Name", "")).strip(),
            "typ": str(row.get("Typ", "")).strip(),
            "zitat": str(row.get("Zitat", "")).strip(),
            "score": str(row.get("AI Score", "")).strip(),
            "begruendung": str(row.get("AI Begründung", "")).strip(),
        })
    return items[-limit:]


def get_recent_trends(limit: int = 8):
    rows = get_rows(TRENDS_TAB)
    items = []
    for row in rows[-limit:]:
        items.append({
            "plattform": str(row.get("Plattform", "")).strip(),
            "trend": str(row.get("Trend", "")).strip(),
            "quelle": str(row.get("Quelle", "")).strip(),
            "beschreibung": str(row.get("Kurzbeschreibung", "")).strip(),
            "relevanz": str(row.get("Relevanz", "")).strip(),
        })
    return items


def get_recent_social_history(limit: int = 12):
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


def get_recent_queue(limit: int = 10):
    rows = get_rows(QUEUE_TAB)
    items = []
    for row in rows[-limit:]:
        items.append({
            "plattform": str(row.get("Plattform", "")).strip(),
            "format": str(row.get("Format", "")).strip(),
            "post_text": str(row.get("Post_Text", "")).strip()[:220],
            "status": str(row.get("Status", "")).strip(),
        })
    return items


def select_planning_inputs():
    history = get_recent_social_history(limit=20)
    trend_ideas = [h for h in history if "Trend:" in str(h.get("notiz", "")) or str(h.get("typ", "")).lower() == "trend-post"]
    normal_ideas = [h for h in history if h not in trend_ideas]

    selected = []
    if trend_ideas:
        selected.append(trend_ideas[-1])
    selected.extend(normal_ideas[-2:])

    if len(selected) < 3:
        fallback = history[-3:]
        for item in fallback:
            if item not in selected:
                selected.append(item)
            if len(selected) == 3:
                break

    return selected[:3]


def build_prompt():
    autorin = get_general_value("autorin_name", "Unbekannt")
    buchtitel = get_general_value("buchtitel", get_general_value("book_name", "Unbekannt"))
    genre = get_general_value("genre", "Jugendbuch")
    zielsetzung = get_general_value("zielsetzung", "Bekanntheit steigern")
    website_url = get_general_value("website_url", "")

    reviews = get_recent_reviews()
    trends = get_recent_trends()
    history = get_recent_social_history()
    queue = get_recent_queue()
    selected_ideas = select_planning_inputs()

    return f"""
Du bist Senior Social Media Copywriter einer Buchmarketing-Agentur.

AUFGABE:
Erzeuge GENAU 3 veröffentlichungsreife Social-Media-Post-Entwürfe für die aktuelle Kampagne.

KAMPAGNENKONTEXT:
- Autorin: {autorin}
- Titel: {buchtitel}
- Genre: {genre}
- Zielsetzung: {zielsetzung}
- Website: {website_url}

REZENSIONEN / ERWÄHNUNGEN:
{json.dumps(reviews, ensure_ascii=False, indent=2)}

TRENDS:
{json.dumps(trends, ensure_ascii=False, indent=2)}

SOCIAL-HISTORY:
{json.dumps(history, ensure_ascii=False, indent=2)}

QUEUE:
{json.dumps(queue, ensure_ascii=False, indent=2)}

AUSGEWÄHLTE PLANUNGSIDEEN:
{json.dumps(selected_ideas, ensure_ascii=False, indent=2)}

WICHTIGE REGELN:
- Erzeuge genau 3 Posts.
- Mindestens 1 Post soll trendnah sein, wenn Trends vorhanden sind.
- Mindestens 2 Posts sollen evergreen / normal sein.
- Die 3 Posts sollen sich klar unterscheiden.
- Schreibe emotional, hochwertig, social-tauglich und nicht platt werblich.
- Die Texte sollen zu Instagram/Facebook passen.
- Du darfst intensiv nachdenken; Qualität ist wichtiger als Geschwindigkeit.
- Nutze Rezensionen sinnvoll, aber erfinde keine falschen Zitate.
- Verwende nur Informationen, die zum Buch und zur Kampagne passen.
- Liefere fertige Captions mit Hashtags.
- Nenne zusätzlich kurz die Bildidee.

ANTWORTFORMAT: NUR JSON
{{
  "posts": [
    {{
      "plattform": "Instagram",
      "format": "Feed",
      "post_text": "Kompletter Posttext / Caption",
      "bild_urls": "",
      "hashtags": "#whatislove #jugendbuch",
      "bildidee": "Nahaufnahme Buchcover + warmes Licht",
      "typ": "Trend-Post",
      "begruendung": "Warum dieser Post strategisch gut ist"
    }}
  ]
}}

WICHTIG:
- Genau 3 Posts.
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


def normalize_posts(data: dict):
    items = data.get("posts", [])
    if not isinstance(items, list):
        raise ValueError("Feld 'posts' ist keine Liste.")

    normalized = []
    seen = set()

    for item in items:
        if not isinstance(item, dict):
            continue

        plattform = str(item.get("plattform", DEFAULT_PLATFORM)).strip() or DEFAULT_PLATFORM
        format_name = str(item.get("format", "Feed")).strip() or "Feed"
        post_text = str(item.get("post_text", "")).strip()
        bild_urls = str(item.get("bild_urls", PLACEHOLDER_IMAGE)).strip()
        hashtags = str(item.get("hashtags", "")).strip()
        bildidee = str(item.get("bildidee", "")).strip()
        typ = str(item.get("typ", "Allgemein")).strip() or "Allgemein"
        begruendung = str(item.get("begruendung", "")).strip()

        if not post_text:
            continue

        dedupe_key = (plattform.lower(), format_name.lower(), post_text[:120].lower())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        normalized.append({
            "plattform": plattform,
            "format": format_name,
            "post_text": post_text,
            "bild_urls": bild_urls,
            "hashtags": hashtags,
            "bildidee": bildidee,
            "typ": typ,
            "begruendung": begruendung or "Strategisch sinnvoll für die laufende Social-Kampagne.",
        })

        if len(normalized) == 3:
            break

    if len(normalized) < 2:
        raise ValueError("Zu wenige brauchbare Posts aus der LLM-Antwort extrahiert.")

    return normalized


def append_queue_rows(posts):
    ts = datetime.now()
    rows = []
    for idx, post in enumerate(posts, start=1):
        full_text = post["post_text"].strip()
        if post.get("bildidee"):
            full_text += f"\n\n[Bildidee: {post['bildidee']}]"

        rows.append([
            f"social_{ts.strftime('%d%H%M%S')}_{idx:02d}",
            ts.strftime("%Y-%m-%d %H:%M:%S"),
            post["plattform"],
            post["format"],
            full_text,
            post.get("bild_urls", ""),
            post.get("hashtags", ""),
            DEFAULT_STATUS,
            "",
            "",
            "",
            "",
        ])

    if rows:
        utils.write_to_sheet(QUEUE_TAB, rows)
    return len(rows)


def append_history_rows(posts):
    ts = datetime.now()
    rows = []
    for idx, post in enumerate(posts, start=1):
        rows.append([
            f"socialdone_{ts.strftime('%d%H%M%S')}_{idx:02d}",
            ts.strftime("%Y-%m-%d %H:%M:%S"),
            post["plattform"],
            post["typ"],
            post["post_text"][:120],
            "Entwurf erstellt",
            f"Format: {post['format']} | Bildidee: {post['bildidee']}",
            post["begruendung"],
        ])

    if rows:
        utils.write_to_sheet(HISTORY_TAB, rows)


def send_summary_to_telegram(posts):
    lines = [
        "📱 <b>Neue Social-Posts erstellt</b>",
        "",
        f"Es wurden <b>{len(posts)}</b> Entwürfe in <b>Social_Media_Queue</b> abgelegt.",
        "",
    ]

    for idx, post in enumerate(posts, start=1):
        lines.append(f"<b>{idx}. {post['plattform']} / {post['format']}</b>")
        lines.append(f"📝 {post['post_text'][:180]}")
        if post.get("hashtags"):
            lines.append(f"🏷️ {post['hashtags'][:120]}")
        if post.get("bildidee"):
            lines.append(f"🖼️ {post['bildidee']}")
        lines.append("")

    lines.append("Status der neuen Einträge: <b>Freigabe_ausstehend</b>")

    try:
        utils.send_telegram("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        log("WARNUNG", f"Telegram-Zusammenfassung fehlgeschlagen: {e}")


def main():
    log("INFO", "Social Media Agent gestartet")
    try:
        llm = build_llm()
        prompt = build_prompt()
        log("INFO", "LLM erzeugt Social-Post-Entwürfe...")
        raw = llm.invoke(prompt).strip()
        data = parse_llm_json(raw)
        posts = normalize_posts(data)
        created = append_queue_rows(posts)
        append_history_rows(posts)
        log("OK", f"{created} Social-Posts erstellt")
        send_summary_to_telegram(posts)
    except Exception as e:
        log("FEHLER", f"Social-Agent-Fehler: {e}")
        try:
            utils.send_telegram(f"❌ <b>Social Media Agent Fehler</b>\n<code>{str(e)}</code>", parse_mode="HTML")
        except:
            pass
        raise


if __name__ == "__main__":
    main()
