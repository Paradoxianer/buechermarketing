import json
import os
import time
from datetime import datetime
import requests
from ddgs import DDGS

STATUS_FILE = "kampagnen_status.json"
# WICHTIG: Nutze hier deine n8n Produktions-URL (ohne -test)
N8N_WEBHOOK_URL = "http://localhost:5678/webhook/marketing-update"

def lade_status():
    if not os.path.exists(STATUS_FILE):
        print(f"Fehler: {STATUS_FILE} nicht gefunden!")
        return None
    with open(STATUS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def speichere_status(data):
    data["letztes_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def main():
    status = lade_status()
    if not status:
        return
    
    # 1. Dynamisch prüfen, welche Recherche-Aufgabe ansteht und welche Typen gesucht werden sollen
    aufgabe_gefunden = None
    zielgruppen_typen = []
    
    if "aktuelle_aufgaben" in status:
        for aufgabe in status["aktuelle_aufgaben"]:
            if aufgabe["status"] == "bereit_fuer_recherche" or aufgabe["status"] == "in_recherche":
                aufgabe_gefunden = aufgabe
                aufgabe["status"] = "in_recherche"
                # Hol dir die von der KI dynamisch festgelegten Typen (Fallback, falls das Feld noch fehlt)
                zielgruppen_typen = aufgabe.get("zielgruppen_typen", ["Buchblogger Romantik", "Jugendmagazine Kultur"])
                break
                
    if not aufgabe_gefunden:
        print("💡 Keine offenen Recherche-Aufgaben in der Warteschlange gefunden.")
        return

    speichere_status(status)
    print("🕵️ Dynamischer Recherche-Agent gestartet...")
    print(f"Buchtitel: {status.get('buchtitel', 'Unbekannt')} | Genre: {status.get('genre', 'Unbekannt')}")
    print(f"Folgende Zielgruppen werden jetzt KI-gesteuert gesucht: {zielgruppen_typen}\n")

    alle_ergebnisse = []
    
    # 2. Die von der KI vorgegebenen Suchbegriffe dynamisch abarbeiten
    try:
        with DDGS() as ddgs:
            for typ in zielgruppen_typen:
                # Wir bauen die Suchanfrage dynamisch aus dem Typen
                query = f"{typ} rezension kontakt"
                print(f"🔎 Suche im Netz nach ({typ}): '{query}'...")
                
                try:
                    results = list(ddgs.text(query, max_results=8)) # Etwas mehr Ergebnisse erlauben
                    if results:
                        print(f"   -> {len(results)} Rohdaten-Treffer erzielt.")
                        for r in results:
                            # Wir bereiten das Datenformat exakt für deine Google-Sheets-Spalten vor!
                            alle_ergebnisse.append({
                                "Typ": typ,
                                "Medium/Name": r.get("title", "Unbekannt"),
                                "URL": r.get("href", ""),
                                "Beschreibung": r.get("body", "")[:300], # Gekürzt für die Tabelle
                                "E-Mail": "Wird händisch geprüft", # Platzhalter für dich zum Ausfüllen
                                "Status": "Neu erfasst"
                            })
                    else:
                        print("   -> Keine Ergebnisse für diesen Begriff.")
                except Exception as search_error:
                    print(f"   ⚠️ Fehler bei Teilsuche für '{typ}': {search_error}")
                
                # Schutz-Pause gegen Google/DuckDuckGo Blockaden
                time.sleep(3)
                
    except Exception as e:
        print(f"❌ Allgemeiner Fehler bei der DDGS-Initialisierung: {e}")

    if not alle_ergebnisse:
        print("⚠️ Keine Ergebnisse gefunden. Breche ab.")
        return

    # 3. DAS SIGNAL: Wir senden die gesamte Liste als ein einziges Paket an n8n
    payload = {
        "event_typ": "recherche_abgeschlossen",
        "buchtitel": status.get("buchtitel", "What is Love?"),
        "daten_liste": alle_ergebnisse # Hier steckt das gesamte Array drin!
    }

    try:
        print(f"\n🚀 Sende Signal und {len(alle_ergebnisse)} Kontakte gesammelt an n8n...")
        response = requests.post(N8N_WEBHOOK_URL, json=payload)
        
        if response.status_code == 200:
            print("✅ Signal erfolgreich an n8n übermittelt!")
            
            # Status auf erledigt setzen
            aufgabe_gefunden["status"] = "recherche_erledigt"
            aufgabe_gefunden["beendet_am"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            status["logbuch"].append(f"{datetime.now().strftime('%Y-%m-%d %H:%M')}: Recherche für {len(zielgruppen_typen)} Typen beendet. Signal an n8n gesendet.")
            speichere_status(status)
        else:
            print(f"⚠️ n8n hat das Signal abgewiesen (Statuscode: {response.status_code})")
            
    except Exception as e:
        print(f"❌ n8n-Webhook konnte nicht erreicht werden: {e}")

if __name__ == "__main__":
    main()
