"""
mail_checker.py — Buchmarketing Agentur
═══════════════════════════════════════════════════════════════
Prüft den IMAP-Posteingang, erkennt neue ungelesene E-Mails,
klassifiziert deren Inhalt grob und aktualisiert Kampagnen_Tracking.

Ziele:
- neue E-Mails per IMAP abrufen
- Absender, Betreff, Datum, Text extrahieren
- Antworten grob klassifizieren
- passende Einträge in Kampagnen_Tracking markieren
- Telegram-Zusammenfassung senden

Erwartete .env-Werte:
- IMAP_HOST
- IMAP_PORT
- MAIL_USER
- MAIL_PASS

Starten:
    python mail_checker.py
═══════════════════════════════════════════════════════════════
"""

import email
import email.utils
import imaplib
import re
from datetime import datetime
from email.header import decode_header

from langchain_ollama import OllamaLLM

import utils_system as utils


# ─────────────────────────────────────────────────────────────
# KONFIGURATION
# ─────────────────────────────────────────────────────────────

TRACKING_TAB = "Kampagnen_Tracking"
LOG_TAB = "Logbuch"
CONFIG_TAB = "Konfiguration"
DEFAULT_MODEL = "llama3:8b"
DEFAULT_TEMP = 0.2
MAILBOX = "INBOX"
MAX_UNSEEN_MAILS = 20

STATUS_MAP = {
    "positiv": "Reagiert_positiv",
    "negativ": "Reagiert_negativ",
    "rueckfrage": "Rückfrage",
    "autoreply": "Autoreply",
    "irrelevant": "Irrelevant",
}


# ─────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────

def log(level: str, message: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{level}] {ts} — {message}", flush=True)
    try:
        utils.write_to_sheet(LOG_TAB, [[ts, "mail_checker.py", level, message]])
    except Exception as e:
        print(f"[WARNUNG] Logbuch konnte nicht geschrieben werden: {e}", flush=True)


# ─────────────────────────────────────────────────────────────
# CONFIG / LLM
# ─────────────────────────────────────────────────────────────

def get_config_value(key: str, default=""):
    try:
        value = utils.get_value_by_key(CONFIG_TAB, key)
        return value if value not in (None, "") else default
    except:
        return default


def build_llm():
    model = get_config_value("ollama_model", DEFAULT_MODEL)
    temp_raw = get_config_value("ollama_temperature_mail", str(DEFAULT_TEMP))
    try:
        temperature = float(temp_raw)
    except:
        temperature = DEFAULT_TEMP
    return OllamaLLM(model=model, temperature=temperature)


# ─────────────────────────────────────────────────────────────
# MAIL HELPERS
# ─────────────────────────────────────────────────────────────

def decode_mime(value):
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for part, encoding in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(encoding or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded).strip()


def extract_plain_text(msg):
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            if content_type == "text/plain" and "attachment" not in content_disposition.lower():
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace").strip()

        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/html":
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                html = payload.decode(charset, errors="replace")
                html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
                html = re.sub(r"<[^>]+>", " ", html)
                html = re.sub(r"\s+", " ", html)
                return html.strip()
        return ""

    payload = msg.get_payload(decode=True)
    if payload is None:
        return ""
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace").strip()


