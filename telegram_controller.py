"""
telegram_controller.py — Buchmarketing Agentur
═══════════════════════════════════════════════════════════════
Zentrales Steuer-Script. Läuft dauerhaft im Hintergrund.
Empfängt Telegram-Befehle und führt geplante Tasks aus.

Starten:   python telegram_controller.py
Beenden:   Strg+C  (sendet Abmeldung an Telegram)

Befehle (per Telegram):
  /hilfe                — Alle Befehle anzeigen
  /status               — Kampagnen-Übersicht aus Google Sheets
  /recherche [Nische]   — Neue Zielgruppen-Recherche starten
  /pitches              — Pitch-Anschreiben generieren (mit Freigabe)
  /website              — Website bauen & deployen (mit Freigabe)
  /social               — Social-Media-Posts vorbereiten (mit Freigabe)
  /mail                 — Posteingang per IMAP prüfen
  /log [n]              — Letzte n Log-Einträge (Standard: 10)
═══════════════════════════════════════════════════════════════
"""

import os
import signal
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta

import requests
import utils_system as utils

# ─────────────────────────────────────────────────────────────
# KONFIGURATION
# ─────────────────────────────────────────────────────────────

VERSION            = "1.0.0"
OFFSET_FILE        = ".tg_offset"  # Lokale Datei — kein Sheet-API-Verbrauch
SCHED_INTERVAL_SEC = 60            # Sekunden zwischen Scheduler-Checks
TG_TIMEOUT         = 30            # Telegram Long-Poll Timeout in Sekunden

# Tägliche Scripts (ab 08:00 Uhr, einmal pro Tag)
DAILY_SCRIPTS = [
    "review_monitor.py",   # Rezensionen suchen
    "mail_checker.py",     # E-Mails prüfen
]

# Wöchentliche Scripts (jeden Montag ab 09:00 Uhr)
WEEKLY_SCRIPTS = [
    "analytics_reporter.py",  # KPI-Wochenbericht
]

# Befehlsname → Script-Datei
SCRIPTS = {
    "recherche": "pitch_preparer.py",
    "pitches":   "pitch_generator.py",
    "website":   "generate_website.py",
    "social":    "social_media_agent.py",
    "mail":      "mail_checker.py",
    "review":    "review_monitor.py",
    "plan":      "planner.py",
}


# ─────────────────────────────────────────────────────────────
# LOGGING  (Konsole + Logbuch-Tab in Google Sheets)
# ─────────────────────────────────────────────────────────────

_ICONS = {"INFO": "ℹ️", "OK": "✅", "WARNUNG": "⚠️", "FEHLER": "❌"}

