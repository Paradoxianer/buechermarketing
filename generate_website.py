import json
import os
import shutil
import subprocess
import zipfile
import requests
import time
import csv
import utils_system as utils  # 👈 DEIN NEUES MODUL
from ftplib import FTP, error_perm


# --- KONFIGURATION JETZT ZENTRAL ÜBER utils_system ---
# TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, SPREADSHEET_ID werden jetzt aus .env geladen
# Zugriff erfolgt via utils.TELEGRAM_TOKEN etc.

# --- GOOGLE SPREADSHEET CONFIG ---
TAB_CLIPPINGS = "Rezension"

# 🦙 OLLAMA KONFIGURATION (Exakt auf dein System angepasst!)
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODELL = "llama3:8b"  # Nutzt jetzt dein lokal installiertes Modell

# 🌐 FTP ZUGANGSDATEN

# 🛡️ SCHUTZ-FILTER: Diese Ordner auf dem FTP-Server werden NIEMALS angefasst!
FTP_IGNORE_DIRS = ["lindner", "stammbaum"]

# 📁 PFADE
FAQ_SOURCE_FILE = "agentur_wissen/faq_katalog.json"
BILDER_SOURCE_DIR = "agentur_wissen/bilder"
WEBSITE_DIR = "autoren_website"
LOCAL_BUILD_DIR = os.path.join(WEBSITE_DIR, "_site")
ELEVENTY_DATA_DIR = os.path.join(WEBSITE_DIR, "src", "_data")
ELEVENTY_IMAGES_DIR = os.path.join(WEBSITE_DIR, "src", "images")
ELEVENTY_DOWNLOADS_DIR = os.path.join(WEBSITE_DIR, "src", "downloads")

def fetch_google_sheet_by_name(sheet_name):
    """Holt Daten jetzt sauber über das neue utils-System."""
    try:
        print(f"[📊 SPREADSHEET] Lade Daten aus Tab: {sheet_name}...", flush=True)
        # utils.get_sheet_data gibt eine Liste von Dicts zurück
        return utils.get_sheet_data(sheet_name)
    except Exception as e:
        print(f"[❌ SPREADSHEET] Fehler beim Laden: {e}")
        return None


def ask_llama_for_preview(fokus_buch, rezensionen):
    """ Erstellt mit Llama einen harten Auszug der echten Daten für Telegram """
    print(f"\n[🦙 LLAMA-MODUL] Generiere präzisen Änderungs-Auszug mit '{OLLAMA_MODELL}'...")
    
    # Wir bauen eine knallharte Faktenliste für das Modell
    rez_liste = ""
    for idx, r in enumerate(rezensionen, 1):
        if "Dieses neue Werk" not in r['text']:
            rez_liste += f"- {r['autor']} ({r['plattform']}): \"{r['text'][:60]}...\"\n"

    prompt = (
        f"Du bist ein technischer Webmaster-Agent. Erstelle einen strukturierten, übersichtlichen Änderungsbericht "
        f"für ein Telegram-Log basierend auf diesen exakten Fakten:\n\n"
        f"NEUES FOKUS-BUCH:\n"
        f"Titel: {fokus_buch.get('titel', 'Unbekannt')}\n"
        f"Erscheinungsdatum: {fokus_buch.get('erscheinungsdatum', 'Unbekannt')}\n\n"
        f"AKTUELLE REZENSIONEN:\n"
        f"{rez_liste if rez_liste else '- Keine neuen Rezensionen vorhanden.'}\n"
        f"Formatierungsvorgabe für Telegram:\n"
        f"Nutze kurze Bulletpoints. Keine Floskeln, kein 'Hallo', kein langes Drumherumreden. "
        f"Zeige einfach knackig, was neu auf die Website kommt."
    )
    
    try:
        response = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODELL,
            "prompt": prompt,
            "stream": False
        }, timeout=20)
        
        if response.status_code == 200:
            return response.json().get("response", "").strip()
    except Exception:
        pass
    
    # Fallback, falls Ollama offline ist
    return f"📖 Fokus-Buch: {fokus_buch.get('titel')}\n💬 Rezensionen: {len(rezensionen)} Stück geladen."


