import json
import os
import re
import subprocess
import time
from datetime import datetime
from langchain_ollama import OllamaLLM
import requests

# =====================================================================
# KONFIGURATION & SETUP
# =====================================================================
llm = OllamaLLM(model="llama3:8b", temperature=0.4)

STATUS_FILE = "kampagnen_status.json"
N8N_WEBHOOK_URL = "http://localhost:5678/webhook/marketing-update"

def lade_status():
    if not os.path.exists(STATUS_FILE):
        print(f"❌ Fehler: {STATUS_FILE} nicht gefunden!")
        return None
    with open(STATUS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def speichere_status(data):
    data["letztes_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def generiere_telegram_nachricht(status, event_typ, nischen_liste=None):
    """Lässt Llama 3 eine dynamische, packende Nachricht für die Telegram-Gruppe schreiben."""
    conf = status.get("agenten_konfiguration", {})
    ziel = conf.get("ziel_datenbank_groesse", 50)
    aktuell = conf.get("aktuelle_hochwertige_treffer", 0)
    
    nischen_text = ", ".join(nischen_liste) if nischen_liste else "neue Segmente"

    if event_typ == "zwischenstand":
        prompt = f"""
        Du bist der Chief Marketing Officer (CMO). Schreibe ein kurzes, begeistertes Update für das Autoren-Team über den aktuellen Fortschritt der Recherche-Phase.
        Buch: '{status.get('buchtitel')}' von {status.get('autorin')}.
        Gerade durchsuchte Nischen: {nischen_text}
        Aktueller Zwischenstand im Google Sheet: {aktuell} von {ziel} Top-Treffern erreicht.
        
        Vorgaben:
        - Nutze HTML-Tags wie <b>...</b> für Fettung und • für Aufzählungspunkte.
        - Sei motivierend, professionell und locker.
        - Erinnere das Team kurz daran, dass sie parallel schon im Sheet (unter 'Rohdaten') die Nummern und Mails prüfen können.
        - Füge passende Emojis ein.
        - Antworte NUR mit dem finalen Nachrichtentext, kein 'Hier ist der Text:' oder ähnliches.
        """
    else: # Gesamtziel erreicht
        prompt = f"""
        Du bist der Chief Marketing Officer (CMO). Feiere den Erfolg, dass die Recherche-Phase komplett abgeschlossen ist!
        Buch: '{status.get('buchtitel')}' von {status.get('autorin')}.
        Gesamtergebnis: {aktuell} hochwertige Kontakte wurden erfolgreich im Google Sheet validiert.
        
        Vorgaben:
        - Nutze HTML-Tags für Formatierung (<b>).
        - Gratuliere dem Team herzlich.
        - Weise darauf hin, dass die Datenbank jetzt prall gefüllt ist und im nächsten Schritt (Phase 4) die individuellen Pitches generiert werden können.
        - Füge den folgenden Google-Sheet-Link elegant als HTML-Link am Ende ein: <a href="https://docs.google.com/spreadsheets/d/1_yCynt1scTCWByYJBIxatiw9_KBP-F3WgPn3xRjRb7s/edit?usp=sharing">Hier klicken, um die Google-Tabelle zu öffnen</a>
        - Antworte NUR mit dem finalen Nachrichtentext.
        """
        
    try:
        return llm.invoke(prompt).strip()
    except:
        return f"📢 <b>Update der Agentur:</b> Wir haben einen Zwischenstand von {aktuell}/{ziel} Kontakten erreicht!"

def main():
    print(f"--- 🧠 AUTONOMER CMO & MARKETING DIRECTOR GESTARTET ---")
    
    while True:
        status = lade_status()
        if not status: break

        conf = status.get("agenten_konfiguration", {})
        ziel_groesse = conf.get("ziel_datenbank_groesse", 50)
        aktuelle_treffer = conf.get("aktuelle_hochwertige_treffer", 0)

        print(f"\n📊 Zwischenstand: {aktuelle_treffer}/{ziel_groesse} Top-Treffer im Sheet.")

        # 1. ERFOLGS-CHECK: GESAMTZIEL ERREICHT?
        if aktuelle_treffer >= ziel_groesse:
            print("🎉 DAS ZIEL WURDE ERREICHT! Generiere finale Telegram-Nachricht...")
            for s in status.get("marketing_plan", []):
                if s["id"] == "1": s["status"] = "erledigt"
            speichere_status(status)
            
            # KI textet den feierlichen Abschluss
            tg_text = generiere_telegram_nachricht(status, "abschluss")
            
            payload = {
                "event_typ": "kampagne_recherche_beendet",
                "telegram_text": tg_text
            }
            try: requests.post(N8N_WEBHOOK_URL, json=payload)
            except: print("⚠️ n8n nicht erreichbar.")
            break

        # 2. STRATEGIE-PHASE: Neue Aufgaben planen, falls alles leer ist
        offene_aufgaben = [a for a in status.get("aktuelle_aufgaben", []) if a["status"] in ["bereit_fuer_recherche", "in_recherche"]]
        
        if not offene_aufgaben:
            print("💡 Keine offenen Aufgaben. KI plant die nächsten 3 Nischen...")
            
            aktueller_schritt = None
            for schritt in status.get("marketing_plan", []):
                if schritt["status"] in ["offen", "in_fortschritt"]:
                    aktueller_schritt = schritt
                    break
            
            if not aktueller_schritt: break

            historie = conf.get("historie_suchbegriffe", [])
            prompt = f"""
            Du bist der Chief Marketing Officer (CMO).
            Buch: '{status.get('buchtitel')}' ({status.get('genre')}) von {status.get('autorin')}.
            Bisherige Suchbegriffe: {historie}

            Erstelle 3 neue, völlig unterschiedliche Zielgruppen-Ansätze für die Online-Recherche.
            Liefere für jeden Ansatz eine prägnante Google-Suchquery (3-4 Wörter).

            Antworte NUR im JSON-Format:
            {{
                "aufgaben": [
                    {{"zielgruppen_typ": "Nische 1", "such_query": "suchbegriff 1"}},
                    {{"zielgruppen_typ": "Nische 2", "such_query": "suchbegriff 2"}},
                    {{"zielgruppen_typ": "Nische 3", "such_query": "suchbegriff 3"}}
                ]
            }}
            """
            try:
                antwort_raw = llm.invoke(prompt).strip()
                match = re.search(r'\{.*\}', antwort_raw, re.DOTALL)
                ki_plan = json.loads(match.group(0))
                
                if "aktuelle_aufgaben" not in status: status["aktuelle_aufgaben"] = []
                if "agenten_konfiguration" not in status: 
                    status["agenten_konfiguration"] = {"historie_suchbegriffe": [], "ziel_datenbank_groesse": 50, "aktuelle_hochwertige_treffer": 0}

                aktuelle_nischen = []
                for idx, aufgabe in enumerate(ki_plan["aufgaben"]):
                    status["aktuelle_aufgaben"].append({
                        "id": f"task_{datetime.now().strftime('%m%d%H%M')}_{idx}",
                        "schritt_id": aktueller_schritt["id"],
                        "zielgruppen_typen": [aufgabe["zielgruppen_typ"]],
                        "such_query": aufgabe["such_query"],
                        "status": "bereit_fuer_recherche"
                    })
                    status["agenten_konfiguration"]["historie_suchbegriffe"].append(aufgabe["such_query"])
                    aktuelle_nischen.append(aufgabe["zielgruppen_typ"])

                aktueller_schritt["status"] = "in_fortschritt"
                status["logbuch"].append(f"{datetime.now().strftime('%Y-%m-%d %H:%M')}: Neue Nischen geplant.")
                speichere_status(status)
                
            except Exception as e:
                print(f"❌ Planungsfehler: {e}")
                break

        # 3. EXEKUTIONS-PHASE: Den Pitch-Preparer aufrufen
        print("\n🏃‍♂️ Übergebe an den Recherche-Agenten (pitch_preparer.py)...")
        try:
            subprocess.run(["python3", "pitch_preparer.py"], check=True)
        except subprocess.CalledProcessError as e:
            print(f"⚠️ Fehler im Pitch-Preparer: {e}")
            break
        
        # 4. ZWISCHENSTAND-FUNK: Nach jedem erfolgreichen Lauf der Schleife Telegram updaten
        # Status neu laden, um die Ergebnisse des Preparers zu sehen
        status = lade_status()
        tg_update_text = generiere_telegram_nachricht(status, "zwischenstand", nischen_liste=aktuelle_nischen)
        
        print("📱 Sende Zwischenstand-Bericht an Telegram...")
        payload = {
            "event_typ": "zwischenstand_recherche",
            "telegram_text": tg_update_text
        }
        try: requests.post(N8N_WEBHOOK_URL, json=payload)
        except: pass

        print("⏳ Warte 5 Sekunden vor der nächsten Runde...")
        time.sleep(5)

if __name__ == "__main__":
    main()
