import json
import os
from datetime import datetime
from langchain_ollama import OllamaLLM
import requests

# Verbindung zur KI (diesmal etwas kreativer eingestellt mit temp=0.7)
llm = OllamaLLM(model="llama3:8b", temperature=0.7)

VALIDATED_FILE = "geprüfte_kontakte.json"
PITCH_DIR = "fertige_pitches"
STATUS_FILE = "kampagnen_status.json"

# Deine n8n Test-Webhook-URL (für die Live-Meldung auf dem Handy)
N8N_WEBHOOK_URL = "http://localhost:5678/webhook/marketing-update"

if not os.path.exists(PITCH_DIR):
    os.makedirs(PITCH_DIR)

def lade_kontakte():
    if not os.path.exists(VALIDATED_FILE):
        print(f"Fehler: {VALIDATED_FILE} nicht gefunden! Starte erst den pitch_preparer.py.")
        return []
    with open(VALIDATED_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def speichere_status_log(eintrag):
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            status = json.load(f)
        status["logbuch"].append(f"{datetime.now().strftime('%Y-%m-%d %H:%M')}: {eintrag}")
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(status, f, indent=4, ensure_ascii=False)

def main():
    kontakte = lade_kontakte()
    # Nur Kontakte bearbeiten, für die noch kein Pitch generiert wurde
    zu_texten = [k for k in kontakte if "pitch_erstellt" not in k]

    if not zu_texten:
        print("💡 Alle verifizierten Kontakte haben bereits ein fertiges Anschreiben!")
        return

    print(f"✍️ Generiere maßgeschneiderte Anschreiben für {len(zu_texten)} Kontakte...\n")

    # Buchdetails für den Kontext (wird für den Pitch benötigt)
    buch_titel = "What is Love?"
    autorin = "Anni E. Lindner"
    genre = "Jugendbuch / Romantik"

    for kontakt in zu_texten:
        titel = kontakt["titel"]
        url = kontakt["url"]
        typ = kontakt["typ"]
        name = kontakt["ansprechpartner"]
        email = kontakt["email"]
        
        print(f"📝 Schreibe Pitch für: {titel} ({typ})...")

        # Dynamischer Regel-Prompt je nach Typ
        if typ == "Presse/Magazin":
            anrede = f"Sehr geehrte Damen und Herren," if name == "Unbekannt" else f"Sehr geehrte(r) Frau/Herr {name},"
            tonfall_regeln = f"""
            - Nutze ein professionelles, höfliches 'Sie'.
            - Biete einen klaren journalistischen Newswert (z.B. Regionale Autorin veröffentlicht packenden Jugendroman über die Generation Z).
            - Betone, dass ein Rezensionsexemplar oder Interview-Möglichkeit bereitsteht.
            """
        else: # Buchblogger
            anrede = "Hallo," if name == "Unbekannt" else f"Hallo {name},"
            tonfall_regeln = f"""
            - Nutze ein begeistertes,社区-nahes 'Du' auf Augenhöhe.
            - Zeige Interesse an ihrem Blog/Kanal.
            - Biete ein kostenloses Leseexemplar (Print/E-Book) und ggf. Goodies für ein Gewinnspiel für ihre Follower an.
            """

        prompt = f"""
        Du bist eine professionelle PR-Agentin für Buchmarketing. Schreibe eine packende Pitch-E-Mail für folgendes Buch:
        - Titel: {buch_titel}
        - Autorin: {autorin}
        - Genre: {genre}
        
        Der Empfänger ist ein {typ} mit dem Namen/Titel: '{titel}'.
        Anrede-Formel: {anrede}
        
        Wichtige Stil-Regeln für diesen Empfänger-Typ:
        {tonfall_regeln}
        
        Inhalt der E-Mail:
        1. Ein interessanter Einstieg, der neugierig auf die Story macht (Es geht um Jugend, Liebe, Identität).
        2. Kurze, knackige Vorstellung des Buchs.
        3. Die konkrete Frage, ob Interesse an einem Rezensionsexemplar besteht.
        4. Halte die E-Mail übersichtlich und nicht zu lang.
        
        Antworte AUSSCHLIESSLICH mit dem fertigen E-Mail-Text (inklusive Betreffzeile ganz oben). Kein 'Hier ist der Text'-Drumherum.
        """

        try:
            pitch_text = llm.invoke(prompt).strip()
            
            # Dateinamen sicher machen
            sicherer_name = "".join([c for c in titel if c.isalpha() or c.isdigit() or c==' ']).rstrip()
            sicherer_name = sicherer_name.replace(' ', '_')[:30]
            dateiname = f"{PITCH_DIR}/Pitch_{typ}_{sicherer_name}.txt"
            
            # Lokal speichern
            with open(dateiname, "w", encoding="utf-8") as f:
                f.write(f"EMPFÄNGER-URL: {url}\nKONTAKT-EMAIL: {email}\n")
                f.write("="*50 + "\n\n")
                f.write(pitch_text)
                
            print(f"   💾 Gespeichert unter: {dateiname}")
            kontakt["pitch_erstellt"] = dateiname
            
            # NEU: n8n informieren, dass ein Diamant geschliffen wurde!
            payload = {
                "buch_titel": buechermarketing_titel := "What is Love?",
                "schritt_id": "3",
                "schritt_name": "Pitch Generiert",
                "anweisung_text": f"**Neuer E-Mail-Entwurf fertig!**\n\n**Typ:** {typ}\n**Medium:** {titel}\n**E-Mail:** {email}\n\n{pitch_text}"
            }
            try:
               # requests.post(N8N_WEBHOOK_URL, json=payload)
            except:
                pass # Falls n8n gerade nicht lauscht, nicht abstürzen

        except Exception as e:
            print(f"   ⚠️ Fehler bei Pitch-Erstellung: {e}")

    # Aktualisierte Kontakte zurückschreiben
    with open(VALIDATED_FILE, "w", encoding="utf-8") as f:
        json.dump(kontakte, f, indent=4, ensure_ascii=False)
        
    speichere_status_log(f"Pitch-Generator beendet. Anschreiben in '{PITCH_DIR}/' abgelegt.")
    print("\n🎯 Alle Anschreiben erfolgreich generiert!")

if __name__ == "__main__":
    main()