def upload_directory_to_ftp():
    import os
    import time
    import socket
    from ftplib import FTP

    print("[FTP] Starte Smart Upload für zickigen Server")

    local_dir = LOCAL_BUILD_DIR
    uploaded = []
    failed = []

    def ensure_remote_dir(ftp, remote_dir):
        current = ""
        for part in remote_dir.strip("/").split("/"):
            if not part:
                continue
            current += "/" + part
            try:
                ftp.mkd(current)
                print(f"[FTP] Ordner erstellt: {current}")
            except Exception:
                pass

    def connect_fresh():
        ftp = FTP()
        ftp.connect(utils.FTP_HOST, utils.FTP_PORT, timeout=60)
        ftp.login(utils.FTP_USER, utils.FTP_PASSWORD)
        ftp.set_pasv(True)
        ftp.voidcmd("TYPE I")
        try:
            ftp.sock.settimeout(60)
        except Exception:
            pass
        ftp.set_debuglevel(2)
        return ftp

    def upload_single_file(local_path, remote_dir, filename, max_attempts=3):
        remote_path = f"{remote_dir}/{filename}"
        file_size = os.path.getsize(local_path)

        for attempt in range(1, max_attempts + 1):
            ftp = None
            try:
                print(f"\n[FTP] Datei: {remote_path} ({file_size/1024:.1f} KB) | Versuch {attempt}/{max_attempts}")

                ftp = connect_fresh()
                ensure_remote_dir(ftp, remote_dir)
                ftp.cwd(remote_dir)

                with open(local_path, "rb") as f:
                    print(f"[FTP] Upload starte: {remote_path}")
                    ftp.storbinary(f"STOR {filename}", f, blocksize=2048)

                print(f"[FTP] ✅ Erfolgreich: {remote_path}")

                try:
                    ftp.quit()
                except Exception:
                    try:
                        ftp.close()
                    except Exception:
                        pass

                uploaded.append(remote_path)
                time.sleep(1.5)  # wichtig wegen 421 too many connections
                return True

            except (TimeoutError, socket.timeout) as e:
                print(f"[FTP] ⏱️ Timeout bei {remote_path}: {e}")

            except Exception as e:
                print(f"[FTP] ⚠️ Fehler bei {remote_path}: {type(e).__name__}: {e}")

            finally:
                if ftp:
                    try:
                        ftp.close()
                    except Exception:
                        pass

            if attempt < max_attempts:
                wait_time = 5 * attempt
                print(f"[FTP] Warte {wait_time}s vor Retry...")
                time.sleep(wait_time)

        print(f"[FTP] ❌ Endgültig fehlgeschlagen: {remote_path}")
        failed.append((local_path, remote_dir, filename))
        return False

    def collect_files():
        result = []
        for root, dirs, files in os.walk(local_dir):
            dirs[:] = [d for d in dirs if d not in FTP_IGNORE_DIRS]

            rel = os.path.relpath(root, local_dir)
            rel = "" if rel == "." else rel.replace("\\", "/")
            remote_dir = utils.FTP_REMOTE_DIR if not rel else f"{utils.FTP_REMOTE_DIR}/{rel}"

            for filename in files:
                local_path = os.path.join(root, filename)
                result.append((local_path, remote_dir, filename))
        return result

    all_files = collect_files()
    print(f"[FTP] {len(all_files)} Dateien gefunden")

    # Erste Runde
    for local_path, remote_dir, filename in all_files:
        upload_single_file(local_path, remote_dir, filename, max_attempts=3)

    # Zweite Runde nur für Fehlversuche
    if failed:
        retry_batch = failed[:]
        failed.clear()

        print(f"\n[FTP] Starte zweite Gesamtrunde für {len(retry_batch)} fehlgeschlagene Dateien...")
        time.sleep(10)

        for local_path, remote_dir, filename in retry_batch:
            upload_single_file(local_path, remote_dir, filename, max_attempts=2)

    print("\n[FTP] ✅ Upload beendet")
    print(f"[FTP] Hochgeladen: {len(uploaded)}")
    print(f"[FTP] Fehler: {len(failed)}")

    try:
        message = "<b>📡 Deployment Ergebnis</b>\n\n"
        message += f"✅ Hochgeladen: {len(uploaded)}\n"
        message += f"❌ Fehler: {len(failed)}\n"

        if failed:
            message += "\n<b>Fehlerhafte Dateien:</b>\n"
            for _, remote_dir, filename in failed[:10]:
                message += f"- {remote_dir}/{filename}\n"

        utils.send_telegram(message)

    except Exception as e:
        print(f"[TELEGRAM] Fehler beim Senden: {e}")

    if failed and not uploaded:
        return "failed"
    elif failed:
        return "partial"
    return "success"