def log(level: str, message: str, script: str = "telegram_controller"):
    """Schreibt in die Konsole UND in den Logbuch-Tab."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{_ICONS.get(level, '📌')} [{ts}] {message}", flush=True)
    try:
        utils.write_to_sheet("Logbuch", [[ts, script, level, message]])
    except Exception as e:
        print(f"  ⚠️ Logbuch-Schreibfehler: {e}", flush=True)


# ─────────────────────────────────────────────────────────────
# KONFIGURATION LESEN/SCHREIBEN  (Konfiguration-Tab)
# ─────────────────────────────────────────────────────────────

def get_config(key: str, default=None):
    """Liest einen Wert aus dem Konfiguration-Tab."""
    try:
        val = utils.get_value_by_key("Konfiguration", key)
        return val if val not in (None, "") else default
    except:
        return default

def set_config(key: str, value: str):
    """Aktualisiert einen Wert im Konfiguration-Tab (oder legt ihn neu an)."""
    try:
        client = utils.get_google_client()
        sheet  = client.open_by_key(utils.SPREADSHEET_ID).worksheet("Konfiguration")
        cell   = sheet.find(key, in_column=1)
        if cell:
            sheet.update_cell(cell.row, 2, str(value))
        else:
            sheet.append_row([key, str(value), "Automatisch gesetzt"])
    except Exception as e:
        log("FEHLER", f"set_config({key}): {e}")


# ─────────────────────────────────────────────────────────────
# OFFSET-PERSISTENZ  (lokal in .tg_offset — kein API-Verbrauch)
# ─────────────────────────────────────────────────────────────

def load_offset() -> int:
    """Liest den zuletzt gespeicherten Telegram Update-Offset."""
    try:
        with open(OFFSET_FILE, "r") as f:
            return int(f.read().strip())
    except:
        return 0

def save_offset(offset: int):
    """Speichert den Offset damit nach Neustart keine alten Updates verarbeitet werden."""
    try:
        with open(OFFSET_FILE, "w") as f:
            f.write(str(offset))
    except Exception as e:
        log("WARNUNG", f"Offset-Speichern fehlgeschlagen: {e}")


# ─────────────────────────────────────────────────────────────
# TELEGRAM HELFER
# ─────────────────────────────────────────────────────────────

def tg_api(method: str, data: dict = None, files=None) -> dict:
    """Ruft die Telegram Bot-API auf."""
    url = f"https://api.telegram.org/bot{utils.TELEGRAM_TOKEN}/{method}"
    try:
        if files:
            r = requests.post(url, data=data, files=files, timeout=15)
        else:
            r = requests.post(url, json=data or {}, timeout=15)
        return r.json()
    except Exception as e:
        log("FEHLER", f"Telegram API {method}: {e}")
        return {}

def send(text: str, parse_mode: str = "HTML"):
    """Sendet eine Textnachricht an den konfigurierten Chat."""
    utils.send_telegram(text, parse_mode=parse_mode)

def send_keyboard(text: str, buttons: list):
    """
    Sendet eine Nachricht mit Inline-Buttons und gibt die message_id zurück.
    buttons = [{"text": "Ja", "data": "callback_data"}, ...]
    """
    result = tg_api("sendMessage", {
        "chat_id":    utils.TELEGRAM_CHAT_ID,
        "text":       text,
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [
                [{"text": b["text"], "callback_data": b["data"]} for b in buttons]
            ]
        }
    })
    return result.get("result", {}).get("message_id")

def answer_callback(callback_id: str, text: str = "✅"):
    """Bestätigt einen Callback-Query (entfernt Ladeanimation am Button)."""
    tg_api("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

def edit_message(message_id: int, text: str):
    """Bearbeitet eine bereits gesendete Nachricht."""
    tg_api("editMessageText", {
        "chat_id":    utils.TELEGRAM_CHAT_ID,
        "message_id": message_id,
        "text":       text,
        "parse_mode": "HTML"
    })


# ─────────────────────────────────────────────────────────────
# SCRIPT-AUSFÜHRUNG
# ─────────────────────────────────────────────────────────────

def run_script(script_name: str, args: list = None, background: bool = False) -> bool:
    """
    Startet ein Python-Script als Subprocess.
    background=True  → asynchron, Controller läuft sofort weiter.
    background=False → blockiert bis Script fertig (max. 300 Sek.).
    """
    if not os.path.exists(script_name):
        log("WARNUNG", f"Script nicht gefunden: {script_name}")
        send(f"⚠️ Script <code>{script_name}</code> noch nicht vorhanden.")
        return False

    cmd = [sys.executable, script_name] + (args or [])
    log("INFO", f"Starte: {' '.join(cmd)}")

    try:
        if background:
            subprocess.Popen(cmd)
            return True
        result = subprocess.run(cmd, timeout=300)
        success = result.returncode == 0
        if not success:
            log("WARNUNG", f"{script_name} beendet mit Code {result.returncode}")
        return success
    except subprocess.TimeoutExpired:
        log("FEHLER", f"Timeout nach 5 Min: {script_name}")
        return False
    except Exception as e:
        log("FEHLER", f"Script-Start fehlgeschlagen {script_name}: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# KOMMANDO-HANDLER
# ─────────────────────────────────────────────────────────────

def cmd_hilfe(_args):
    send(
        f"🤖 <b>Buchmarketing Agentur</b>  <i>v{VERSION}</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📋 <b>Info &amp; Kontrolle</b>\n"
        "  /hilfe             — Diese Übersicht\n"
        "  /status            — Kampagnen-Übersicht\n"
        "  /log [n]           — Letzte n Logzeilen (Standard: 10)\n\n"
        "🔍 <b>Recherche</b>\n"
        "  /recherche Nische  — Neue Recherche starten\n"
        "    z.B.: /recherche Christliche Zeitschriften\n"
        "    z.B.: /recherche Jugendbuch Influencer\n\n"
        "✍️ <b>Pitches &amp; E-Mail</b>\n"
        "  /pitches           — Anschreiben generieren\n"
        "  /mail              — Posteingang prüfen\n\n"
        "🌐 <b>Website</b>\n"
        "  /website           — Website bauen &amp; deployen\n\n"
        "📱 <b>Social Media</b>\n"
        "  /social            — Posts vorbereiten\n"
    )


def cmd_status(_args):
    send("⏳ Lade Kampagnen-Status...")
    try:
        def count_status(tab, col, val):
            try:
                return sum(1 for r in utils.get_sheet_data(tab) if r.get(col) == val)
            except:
                return "?"

        def total(tab):
            try:
                return len(utils.get_sheet_data(tab))
            except:
                return "?"

        buchtitel   = utils.get_value_by_key("Allgemeines", "buchtitel")    or "?"
        autorin     = utils.get_value_by_key("Allgemeines", "autorin_name") or "?"
        ziel        = get_config("ziel_datenbank_groesse", 50)

        kontakte    = total("Rohdaten")
        top_treffer = count_status("Rohdaten",           "Status", "Top-Treffer")
        gesendet    = count_status("Kampagnen_Tracking", "Status", "Gesendet")
        reaktionen  = count_status("Kampagnen_Tracking", "Status", "Reagiert_positiv")
        social_wait = count_status("Social_Media_Queue", "Status", "Freigabe_ausstehend")
        rez_neu     = count_status("Rezension",          "Status", "Neu gefunden")

        send(
            f"📊 <b>Kampagnen-Status</b>\n"
            f"<i>{buchtitel} — {autorin}</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 <b>Kontakte (Rohdaten)</b>\n"
            f"  Gesamt gefunden:  {kontakte}\n"
            f"  Top-Treffer:      {top_treffer}  (Ziel: {ziel})\n\n"
            f"📧 <b>Pitches</b>\n"
            f"  Gesendet:         {gesendet}\n"
            f"  Positiv reagiert: {reaktionen}\n\n"
            f"📱 <b>Social Media</b>\n"
            f"  Warten Freigabe:  {social_wait}\n\n"
            f"📖 <b>Neue Rezensionen:</b>  {rez_neu}"
        )
    except Exception as e:
        log("FEHLER", f"cmd_status: {e}")
        send(f"❌ Status-Fehler: {e}")


def cmd_recherche(args):
    nische = " ".join(args).strip() if args else ""
    if not nische:
        send(
            "⚠️ Bitte eine Zielgruppe angeben!\n\n"
            "<b>Beispiele:</b>\n"
            "  /recherche Buchblogger Romantik\n"
            "  /recherche Christliche Zeitschriften\n"
            "  /recherche Jugendbuch Influencer Instagram\n"
            "  /recherche Feuilleton Tageszeitungen\n"
            "  /recherche Christliches Radio"
        )
        return

    # Neue Aufgabe in Google Sheets eintragen (single point of truth)
    try:
        task_id = f"task_{datetime.now().strftime('%d%H%M%S')}"
        today   = datetime.now().strftime("%Y-%m-%d")
        utils.write_to_sheet("Aufgaben", [[
            task_id, "1", nische,
            f"{nische.lower()} rezension kontakt",
            "bereit_fuer_recherche", today, "", ""
        ]])
        log("INFO", f"Neue Aufgabe angelegt: {task_id} — {nische}")
    except Exception as e:
        log("WARNUNG", f"Aufgabe konnte nicht in Sheet geschrieben werden: {e}")

    send(
        f"🔍 <b>Recherche gestartet</b>\n\n"
        f"Nische: <b>{nische}</b>\n\n"
        f"⏳ Läuft im Hintergrund...\n"
        f"Ich melde mich wenn Ergebnisse vorliegen!"
    )
    run_script(SCRIPTS["recherche"], background=True)


def cmd_pitches(_args):
    hinweis = ""
    try:
        kontakte = utils.get_sheet_data("Rohdaten")
        bereit   = [k for k in kontakte
                    if k.get("Status") in ("Top-Treffer", "Manuell prüfen")]
        if bereit:
            hinweis = f"\n\n<b>{len(bereit)} Kontakte</b> bereit für Anschreiben."
        else:
            hinweis = (
                "\n\n⚠️ Noch keine freigegebenen Kontakte in <b>Rohdaten</b>.\n"
                "Setze Status auf <i>Top-Treffer</i> oder <i>Manuell prüfen</i>."
            )
    except:
        pass

    send_keyboard(
        f"✍️ <b>Pitch-Anschreiben generieren</b>{hinweis}\n\n"
        f"Das LLM erstellt individuelle Anschreiben\n"
        f"je nach Kontakt-Typ (Blogger, Presse, Radio...).\n\n"
        f"Entwürfe landen in <b>Kampagnen_Tracking</b>.\n"
        f"Soll ich starten?",
        [
            {"text": "✅ Ja, Pitches generieren!", "data": "run_pitches"},
            {"text": "❌ Abbrechen",               "data": "cancel"}
        ]
    )


def cmd_website(_args):
    send_keyboard(
        "🌐 <b>Website neu bauen</b>\n\n"
        "1. Daten aus Google Sheets laden\n"
        "2. Eleventy lokal bauen\n"
        "3. Screenshot → Telegram-Vorschau\n"
        "4. FTP-Upload nach deiner Freigabe\n\n"
        "Jetzt starten?",
        [
            {"text": "🚀 Ja, bauen!",  "data": "run_website"},
            {"text": "❌ Abbrechen",   "data": "cancel"}
        ]
    )


def cmd_social(_args):
    send_keyboard(
        "📱 <b>Social-Media-Posts vorbereiten</b>\n\n"
        "Das LLM erstellt Post-Ideen für:\n"
        "• Instagram / Facebook\n"
        "• Pinterest\n\n"
        "Jeder Post kommt einzeln zur Freigabe bevor er gepostet wird.\n"
        "Jetzt starten?",
        [
            {"text": "📱 Ja, los!",    "data": "run_social"},
            {"text": "❌ Abbrechen",   "data": "cancel"}
        ]
    )


def cmd_mail(_args):
    send("📬 Prüfe Posteingang <i>info@anni-lindner.de</i>...")
    log("INFO", "Manueller Mail-Check gestartet")
    run_script(SCRIPTS["mail"], background=True)


def cmd_log(args):
    try:
        n     = min(int(args[0]), 50) if args else 10
        rows  = utils.get_sheet_data("Logbuch")
        letzte = rows[-n:] if len(rows) >= n else rows

        if not letzte:
            send("📋 Logbuch ist leer.")
            return

        text = f"📋 <b>Letzte {len(letzte)} Einträge</b>\n\n"
        for r in reversed(letzte):
            icon = _ICONS.get(r.get("Level", "INFO"), "📌")
            ts   = str(r.get("Datum_Zeit", ""))[:16]
            scr  = str(r.get("Script", ""))[:25]
            msg  = str(r.get("Eintrag", ""))[:120]
            text += f"{icon} <code>{ts}</code>  <i>{scr}</i>\n{msg}\n\n"
        send(text)
    except Exception as e:
        send(f"❌ Log-Fehler: {e}")


# ─────────────────────────────────────────────────────────────
# CALLBACK-HANDLER  (Inline-Button-Presse → Freigaben)
# ─────────────────────────────────────────────────────────────

# callback_data → (script_datei, Status-Text für bearbeitete Nachricht)
_CALLBACKS = {
    "run_pitches": ("pitch_generator.py",   "✍️ Pitch-Generator läuft..."),
    "run_website": ("generate_website.py",  "🌐 Website-Build gestartet..."),
    "run_social":  ("social_media_agent.py","📱 Social-Media-Agent läuft..."),
}

def handle_callback(callback: dict):
    """Verarbeitet einen Inline-Button-Druck."""
    data   = callback.get("data", "")
    cb_id  = callback["id"]
    msg_id = callback["message"]["message_id"]

    answer_callback(cb_id)  # Ladeanimation am Button entfernen

    if data == "cancel":
        edit_message(msg_id, "🛑 Abgebrochen.")
        log("INFO", "Aktion abgebrochen (Telegram)")
        return

    if data in _CALLBACKS:
        script, status_text = _CALLBACKS[data]
        edit_message(msg_id, f"⏳ {status_text}")
        log("INFO", f"Freigabe via Telegram: {script}")
        run_script(script, background=True)
        return

    # Unbekannte Callbacks durchloggen (z.B. deploy_yes von generate_website.py)
    log("INFO", f"Unbekannter Callback empfangen: {data}")


# ─────────────────────────────────────────────────────────────
# UPDATE-VERARBEITUNG
# ─────────────────────────────────────────────────────────────

_COMMANDS = {
    "/hilfe":     cmd_hilfe,
    "/help":      cmd_hilfe,
    "/start":     cmd_hilfe,
    "/status":    cmd_status,
    "/recherche": cmd_recherche,
    "/pitches":   cmd_pitches,
    "/website":   cmd_website,
    "/social":    cmd_social,
    "/mail":      cmd_mail,
    "/log":       cmd_log,
}

def process_update(update: dict):
    """Verarbeitet ein einzelnes Telegram-Update."""

    # Callback-Query (Button-Druck)
    if "callback_query" in update:
        handle_callback(update["callback_query"])
        return

    # Normale oder bearbeitete Nachricht
    msg  = update.get("message") or update.get("edited_message")
    if not msg:
        return

    text = msg.get("text", "").strip()
    if not text.startswith("/"):
        return

    # /befehl@botname → /befehl   (für Gruppen-Chats)
    parts   = text.split()
    cmd_raw = parts[0].split("@")[0].lower()
    args    = parts[1:]

    handler = _COMMANDS.get(cmd_raw)
    if handler:
        log("INFO", f"Befehl empfangen: {text[:80]}")
        try:
            handler(args)
        except Exception as e:
            err = traceback.format_exc()
            log("FEHLER", f"{cmd_raw}: {e}\n{err}")
            send(f"❌ Fehler bei <code>{cmd_raw}</code>:\n<code>{e}</code>")
    else:
        send(
            f"❓ Unbekannter Befehl: <code>{cmd_raw}</code>\n"
            f"Tippe /hilfe für alle verfügbaren Befehle."
        )


# ─────────────────────────────────────────────────────────────
# SCHEDULER  (Tägliche & Wöchentliche Tasks)
# ─────────────────────────────────────────────────────────────

_last_sched = datetime.min

def check_scheduled_tasks():
    """Prüft ob automatisch geplante Scripts ausgeführt werden sollen."""
    global _last_sched
    now = datetime.now()
    if (now - _last_sched).total_seconds() < SCHED_INTERVAL_SEC:
        return
    _last_sched = now

    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # ── Tägliche Tasks (ab 08:00 Uhr, max. 1x pro Tag) ──────
    try:
        last_daily = datetime.strptime(
            str(get_config("letzter_daily_run", "2000-01-01"))[:10], "%Y-%m-%d"
        )
    except:
        last_daily = datetime.min

    if now.hour >= 8 and last_daily < today:
        ran_any = False
        for script in DAILY_SCRIPTS:
            if os.path.exists(script):
                log("INFO", f"Scheduler (tägl.): {script}")
                run_script(script, background=True)
                ran_any = True
        if ran_any:
            set_config("letzter_daily_run", now.strftime("%Y-%m-%d"))

    # ── Wöchentliche Tasks (Montag = weekday 0, ab 09:00) ───
    try:
        last_weekly = datetime.strptime(
            str(get_config("letzter_weekly_run", "2000-01-01"))[:10], "%Y-%m-%d"
        )
    except:
        last_weekly = datetime.min

    if now.weekday() == 0 and now.hour >= 9 and last_weekly < today - timedelta(days=6):
        ran_any = False
        for script in WEEKLY_SCRIPTS:
            if os.path.exists(script):
                log("INFO", f"Scheduler (wöch.): {script}")
                run_script(script, background=True)
                ran_any = True
        if ran_any:
            set_config("letzter_weekly_run", now.strftime("%Y-%m-%d"))


# ─────────────────────────────────────────────────────────────
# HAUPTSCHLEIFE
# ─────────────────────────────────────────────────────────────

def main():
    log("OK",   f"🤖 Telegram Controller v{VERSION} gestartet")
    log("INFO", f"Chat-ID: {utils.TELEGRAM_CHAT_ID}")

    offset = load_offset()
    log("INFO", f"Polling-Offset: {offset}")

    # Sauberes Beenden auf Strg+C oder SIGTERM
    def shutdown(sig, frame):
        save_offset(offset)
        log("INFO", "🛑 Controller wird beendet.")
        send("🔴 <b>Buchmarketing Agentur offline.</b>")
        sys.exit(0)

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Startmeldung
    send(
        f"🟢 <b>Buchmarketing Agentur online!</b>\n"
        f"<i>v{VERSION} — Bereit für Befehle.</i>\n\n"
        f"Tippe /hilfe für alle Befehle."
    )

    tg_url    = f"https://api.telegram.org/bot{utils.TELEGRAM_TOKEN}/getUpdates"
    err_count = 0

    while True:
        try:
            resp = requests.get(
                tg_url,
                params={
                    "timeout":         TG_TIMEOUT,
                    "offset":          offset,
                    "allowed_updates": ["message", "callback_query"]
                },
                timeout=TG_TIMEOUT + 5
            )

            if resp.status_code == 200:
                err_count = 0
                for update in resp.json().get("result", []):
                    offset = update["update_id"] + 1
                    process_update(update)
                save_offset(offset)  # Nach jedem Batch lokal speichern

            else:
                log("WARNUNG", f"Telegram HTTP {resp.status_code}: {resp.text[:120]}")
                time.sleep(5)

        except requests.exceptions.Timeout:
            pass  # Long-Poll Timeout ist völlig normal

        except requests.exceptions.ConnectionError as e:
            err_count += 1
            log("WARNUNG", f"Verbindungsfehler #{err_count}: {e}")
            time.sleep(min(60, err_count * 10))
            continue

        except Exception as e:
            err_count += 1
            log("FEHLER", f"Unbekannter Fehler #{err_count}: {e}")
            time.sleep(min(30, err_count * 5))
            continue

        check_scheduled_tasks()


if __name__ == "__main__":
    main()