def normalize_body(text: str):
    text = text or ""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if stripped.startswith(">"):
            continue
        if re.match(r"^Am .+ schrieb .+:$", stripped):
            break
        if re.match(r"^On .+ wrote:$", stripped):
            break
        if stripped.startswith("-- "):
            break
        lines.append(stripped)
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def fetch_unseen_messages():
    host = getattr(utils, "IMAP_HOST", None)
    port = int(getattr(utils, "IMAP_PORT", 143) or 143)
    user = getattr(utils, "MAIL_USER", None)
    password = getattr(utils, "MAIL_PASS", None)

    if not host or not user or not password:
        raise RuntimeError("IMAP-Konfiguration unvollständig. Bitte IMAP_HOST, IMAP_PORT, MAIL_USER, MAIL_PASS prüfen.")

    mail = imaplib.IMAP4(host, port)
    mail.starttls()
    mail.login(user, password)
    mail.select(MAILBOX)

    status, data = mail.search(None, "UNSEEN")
    if status != "OK":
        mail.logout()
        return []

    message_ids = data[0].split()[-MAX_UNSEEN_MAILS:]
    messages = []

    for msg_id in message_ids:
        fetch_status, msg_data = mail.fetch(msg_id, "(RFC822)")
        if fetch_status != "OK":
            continue

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = decode_mime(msg.get("Subject", ""))
        from_raw = decode_mime(msg.get("From", ""))
        sender_name, sender_email = email.utils.parseaddr(from_raw)
        sender_name = sender_name.strip()
        sender_email = sender_email.strip().lower()
        date_raw = decode_mime(msg.get("Date", ""))
        body = normalize_body(extract_plain_text(msg))

        messages.append({
            "imap_id": msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id),
            "subject": subject,
            "from_name": sender_name,
            "from_email": sender_email,
            "date": date_raw,
            "body": body[:4000],
        })

    mail.logout()
    return messages


# ─────────────────────────────────────────────────────────────
# TRACKING HELPERS
# ─────────────────────────────────────────────────────────────

def get_tracking_rows():
    try:
        return utils.get_sheet_data(TRACKING_TAB)
    except Exception as e:
        log("FEHLER", f"Kampagnen_Tracking konnte nicht geladen werden: {e}")
        return []


def find_tracking_match(mail_item: dict, rows: list):
    sender_email = mail_item["from_email"].strip().lower()
    subject = mail_item["subject"].strip().lower()

    best_index = None
    best_score = -1

    for idx, row in enumerate(rows, start=2):
        row_email = str(row.get("E-Mail", "")).strip().lower()
        row_medium = str(row.get("Medium/Name", "")).strip().lower()
        row_betreff = str(row.get("Betreff", "")).strip().lower()

        score = 0
        if sender_email and row_email and sender_email == row_email:
            score += 10
        if subject and row_betreff and (subject == row_betreff or subject.replace("re:", "").strip() == row_betreff.replace("re:", "").strip()):
            score += 5
        if sender_email and row_medium and sender_email.split("@")[0] in row_medium:
            score += 2

        if score > best_score:
            best_score = score
            best_index = idx

    if best_score <= 0:
        return None
    return best_index


