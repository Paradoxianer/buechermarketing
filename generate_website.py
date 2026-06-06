import json
import os
import shutil
import subprocess
import zipfile
import requests
import time
import csv
import utils_system as utils
from ftplib import FTP, error_perm

TAB_CLIPPINGS = "Rezension"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODELL = "llama3:8b"
FTP_IGNORE_DIRS = ["lindner", "stammbaum"]

FAQ_SOURCE_FILE = "agentur_wissen/faq_katalog.json"
BILDER_SOURCE_DIR = "agentur_wissen/bilder"
WEBSITE_DIR = "autoren_website"
LOCAL_BUILD_DIR = os.path.join(WEBSITE_DIR, "_site")
ELEVENTY_DATA_DIR = os.path.join(WEBSITE_DIR, "src", "_data")
ELEVENTY_IMAGES_DIR = os.path.join(WEBSITE_DIR, "src", "images")
ELEVENTY_DOWNLOADS_DIR = os.path.join(WEBSITE_DIR, "src", "downloads")

AUTHOR_IMAGE_NAME = "anni-lindner.png"
PRESSKIT_ZIP_NAME = "Anni_E_Lindner_Pressekit.zip"
PRESSKIT_WORK_DIR = os.path.join(WEBSITE_DIR, "tmp_presskit")

AUTHOR_SHORT_BIO = (
    "Anni E. Lindner, geboren 1980 in Freiberg/Sachsen, ist Schriftstellerin und Heilsarmeeoffizierin. "
    "Nach ihrer Ausbildung zur Krankenschwester studierte sie Religionspädagogik sowie Praktische Theologie. "
    "Heute lebt sie in Chemnitz, ist verheiratet und Mutter von sechs Kindern. In ihren Kinder- und Jugendbüchern "
    "verbindet sie starke Geschichten mit Wertefragen, Alltagsnähe und emotionaler Tiefe."
)

AUTHOR_LONG_BIO = (
    "Anni E. Lindner (*1980 in Freiberg) ist deutsche Schriftstellerin und Heilsarmeeoffizierin. "
    "Aufgewachsen im Randerzgebirge, absolvierte sie zunächst eine Ausbildung zur Krankenschwester, bevor sie "
    "an der Evangelischen Hochschule Moritzburg Religionspädagogik und Gemeindediakonie studierte. Anschließend "
    "folgte ein Studium der Praktischen Theologie am Institut für Gemeindebau und Weltmission. Seither ist sie als "
    "Offizierin der Heilsarmee an unterschiedlichen Orten in Deutschland tätig.\n\n"
    "Parallel zu ihrer beruflichen Arbeit schreibt sie Romane für Kinder, Jugendliche und junge Erwachsene. "
    "Ihre Geschichten entstehen aus genauen Alltagsbeobachtungen, aus Begegnungen, aus Fragen nach Identität, "
    "Freundschaft, Verantwortung und Liebe. Lindner gelingt es, gesellschaftliche Themen, emotionale Entwicklungen "
    "und Wertefragen so miteinander zu verbinden, dass ihre Bücher sowohl im christlichen Kontext als auch im "
    "allgemeinen Buchmarkt anschlussfähig sind.\n\n"
    "Seit ihrer ersten Buchveröffentlichung im Jahr 2012 hat sie mehrere Titel im Bereich Kinder- und Jugendliteratur "
    "publiziert. Dazu zählen unter anderem die Trilogie um Franzi und Burg Rosenfels, das Jugendbuch "
    "‚Die Wahrheit schmeckt nach Marzipan‘ sowie das Kinderbuch ‚Wie wir die Welt retten wollten und dabei aus Versehen "
    "das Bernsteinzimmer fanden‘. Ihr Anliegen ist es, Bücher mit Haltung und Werten auch in weltlichen Buchhandlungen "
    "sichtbar zu machen."
)


def fetch_google_sheet_by_name(sheet_name):
    try:
        print(f"[📊 SPREADSHEET] Lade Daten aus Tab: {sheet_name}...", flush=True)
        return utils.get_sheet_data(sheet_name)
    except Exception as e:
        print(f"[❌ SPREADSHEET] Fehler beim Laden: {e}")
        return None


def ask_llama_for_preview(fokus_buch, rezensionen):
    print(f"\n[🦙 LLAMA-MODUL] Generiere präzisen Änderungs-Auszug mit '{OLLAMA_MODELL}'...")
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

    return f"📖 Fokus-Buch: {fokus_buch.get('titel')}\n💬 Rezensionen: {len(rezensionen)} Stück geladen."


