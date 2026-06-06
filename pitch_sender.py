"""
pitch_sender.py — Buchmarketing Agentur
═══════════════════════════════════════════════════════════════
Versendet freigegebene Pitch-Entwürfe aus Kampagnen_Tracking per SMTP.

Ziele:
- Freigegebene Entwürfe aus Google Sheets lesen
- E-Mails per SMTP versenden
- Versandstatus in Kampagnen_Tracking aktualisieren
- Telegram-Zusammenfassung senden
- Fehler sauber ins Logbuch schreiben

Erwartete .env-Werte:
- SMTP_HOST
- SMTP_PORT
- MAIL_USER
- MAIL_PASS

Starten:
    python pitch_sender.py
═══════════════════════════════════════════════════════════════
"""

import html
import smtplib
from datetime import datetime
from email.message import EmailMessage

import utils_system as utils


# ─────────────────────────────────────────────────────────────
# KONFIGURATION
# ─────────────────────────────────────────────────────────────

TRACKING_TAB = "Kampagnen_Tracking"
LOG_TAB = "Logbuch"
CONFIG_TAB = "Konfiguration"
DEFAULT_MAX_PER_RUN = 10
SENDABLE_STATUSES = {"Freigegeben"}
SUCCESS_STATUS = "Gesendet"
ERROR_STATUS = "Versand_Fehler"


# ─────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────

def log(level: str, message: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{level}] {ts} — {message}", flush=True)
    try:
        utils.write_to_sheet(LOG_TAB, [[ts, "pitch_sender.py", level, message]])
    except Exception as e:
        print(f"[WARNUNG] Logbuch konnte nicht geschrieben werden: {e}", flush=True)


# ─────────────────────────────────────────────────────────────
# CONFIG / SHEETS
# ─────────────────────────────────────────────────────────────

def get_config_value(key: str, default=""):
    try:
        value = utils.get_value_by_key(CONFIG_TAB, key)
        return value if value not in (None, "") else default
    except:
        return default



def get_max_per_run():
    raw = get_config_value("mail_send_max_per_run", str(DEFAULT_MAX_PER_RUN))
    try:
        return max(1, int(raw))
    except:
        return DEFAULT_MAX_PER_RUN



def get_tracking_sheet():
    client = utils.get_google_client()
    return client.open_by_key(utils.SPREADSHEET_ID).worksheet(TRACKING_TAB)



def get_tracking_rows():
    try:
        return utils.get_sheet_data(TRACKING_TAB)
    except Exception as e:
        log("FEHLER", f"Kampagnen_Tracking konnte nicht geladen werden: {e}")
        return []



def get_header_map(sheet):
    headers = sheet.row_values(1)
    return {name.strip(): idx for idx, name in enumerate(headers, start=1) if name.strip()}



def pick_value(row: dict, candidates: list):
    for key in candidates:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""



def select_sendable_rows(rows: list, max_per_run: int):
    selected = []
    for idx, row in enumerate(rows, start=2):
        status = str(row.get("Status", "")).strip()
        if status not in SENDABLE_STATUSES:
            continue

        recipient = pick_value(row, ["E-Mail", "Email", "Mail"])
        subject = pick_value(row, ["Betreff", "Subject"])
        body = pick_value(row, ["Pitch-Text", "Pitch_Text", "Pitchtext", "Anschreiben", "Text"])
        medium = pick_value(row, ["Medium/Name", "Medium", "Name"])

        if not recipient or not subject or not body:
            selected.append({
                "row_index": idx,
                "medium": medium or "Unbekannt",
                "recipient": recipient,
                "subject": subject,
                "body": body,
                "valid": False,
                "error": "Pflichtfelder fehlen (E-Mail, Betreff oder Pitch-Text)",
            })
            continue

        selected.append({
            "row_index": idx,
            "medium": medium or "Unbekannt",
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "valid": True,
            "error": "",
        })

        if len([x for x in selected if x["valid"]]) >= max_per_run:
            break

    return selected