def update_tracking_row(row_index: int, status_text: str, summary: str, latest_message: str):
    try:
        client = utils.get_google_client()
        sheet = client.open_by_key(utils.SPREADSHEET_ID).worksheet(TRACKING_TAB)

        headers = sheet.row_values(1)
        header_map = {name.strip(): idx for idx, name in enumerate(headers, start=1) if name.strip()}

        if "Status" in header_map:
            sheet.update_cell(row_index, header_map["Status"], status_text)
        if "Antwort_Datum" in header_map:
            sheet.update_cell(row_index, header_map["Antwort_Datum"], datetime.now().strftime("%Y-%m-%d %H:%M"))
        if "Antwort_Zusammenfassung" in header_map:
            sheet.update_cell(row_index, header_map["Antwort_Zusammenfassung"], summary)
        if "Letzte_Nachricht" in header_map:
            sheet.update_cell(row_index, header_map["Letzte_Nachricht"], latest_message[:500])
        elif "Notiz" in header_map:
            existing = sheet.cell(row_index, header_map["Notiz"]).value or ""
            merged = (existing + "\n" if existing else "") + f"Mail: {summary} | {latest_message[:250]}"
            sheet.update_cell(row_index, header_map["Notiz"], merged[:1000])
        return True
    except Exception as e:
        log("WARNUNG", f"Tracking-Zeile konnte nicht aktualisiert werden: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# KLASSIFIKATION
# ─────────────────────────────────────────────────────────────

def heuristic_classification(subject: str, body: str):
    text = f"{subject}\n{body}".lower()

    if any(k in text for k in ["abwesenheit", "out of office", "automatische antwort", "autoreply", "auto reply"]):
        return "autoreply", "Automatische Antwort / Abwesenheitsnotiz"
    if any(k in text for k in ["leider kein interesse", "kein interesse", "absage", "passt leider nicht"]):
        return "negativ", "Eher ablehnende Rückmeldung"
    if any(k in text for k in ["gerne", "interessiert", "rezensionsexemplar", "bitte senden", "interesse", "spannend"]):
        return "positiv", "Positives oder interessiertes Signal"
    if any(k in text for k in ["rückfrage", "frage", "wann", "wie", "können sie", "kannst du", "mehr informationen"]):
        return "rueckfrage", "Enthält Rückfrage oder Informationsbedarf"
    return None, None


def classify_mail(llm, subject: str, body: str):
    heuristic_label, heuristic_summary = heuristic_classification(subject, body)
    if heuristic_label:
        return heuristic_label, heuristic_summary

    prompt = f"""
Du analysierst eingehende E-Mails im Kontext einer Buchmarketing-Kampagne.

BETREFF:
{subject}

MAILTEXT:
{body[:2500]}

Ordne die Nachricht GENAU einer Kategorie zu:
- positiv
- negativ
- rueckfrage
- autoreply
- irrelevant

Antworte exakt in diesem Format:
KATEGORIE: <eine der Kategorien>
ZUSAMMENFASSUNG: <maximal 20 Wörter>
""".strip()

    raw = llm.invoke(prompt).strip()
    cat_match = re.search(r"KATEGORIE\s*:\s*(positiv|negativ|rueckfrage|autoreply|irrelevant)", raw, re.IGNORECASE)
    sum_match = re.search(r"ZUSAMMENFASSUNG\s*:\s*(.+)", raw, re.IGNORECASE)

    if not cat_match:
        return "irrelevant", "Nicht eindeutig zuordenbar"

    label = cat_match.group(1).lower()
    summary = sum_match.group(1).strip() if sum_match else "Kurz klassifiziert"
    return label, summary[:120]


# ─────────────────────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────────────────────

def send_summary_to_telegram(total_mails: int, matched: int, unmatched: int, status_counter: dict):
    lines = [
        "📬 <b>Mail-Check abgeschlossen</b>",
        "",
        f"Neue ungelesene Mails: {total_mails}",
        f"Mit Kampagne verknüpft: {matched}",
        f"Nicht zugeordnet: {unmatched}",
        "",
        "<b>Klassifikation:</b>",
    ]

    for key in ["positiv", "negativ", "rueckfrage", "autoreply", "irrelevant"]:
        lines.append(f"- {key}: {status_counter.get(key, 0)}")

    try:
        utils.send_telegram("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        log("WARNUNG", f"Telegram-Zusammenfassung fehlgeschlagen: {e}")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    log("INFO", "Mail Checker gestartet")

    try:
        messages = fetch_unseen_messages()
    except Exception as e:
        log("FEHLER", f"IMAP-Abruf fehlgeschlagen: {e}")
        raise

    if not messages:
        log("INFO", "Keine ungelesenen E-Mails gefunden")
        send_summary_to_telegram(0, 0, 0, {})
        return

    llm = build_llm()
    tracking_rows = get_tracking_rows()

    matched = 0
    unmatched = 0
    status_counter = {}

    for item in messages:
        label, summary = classify_mail(llm, item["subject"], item["body"])
        status_counter[label] = status_counter.get(label, 0) + 1
        mapped_status = STATUS_MAP.get(label, "Irrelevant")

        row_index = find_tracking_match(item, tracking_rows)
        if row_index is None:
            unmatched += 1
            log("INFO", f"Mail ohne Match: {item['from_email']} | {item['subject']}")
            continue

        updated = update_tracking_row(
            row_index=row_index,
            status_text=mapped_status,
            summary=summary,
            latest_message=item["body"],
        )
        if updated:
            matched += 1
            log("OK", f"Mail zugeordnet: {item['from_email']} → {mapped_status}")

    send_summary_to_telegram(
        total_mails=len(messages),
        matched=matched,
        unmatched=unmatched,
        status_counter=status_counter,
    )
    log("OK", f"Mail Checker beendet — {len(messages)} Mails geprüft, {matched} Matches")


if __name__ == "__main__":
    main()
