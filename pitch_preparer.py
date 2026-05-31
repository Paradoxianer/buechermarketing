import json
import os
import re
import time
import urllib.request
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from langchain_ollama import OllamaLLM
from ddgs import DDGS

# 🟢 GOOGLE CONFIGURATION
GOOGLE_JSON_KEYFILE = "DEIN_GOOGLE_SCHLUESSEL.json"
GOOGLE_SPREADSHEET_NAME = "Buchmarketing_Research"

llm = OllamaLLM(model="llama3:8b", temperature=0.1)
STATUS_FILE = "kampagnen_status.json"
N8N_WEBHOOK_URL = "http://localhost:5678/webhook/marketing-update"

WHITELIST_DOMAINS = ["faz.net", "stern.de", "spiegel.de", "zeit.de", "welt.de", "sueddeutsche.de"]

def extrahiere_telefonnummern(text):
    pattern = r'(?:\+49|0)[1-9][0-9]{1,4}[ \-\/]*[0-9]{3,10}'
    treffer = re.findall(pattern, text)
    return list(set([nr.strip() for nr in treffer if len(re.sub(r'\D', '', nr)) >= 6]))

def schreibe_in_google_sheet(daten_liste):
    try:
        import gspread
        from oauth2client.service_account import ServiceAccountCredentials
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_JSON_KEYFILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open(GOOGLE_SPREADSHEET_NAME).worksheet("Rohdaten")
        
        zeilen_fuer_sheet = []
        for d in daten_liste:
            zeilen_fuer_sheet.append([d["Typ"], d["Medium/Name"], d["URL"], d["Beschreibung"], d["E-Mail"], d["Telefon"], d["Ansprechpartner"], d["Score"], d["Status"]])
        sheet.append_rows(zeilen_fuer_sheet)
        return len(zeilen_fuer_sheet)
    except Exception as e:
        print(f"❌ Google Sheet Fehler: {e}")
        return 0

def scrape_website(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            soup = BeautifulSoup(response.read(), 'html.parser')
            for s in soup(["script", "style"]): s.extract()
            return " ".join(soup.get_text().split())[:4000]
    except: return None

def main():
    if not os.path.exists(STATUS_FILE): return
    with open(STATUS_FILE, "r", encoding="utf-8") as f: status = json.load(f)

    # Finde ALLE offenen Aufgaben
    aufgaben_zum_abarbeiten = [a for a in status.get("aktuelle_aufgaben", []) if a["status"] == "bereit_fuer_recherche"]
    
    if not aufgaben_zum_abarbeiten:
        print("💡 Keine offenen Recherche-Aufträge vorhanden.")
        return

    top_treffer_gesamt = 0
    
    for aufgabe in aufgaben_zum_abarbeiten:
        aufgabe["status"] = "in_recherche"
        query = aufgabe["such_query"]
        typ = aufgabe["zielgruppen_typen"][0]
        
        print(f"\n🚀 Starte aktive Recherche für Segment: {typ} ('{query}')")
        
        roh_treffer = []
        with DDGS() as ddgs:
            try:
                results = list(ddgs.text(query, max_results=10)) # 10 Treffer pro Nische
                for r in results: roh_treffer.append({"typ": typ, "titel": r.get("title", "Unbekannt"), "url": r.get("href", "")})
            except Exception as e: print(f"⚠️ Suchfehler: {e}")

        gewertete_kontakte = []
        for treffer in roh_treffer:
            url = treffer["url"]
            if not url or any(d in url.lower() for d in WHITELIST_DOMAINS): continue
            
            text = scrape_website(url)
            if not text: continue

            emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
            email = emails[0] if emails else "Manuell suchen"
            nums = extrahiere_telefonnummern(text)
            tel = nums[0] if nums else "Nicht gefunden"

            prompt = f"Bewerte Relevanz für ein Jugendbuch (Genre: {status.get('genre')}) von 0-100. Antworte NUR als JSON: {{\"score\": 85, \"begruendung\": \"...\", \"ansprechpartner\": \"...\"}} Text: {text[:1500]}"
            try:
                ki_raw = llm.invoke(prompt).strip()
                match = re.search(r'\{.*\}', ki_raw, re.DOTALL)
                ki_daten = json.loads(match.group(0))
                score = int(ki_daten.get("score", 0))
                
                if score >= 40:
                    status_text = "Top-Treffer" if score >= 80 else "Manuell prüfen"
                    if score >= 80: top_treffer_gesamt += 1
                    gewertete_kontakte.append({
                        "Typ": typ, "Medium/Name": treffer["titel"], "URL": url, "Beschreibung": ki_daten.get("begruendung"),
                        "E-Mail": email, "Telefon": tel, "Ansprechpartner": ki_daten.get("ansprechpartner", "Unbekannt"), "Score": score, "Status": status_text
                    })
            except: pass
            time.sleep(1)

        if gewertete_kontakte:
            schreibe_in_google_sheet(gewertete_kontakte)
        
        aufgabe["status"] = "recherche_erledigt"
        aufgabe["beendet_am"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Counter updaten
    conf = status.get("agenten_konfiguration", {})
    conf["aktuelle_hochwertige_treffer"] = conf.get("aktuelle_hochwertige_treffer", 0) + top_treffer_gesamt
    
    # Prüfen, ob Gesamtziel erreicht
    if conf["aktuelle_hochwertige_treffer"] >= conf.get("ziel_datenbank_groesse", 50):
        for s in status["marketing_plan"]:
            if s["id"] == "1": s["status"] = "erledigt"

    with open(STATUS_FILE, "w", encoding="utf-8") as f: json.dump(status, f, indent=4, ensure_ascii=False)

    # 🚀 ENDSIGNAL AN N8N FÜR TELEGRAM SENDEN
    payload = {
        "event_typ": "recherche_abgeschlossen",
        "buchtitel": status.get("buchtitel", "What is Love?"),
        "ziel_groesse": conf.get("ziel_datenbank_groesse", 50),
        "gefundene_treffer": conf["aktuelle_hochwertige_treffer"]
    }
    try:
        requests.post(N8N_WEBHOOK_URL, json=payload)
        print("✅ Signal an n8n übermittelt!")
    except:
        print("⚠️ n8n nicht erreichbar.")

if __name__ == "__main__":
    main()