def send_telegram_proposal_with_image(image_path):
    """
    Sendet den generierten Screenshot an Telegram 
    und bietet Buttons zur Freigabe an.
    """
    # 1. Pfad-Prüfung
    abs_path = os.path.abspath(image_path)
    print(f"[📱 TELEGRAM] Suche Bilddatei unter: {abs_path}")
    
    if not image_path or not os.path.exists(image_path):
        print(f"[❌ FEHLER] Bilddatei nicht gefunden: {image_path}")
        return None

    # 2. API-Aufruf
    url = f"https://api.telegram.org/bot{utils.TELEGRAM_TOKEN}/sendPhoto"
    
    caption = "🏗️ *NEUER WEBSITE-BUILD BEREIT!*\n\nHier ist die visuelle Vorschau deiner neuen Seite. Soll ich den FTP-Upload jetzt starten?"
    
    try:
        with open(image_path, "rb") as photo:
            files = {"photo": photo}
            data = {
                "chat_id": utils.TELEGRAM_CHAT_ID,
                "caption": caption,
                "parse_mode": "Markdown",
                "reply_markup": json.dumps({
                    "inline_keyboard": [
                        [
                            {"text": "🚀 Ja, FTP-Upload!", "callback_data": "deploy_yes"},
                            {"text": "🛑 Abbrechen", "callback_data": "reject"}
                        ]
                    ]
                })
            }
            response = requests.post(url, files=files, data=data)
            
        # 3. Antwort auswerten
        if response.status_code == 200:
            result = response.json().get("result", {})
            print("[✅ TELEGRAM] Vorschau erfolgreich gesendet!")
            return result.get("message_id")
        else:
            print(f"[❌ TELEGRAM] Fehlercode: {response.status_code}")
            print(f"[❌ TELEGRAM] Antwort-Details: {response.text}")
            return None
            
    except Exception as e:
        print(f"[❌ TELEGRAM] Unerwarteter Fehler beim Senden: {e}")
        return None


def wait_for_approval(message_id):
    """Wartet auf User-Feedback via Telegram, nutzt Token aus utils_system."""
    # Zugriff über das utils-Modul
    url = f"https://api.telegram.org/bot{utils.TELEGRAM_TOKEN}/getUpdates"
    offset = None
    
    try:
        # Initialen Offset holen
        init_res = requests.get(url, params={"timeout": 0}).json()
        updates = init_res.get("result", [])
        if updates:
            offset = updates[-1]["update_id"] + 1
    except Exception:
        pass

    print("[⏳ SCHLEIFE] Warte auf Freigabe via Telegram...", flush=True)
    while True:
        try:
            response = requests.get(url, params={"timeout": 1, "offset": offset}).json()
            for update in response.get("result", []):
                offset = update["update_id"] + 1
                if "callback_query" in update:
                    callback = update["callback_query"]
                    data = callback["data"]
                    
                    # Antwort an Telegram senden (auch hier Token nutzen)
                    requests.post(f"https://api.telegram.org/bot{utils.TELEGRAM_TOKEN}/answerCallbackQuery", json={
                        "callback_query_id": callback["id"], 
                        "text": "Verarbeitet!"
                    })
                    return True if data == "deploy_yes" else False
            print(".", end="", flush=True)
            time.sleep(0.5)
        except Exception:
            time.sleep(2)