def pick_value(row, keys, default=""):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return default


def safe_write_text(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.strip() + "\n")


def format_book_facts(book):
    return (
        f"Titel: {book.get('titel', '')}\n"
        f"Autorin: Anni E. Lindner\n"
        f"Genre: {book.get('genre', '')}\n"
        f"Erscheinungstermin: {book.get('erscheinungsdatum', '')}\n"
        f"Altersempfehlung: {book.get('altersempfehlung', '')}\n"
        f"Umfang: {book.get('seitenanzahl', '')}\n"
        f"Preis: {book.get('preis_print', '')}\n"
        f"ISBN: {book.get('isbn_print', '')}\n"
        f"Amazon: {book.get('amazon_link', '')}\n"
        f"LovelyBooks: {book.get('lovelybooks_url', '')}\n"
        f"Website: https://www.anni-lindner.de\n"
    )


def build_book_press_text(book):
    description = book.get("beschreibung", "")
    title = book.get("titel", "What is Love?")
    genre = book.get("genre", "Jugendroman")
    return (
        f"{title} ist ein {genre.lower()}, der Fragen nach Liebe, Identität, Selbstbild und echter Beziehung in die Gegenwart junger Menschen holt. "
        f"Im Zentrum steht die 17-jährige Sophia, eine christliche Influencerin, die mit scheinbar perfekten Beziehungstipps bekannt geworden ist – "
        f"und doch selbst merkt, dass Liebe komplizierter ist als jedes idealisierte Onlinebild.\n\n"
        f"Vor dem Setting eines Schulcampus erzählt der Roman von Freundschaft, Unsicherheit, Sehnsucht, Missverständnissen und davon, wie Jugendliche "
        f"versuchen herauszufinden, was eine tragfähige Beziehung wirklich ausmacht. Das Buch verbindet Social-Media-Gegenwart, emotionale Dynamik und "
        f"werteorientierte Fragen auf eine Weise, die sowohl christliche als auch allgemeine Leserinnen und Leser anspricht.\n\n"
        f"Klappentext / Beschreibung:\n{description}"
    )


def build_press_questions(book):
    title = book.get("titel", "What is Love?")
    return (
        f"Mögliche Themen für Berichterstattung, Interviews und Bloggerbeiträge zu {title}:\n\n"
        f"- Liebe und Beziehungsbilder im Jugendalter\n"
        f"- Wie Social Media Erwartungen an Beziehungen prägt\n"
        f"- Werteorientierte Jugendliteratur für den allgemeinen Buchmarkt\n"
        f"- Christliche Perspektiven in zeitgenössischen Jugendromanen\n"
        f"- Schreiben zwischen Familienalltag, Berufung und Literatur\n"
        f"- Lesungen und Workshops für Schulen, Bibliotheken und Buchhandlungen\n"
    )


def build_press_overview(book, socials, website_content):
    instagram = socials.get("insta_link", "")
    return (
        "PRESSEINFORMATION\n"
        "=================\n\n"
        f"Autorin: Anni E. Lindner\n"
        f"Titel: {book.get('titel', '')}\n"
        f"Genre: {book.get('genre', '')}\n"
        f"Website: https://www.anni-lindner.de\n"
        f"Instagram: {instagram}\n"
        f"Kontakt für Presseanfragen: info@anni-lindner.de\n\n"
        "Dieses Pressekit enthält Autorinneninformationen, Buchinformationen, Bildmaterial und Fakten zum aktuellen Fokusbuch. "
        "Rezensionsexemplare, Interviewanfragen sowie Anfragen für Lesungen und Veranstaltungen sind per E-Mail willkommen.\n"
    )