def update_tracking_row(sheet, header_map: dict, row_index: int, updates: dict):
    for key, value in updates.items():
        if key in header_map:
            sheet.update_cell(row_index, header_map[key], value)


# ─────────────────────────────────────────────────────────────
# SMTP
# ─────────────────────────────────────────────────────────────

def send_email(recipient: str, subject: str, body: str):
    smtp_host = getattr(utils, "SMTP_HOST", None)
    smtp_port = int(getattr(utils, "SMTP_PORT", 587) or 587)
    mail_user = getattr(utils, "MAIL_USER", None)
    mail_pass = getattr(utils, "MAIL_PASS", None)

    if not smtp_host or not mail_user or not mail_pass:
        raise RuntimeError("SMTP-Konfiguration unvollständig. Bitte SMTP_HOST, SMTP_PORT, MAIL_USER, MAIL_PASS prüfen.")

    message = EmailMessage()
    message["From"] = mail_user
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.starttls()
        server.login(mail_user, mail_pass)
        server.send_message(message)


# ─────────────────────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────────────────────

def send_summary_to_telegram(sent_count: int, skipped_count: int, error_items: list):
    lines = [
        "📤 <b>Pitch-Versand abgeschlossen</b>",
        "",
        f"Gesendet: {sent_count}",
        f"Übersprungen: {skipped_count}",
        f"Fehler: {len(error_items)}",
    ]

    if error_items:
        lines.append("")
        lines.append("<b>Fehler:</b>")
        for item in error_items[:5]:
            medium = html.escape(item.get("medium", "Unbekannt"))
            recipient = html.escape(item.get("recipient", ""))
            error_text = html.escape(item.get("error", "Unbekannter Fehler"))
            lines.append(f"- {medium} ({recipient}): {error_text}")

    try:
        utils.send_telegram("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        log("WARNUNG", f"Telegram-Zusammenfassung fehlgeschlagen: {e}")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    log("INFO", "Pitch Sender gestartet")

    sheet = get_tracking_sheet()
    header_map = get_header_map(sheet)
    rows = get_tracking_rows()
    max_per_run = get_max_per_run()
    items = select_sendable_rows(rows, max_per_run)

    if not items:
        log("INFO", "Keine freigegebenen Entwürfe zum Versenden gefunden")
        send_summary_to_telegram(0, 0, [])
        return

    sent_count = 0
    skipped_count = 0
    error_items = []

    for item in items:
        row_index = item["row_index"]

        if not item["valid"]:
            skipped_count += 1
            error_items.append(item)
            update_tracking_row(sheet, header_map, row_index, {
                "Status": ERROR_STATUS,
                "Versand_Fehler": item["error"],
            })
            log("WARNUNG", f"Versand übersprungen für {item['medium']}: {item['error']}")
            continue

        try:
            send_email(item["recipient"], item["subject"], item["body"])
            sent_at = datetime.now().strftime("%Y-%m-%d %H:%M")
            update_tracking_row(sheet, header_map, row_index, {
                "Status": SUCCESS_STATUS,
                "Gesendet_Am": sent_at,
                "Versand_Fehler": "",
            })
            sent_count += 1
            log("OK", f"Pitch gesendet an {item['recipient']} ({item['medium']})")
        except Exception as e:
            error_text = str(e)
            error_items.append({**item, "error": error_text})
            update_tracking_row(sheet, header_map, row_index, {
                "Status": ERROR_STATUS,
                "Versand_Fehler": error_text[:300],
            })
            log("FEHLER", f"Versand fehlgeschlagen für {item['recipient']}: {error_text}")

    send_summary_to_telegram(sent_count, skipped_count, error_items)
    log("OK", f"Pitch Sender beendet — {sent_count} gesendet, {len(error_items)} Fehler")


if __name__ == "__main__":
    main()