def capture_website_screenshot(output_path="preview.png"):
    """ Startet einen unsichtbaren Browser, öffnet die lokale HTML-Datei und macht ein Foto """
    print("[📸 SCREENSHOT] Starte Browser-Modul für visuelle Vorschau...", flush=True)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            # Browser unsichtbar starten
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # Die von Eleventy frisch gebaute index.html lokal öffnen
            # Passe den Pfad an, falls LOCAL_BUILD_DIR anders definiert ist
            local_html_path = os.path.abspath(os.path.join(LOCAL_BUILD_DIR, "index.html"))
            
            # Browser auf die lokale Datei ansetzen
            page.goto(f"file://{local_html_path}")
            
            # Kurz warten, falls Schriftarten oder Stile laden müssen
            page.wait_for_timeout(1000)
            
            # Browserfenster auf eine typische Desktop-Größe einstellen
            page.set_viewport_size({"width": 1280, "height": 900})
            
            # Screenshot aufnehmen (full_page=True würde die ganze lange Seite fotografieren, 
            # full_page=False nimmt nur den direkt sichtbaren Bereich "Above the fold")
            page.screenshot(path=output_path, full_page=True)
            browser.close()
            
        print("   ✅ Screenshot erfolgreich generiert!", flush=True)
        return output_path
    except Exception as e:
        print(f"   ❌ Screenshot-Fehler: {e}", flush=True)
        return None