def copy_if_exists(src, dst):
    if src and os.path.exists(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        return True
    return False


def build_presskit(fokus_buch, website_content):
    print("[📦 PRESSEKIT] Erzeuge hochwertiges Pressekit...")
    os.makedirs(ELEVENTY_DOWNLOADS_DIR, exist_ok=True)

    if os.path.exists(PRESSKIT_WORK_DIR):
        shutil.rmtree(PRESSKIT_WORK_DIR)
    os.makedirs(PRESSKIT_WORK_DIR, exist_ok=True)

    socials = {r["Key"]: r["Value"] for r in website_content if r.get("Bereich") == "Social"}
    lesungen = {r["Key"]: r["Value"] for r in website_content if r.get("Bereich") == "Lesungen"}

    safe_write_text(
        os.path.join(PRESSKIT_WORK_DIR, "00_Presseinfo_Anni_E_Lindner.txt"),
        build_press_overview(fokus_buch, socials, website_content),
    )
    safe_write_text(
        os.path.join(PRESSKIT_WORK_DIR, "01_Autorin_Kurzbio.txt"),
        AUTHOR_SHORT_BIO,
    )
    safe_write_text(
        os.path.join(PRESSKIT_WORK_DIR, "02_Autorin_Langbio.txt"),
        AUTHOR_LONG_BIO,
    )
    safe_write_text(
        os.path.join(PRESSKIT_WORK_DIR, f"03_Buchinfo_{fokus_buch.get('titel', 'Buch').replace(' ', '_').replace('?', '')}.txt"),
        build_book_press_text(fokus_buch),
    )
    safe_write_text(
        os.path.join(PRESSKIT_WORK_DIR, f"04_Faktenblatt_{fokus_buch.get('titel', 'Buch').replace(' ', '_').replace('?', '')}.txt"),
        format_book_facts(fokus_buch),
    )
    safe_write_text(
        os.path.join(PRESSKIT_WORK_DIR, "05_Pressefragen_und_Themen.txt"),
        build_press_questions(fokus_buch),
    )
    safe_write_text(
        os.path.join(PRESSKIT_WORK_DIR, "06_Lesungen_und_Veranstaltungen.txt"),
        (
            "LESUNGEN & VERANSTALTUNGEN\n"
            "==========================\n\n"
            f"Buchbar für: {lesungen.get('buchbar_fuer', '')}\n"
            f"Honorarbasis: {lesungen.get('honorar_basis', '')}\n"
            f"Technik-Anforderung: {lesungen.get('technik_anforderung', '')}\n"
            "Anfragen bitte per E-Mail an info@anni-lindner.de\n"
        ),
    )

    cover_name = fokus_buch.get("cover_datei", "")
    cover_src = os.path.join(BILDER_SOURCE_DIR, cover_name) if cover_name else ""
    author_src = os.path.join(BILDER_SOURCE_DIR, AUTHOR_IMAGE_NAME)

    copied_cover = copy_if_exists(cover_src, os.path.join(PRESSKIT_WORK_DIR, "bilder", cover_name or "cover.png"))
    copied_author = copy_if_exists(author_src, os.path.join(PRESSKIT_WORK_DIR, "bilder", AUTHOR_IMAGE_NAME))

    if copied_author:
        safe_write_text(
            os.path.join(PRESSKIT_WORK_DIR, "bilder", "bildnachweis.txt"),
            "Autorenfoto: Anni E. Lindner (© Foto: Maggie Renger)\nCover: bereitgestellt für Presse, Rezensionen und Berichterstattung.",
        )

    zip_path = os.path.join(ELEVENTY_DOWNLOADS_DIR, PRESSKIT_ZIP_NAME)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(PRESSKIT_WORK_DIR):
            for file in files:
                full_path = os.path.join(root, file)
                arcname = os.path.relpath(full_path, PRESSKIT_WORK_DIR)
                zf.write(full_path, arcname)

    print(f"[📦 PRESSEKIT] ZIP erstellt: {zip_path}")
    return zip_path


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
                time.sleep(1.5)
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
    for local_path, remote_dir, filename in all_files:
        upload_single_file(local_path, remote_dir, filename, max_attempts=3)

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
    abs_path = os.path.abspath(image_path)
    print(f"[📱 TELEGRAM] Suche Bilddatei unter: {abs_path}")
    if not image_path or not os.path.exists(image_path):
        print(f"[❌ FEHLER] Bilddatei nicht gefunden: {image_path}")
        return None

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
                    "inline_keyboard": [[
                        {"text": "🚀 Ja, FTP-Upload!", "callback_data": "deploy_yes"},
                        {"text": "🛑 Abbrechen", "callback_data": "reject"}
                    ]]
                })
            }
            response = requests.post(url, files=files, data=data)
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
    url = f"https://api.telegram.org/bot{utils.TELEGRAM_TOKEN}/getUpdates"
    offset = None
    try:
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
    print("[📸 SCREENSHOT] Starte Browser-Modul für visuelle Vorschau...", flush=True)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            local_html_path = os.path.abspath(os.path.join(LOCAL_BUILD_DIR, "index.html"))
            page.goto(f"file://{local_html_path}")
            page.wait_for_timeout(1000)
            page.set_viewport_size({"width": 1280, "height": 900})
            page.screenshot(path=output_path, full_page=True)
            browser.close()
        print("   ✅ Screenshot erfolgreich generiert!", flush=True)
        return output_path
    except Exception as e:
        print(f"   ❌ Screenshot-Fehler: {e}", flush=True)
        return None


