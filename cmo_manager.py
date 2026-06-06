import json
import os
from datetime import datetime
from langchain_ollama import OllamaLLM
import requests

# =====================================================================
# KONFIGURATION & SETUP
# =====================================================================

# Verbindung zum lokalen Ollama-Modell herstellen
llm = OllamaLLM(model="llama3:8b", temperature=0.4)

STATUS_FILE = "kampagnen_status.json"
ANWEISUNG_FILE = "aktuelle_anweisung.txt"

# ERSETZE DIESE URL MIT DEINER KOPIERTEN TEST-URL AUS N8N!
N8N_WEBHOOK_URL = "http://localhost:5678/webhook-test/marketing-update"

# =====================================================================
# HILFSFUNKTIONEN
# =====================================================================

def lade_status():
    """Lädt die lokale JSON-Statusdatei."""
    if not os.path.exists(STATUS_FILE):
        print(f"Fehler: {STATUS_FILE} nicht gefunden! Bitte stelle sicher, dass die Datei im selben Ordner liegt.")
        return None
    with open(STATUS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def speichere_status(data):
    """Speichert den aktualisierten Zustand zurück in die JSON-Datei."""
    data["letztes_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# =====================================================================
# HAUPTPROGRAMM
# =====================================================================

def main():
    # 1. Status laden
    status = lade_status()
    if not status:
        return

    # 2. Dynamisch den ersten offenen Schritt aus dem Marketing-Plan suchen
    aktueller_schritt = None
    if "marketing_plan" in status:
        for schritt in status["marketing_plan"]:
            if schritt["status"] == "offen":
                aktueller_schritt = schritt
                break

    if not aktueller_schritt:
        print("💡 Alle geplanten Schritte sind erledigt oder kein offener Schritt im 'marketing_plan' gefunden!")
        return

    schritt_id = aktueller_schritt["id"]
    schritt_name = aktueller_schritt["titel"]
    schritt_beschreibung = aktueller_schritt["beschreibung"]
    
    print(f"--- DYNAMISCHER KAMPAGNEN MANAGER GESTARTET ---")
    print(f"Buch: '{status['buch_titel']}' von {status['autorin']}")
    print(f"Aktueller Fokus: [{schritt_id}] - {schritt_name}")
    print(f"Beschreibung: {schritt_beschreibung}\n")
    print("🤖 Rufe den KI-Strategen auf (Bitte warten, CPU arbeitet)...")

    # 3. Strategischen Prompt an das lokale LLM senden
    prompt = f"""
    Du bist der Chief Marketing Officer (CMO) für ein Buchmarketing-System.
    
    Aktuelle Kampagnen-Daten:
    - Buch-Titel: {status['buch_titel']}
    - Genre: {status['genre']}
    - Autorin: {status['autorin']}
    - Aktueller Fokus: Schritt {schritt_id} ({schritt_name})
    - Beschreibung: {schritt_beschreibung}
    
    Deine Aufgabe:
    Erstelle einen strategischen Arbeitsplan für diesen Schritt auf Deutsch.
    Teile deine Antwort zwingend in zwei Bereiche auf:
    1. HINTERGRUND: Warum ist dieser Schritt wichtig für das Buch '{status['buch_titel']}'?
    2. AKTIONEN: Eine nummerierte Liste mit exakten Aufgaben für das KI-Recherche-Team (z.B. nach welchen spezifischen Inhalten gesucht werden soll).
    """

    antwort = llm.invoke(prompt)
    
    print("\n--- ANWEISUNG GENERIERT ---")
    print(antwort)
    print("-------------------------------------------")

    # 4. Lokale Textdatei als Backup/Einsicht für dich speichern
    with open(ANWEISUNG_FILE, "w", encoding="utf-8") as f:
        f.write(f"Generiert am: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Fokus: Schritt {schritt_id} - {schritt_name}\n")
        f.write("="*40 + "\n\n")
        f.write(antwort)
    print(f"💾 Text-Anweisung lokal gespeichert in: {ANWEISUNG_FILE}")

    # 5. Daten live an die n8n-Zentrale senden
    payload = {
        "buch_titel": status["buch_titel"],
        "schritt_id": schritt_id,
        "schritt_name": schritt_name,
        "anweisung_text": antwort
    }
    
    try:
        print("🌐 Sende Daten an n8n Webhook...")
        response = requests.post(N8N_WEBHOOK_URL, json=payload)
        if response.status_code == 200:
            print("🚀 [Erfolg] n8n hat die Daten erfolgreich empfangen!")
        else:
            print(f"⚠️ [Warnung] n8n hat geantwortet, aber mit Statuscode: {response.status_code}")
    except Exception as e:
        print(f"❌ [Fehler] Verbindung zu n8n fehlgeschlagen. Läuft der Webhook-Node im 'Listen'-Modus? Fehler: {e}")

    # 6. Logbuch und Aufgabenstatus in der JSON-Datei aktualisieren
    eintrag = f"Strategischer Plan für '{schritt_name}' erstellt und an n8n übertragen."
    status["logbuch"].append(f"{datetime.now().strftime('%Y-%m-%d %H:%M')}: {eintrag}")
    
    if "aktuelle_aufgaben" not in status:
        status["aktuelle_aufgaben"] = []
        
    status["aktuelle_aufgaben"].append({
        "schritt_id": schritt_id,
        "erstellt_am": datetime.now().strftime('%Y-%m-%d %H:%M'),
        "status": "bereit_fuer_recherche"
    })
    
    speichere_status(status)
    print("📝 Zustand und Logbuch in 'kampagnen_status.json' aktualisiert.")

if __name__ == "__main__":
    main()