def main():
    print("="*60)
    print("🏗️ START DES WEBMASTER-AGENTS (GOOGLE-TABELLEN MODUS)")
    print("="*60)

    # 1. Daten direkt aus Google Tabellen laden (KEINE JSON-DATEI MEHR)
    print("[📊 DATEN] Lade aktuelle Inhalte aus Google Sheets...")
    
    # Hier holen wir die Daten aus deinen neuen Tabellenblättern
    # Stell sicher, dass die Namen 'Allgemeines', 'Website_Content', 'Books', 'Rezension' exakt stimmen
    buecher_liste = utils.get_sheet_data("Books")
    allgemeines = utils.get_sheet_data("Allgemeines")
    website_content = utils.get_sheet_data("Website_Content")
    clippings_raw = utils.get_sheet_data("Rezension")

    # Buch-Logik:
    buecher_liste.sort(key=lambda x: x.get("erscheinungsdatum", "0000-00-00"), reverse=True)
    fokus_buch = buecher_liste[0] if buecher_liste else {}
    fokus_titel = fokus_buch.get("titel", "What is Love?")

    # Rezensions-Logik:
    fokus_rezensionen = []
    if clippings_raw:
        for row in clippings_raw:
            if str(row.get("Status", "")).lower() == "veröffentlicht":
                fokus_rezensionen.append({
                    "text": row.get("Zitat") or "",
                    "autor": row.get("Medium/Name") or "Anonym",
                    "plattform": row.get("Typ") or "Web",
                    "link": row.get("Link") or "" # 👈 NEU: Link mitnehmen
                })

    # 1. Autorin & Socials aus dem Content laden
    autorin_data = {r["Key"]: r["Value"] for r in website_content if r.get("Bereich") == "Autorin"}
    socials_data = {r["Key"]: r["Value"] for r in website_content if r.get("Bereich") == "Social"}

    #  In eine neue JSON schreiben (oder in eine bestehende)
    with open(os.path.join(ELEVENTY_DATA_DIR, "autorin.json"), "w", encoding="utf-8") as f:
        json.dump(autorin_data, f, indent=4, ensure_ascii=False)
        
    with open(os.path.join(ELEVENTY_DATA_DIR, "socials.json"), "w", encoding="utf-8") as f:
        json.dump(socials_data, f, indent=4, ensure_ascii=False)

    # 2. JSONs für Eleventy schreiben (aus den Google-Daten)
    os.makedirs(ELEVENTY_DATA_DIR, exist_ok=True)
    
    # Bücher-Liste
    with open(os.path.join(ELEVENTY_DATA_DIR, "books_list.json"), "w", encoding="utf-8") as f:
        json.dump(buecher_liste, f, indent=4, ensure_ascii=False)
        
    # Rezensionen
    with open(os.path.join(ELEVENTY_DATA_DIR, "fokus_rezensionen.json"), "w", encoding="utf-8") as f:
        json.dump(fokus_rezensionen, f, indent=4, ensure_ascii=False)
    
    # Lesungen (Konditionen)
    raw_lesungen = [r for r in website_content if r.get("Bereich") == "Lesungen"]
    formatted_lesungen = {r["Key"]: r["Value"] for r in raw_lesungen}
    with open(os.path.join(ELEVENTY_DATA_DIR, "lesungen.json"), "w", encoding="utf-8") as f:
        json.dump(formatted_lesungen, f, indent=4, ensure_ascii=False)
    
    #FAQs
    raw_faqs = [r for r in website_content if r.get("Bereich") == "FAQ"]
    formatted_faqs = []
    for i in range(1, 6): # Erhöhe den Bereich auf 6, falls du mehr FAQs hast
        suffix = f"00{i}"
        frage = next((r["Value"] for r in raw_faqs if r["Key"] == f"faq_{suffix}_frage"), None)
        antwort = next((r["Value"] for r in raw_faqs if r["Key"] == f"faq_{suffix}_antwort"), None)
        if frage and antwort:
            formatted_faqs.append({"frage": frage, "antwort": antwort})
            
    with open(os.path.join(ELEVENTY_DATA_DIR, "faqs.json"), "w", encoding="utf-8") as f:
        json.dump(formatted_faqs, f, indent=4, ensure_ascii=False)

    #Impressum - HIER WAR DER FEHLER (content -> website_content)
    raw_impressum = [r for r in website_content if r.get("Bereich") == "Impressum"]
    formatted_impressum = {r["Key"]: r["Value"] for r in raw_impressum}
    with open(os.path.join(ELEVENTY_DATA_DIR, "impressum.json"), "w", encoding="utf-8") as f:
        json.dump(formatted_impressum, f, indent=4, ensure_ascii=False)
    print(f"[✅ DATEN] {len(fokus_rezensionen)} Rezensionen & Content aus Google Sheets geladen.")

    #Eleventy HTML-Generierung starten
    print("\n[🛠️ BUILD] Starte Eleventy-Kompilierung...")
    try:
        subprocess.run(["npx", "@11ty/eleventy"], cwd=WEBSITE_DIR, check=True)
    except Exception as e:
        print(f"[🛠️ BUILD] ❌ Eleventy-Fehler: {e}")
        return

    # 💥 4. NEU: Screenshot der lokalen Website schießen statt LLM-Zusammenfassung!
    foto_pfad = capture_website_screenshot("website_vorschau.png")
    
    # 5. Telegram-Vorschau mit Bild senden & auf Knopfdruck warten
    msg_id = send_telegram_proposal_with_image(foto_pfad)

    if msg_id and wait_for_approval(msg_id):

        status = upload_directory_to_ftp()

        if status == "success":
            status_text = "🎉 *PROJEKT LIVE!*\nWebsite erfolgreich hochgeladen:\nwww.anni-lindner.de"

        elif status == "partial":
            status_text = "⚠️ *TEILWEISE ERFOLGREICH*\nEinige Dateien konnten nicht hochgeladen werden.\nWebsite evtl. unvollständig!"

        else:
            status_text = "❌ *FTP-UPLOAD FEHLGESCHLAGEN!*"

        utils.send_telegram(status_text, parse_mode="Markdown")

        # Screenshot löschen
        if foto_pfad and os.path.exists(foto_pfad):
            os.remove(foto_pfad)

    else:
        print("\n🛑 Deployment abgebrochen.")
if __name__ == "__main__":
    main()