def main():
    print("=" * 60)
    print("🏗️ START DES WEBMASTER-AGENTS (GOOGLE-TABELLEN MODUS)")
    print("=" * 60)
    print("[📊 DATEN] Lade aktuelle Inhalte aus Google Sheets...")

    buecher_liste = utils.get_sheet_data("Books")
    allgemeines = utils.get_sheet_data("Allgemeines")
    website_content = utils.get_sheet_data("Website_Content")
    clippings_raw = utils.get_sheet_data("Rezension")

    buecher_liste.sort(key=lambda x: x.get("erscheinungsdatum", "0000-00-00"), reverse=True)
    fokus_buch = buecher_liste[0] if buecher_liste else {}

    fokus_rezensionen = []
    if clippings_raw:
        for row in clippings_raw:
            if str(row.get("Status", "")).lower() == "veröffentlicht":
                fokus_rezensionen.append({
                    "text": row.get("Zitat") or "",
                    "autor": row.get("Medium/Name") or "Anonym",
                    "plattform": row.get("Typ") or "Web",
                    "link": row.get("Link") or ""
                })

    autorin_data = {r["Key"]: r["Value"] for r in website_content if r.get("Bereich") == "Autorin"}
    socials_data = {r["Key"]: r["Value"] for r in website_content if r.get("Bereich") == "Social"}

    os.makedirs(ELEVENTY_DATA_DIR, exist_ok=True)
    with open(os.path.join(ELEVENTY_DATA_DIR, "autorin.json"), "w", encoding="utf-8") as f:
        json.dump(autorin_data, f, indent=4, ensure_ascii=False)
    with open(os.path.join(ELEVENTY_DATA_DIR, "socials.json"), "w", encoding="utf-8") as f:
        json.dump(socials_data, f, indent=4, ensure_ascii=False)
    with open(os.path.join(ELEVENTY_DATA_DIR, "books_list.json"), "w", encoding="utf-8") as f:
        json.dump(buecher_liste, f, indent=4, ensure_ascii=False)
    with open(os.path.join(ELEVENTY_DATA_DIR, "fokus_rezensionen.json"), "w", encoding="utf-8") as f:
        json.dump(fokus_rezensionen, f, indent=4, ensure_ascii=False)

    raw_lesungen = [r for r in website_content if r.get("Bereich") == "Lesungen"]
    formatted_lesungen = {r["Key"]: r["Value"] for r in raw_lesungen}
    with open(os.path.join(ELEVENTY_DATA_DIR, "lesungen.json"), "w", encoding="utf-8") as f:
        json.dump(formatted_lesungen, f, indent=4, ensure_ascii=False)

    raw_faqs = [r for r in website_content if r.get("Bereich") == "FAQ"]
    formatted_faqs = []
    for i in range(1, 6):
        suffix = f"00{i}"
        frage = next((r["Value"] for r in raw_faqs if r["Key"] == f"faq_{suffix}_frage"), None)
        antwort = next((r["Value"] for r in raw_faqs if r["Key"] == f"faq_{suffix}_antwort"), None)
        if frage and antwort:
            formatted_faqs.append({"frage": frage, "antwort": antwort})
    with open(os.path.join(ELEVENTY_DATA_DIR, "faqs.json"), "w", encoding="utf-8") as f:
        json.dump(formatted_faqs, f, indent=4, ensure_ascii=False)

    raw_impressum = [r for r in website_content if r.get("Bereich") == "Impressum"]
    formatted_impressum = {r["Key"]: r["Value"] for r in raw_impressum}
    with open(os.path.join(ELEVENTY_DATA_DIR, "impressum.json"), "w", encoding="utf-8") as f:
        json.dump(formatted_impressum, f, indent=4, ensure_ascii=False)

    print(f"[✅ DATEN] {len(fokus_rezensionen)} Rezensionen & Content aus Google Sheets geladen.")

    build_presskit(fokus_buch, website_content)

    print("\n[🛠️ BUILD] Starte Eleventy-Kompilierung...")
    try:
        subprocess.run(["npx", "@11ty/eleventy"], cwd=WEBSITE_DIR, check=True)
    except Exception as e:
        print(f"[🛠️ BUILD] ❌ Eleventy-Fehler: {e}")
        return

    foto_pfad = capture_website_screenshot("website_vorschau.png")
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
        if foto_pfad and os.path.exists(foto_pfad):
            os.remove(foto_pfad)
    else:
        print("\n🛑 Deployment abgebrochen.")


if __name__ == "__main__":
    main()
