import csv
import os
from datetime import datetime

import utils_system as utils


CSV_FILE = "Buch_PR_Koordination_ - Presse, Internet.csv"
TARGET_TAB = "Seed_Kontakte"
LOG_TAB = "Logbuch"


def log(level: str, message: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{level}] {ts} — {message}", flush=True)
    try:
        utils.write_to_sheet(LOG_TAB, [[ts, "import_seed_contacts.py", level, message]])
    except Exception as e:
        print(f"[WARNUNG] Logbuch konnte nicht geschrieben werden: {e}", flush=True)


def normalize(value):
    return str(value or "").strip()


def load_existing_keys():
    """
    Verhindert Dubletten anhand von (Name + URL/Kontaktdaten).
    """
    keys = set()
    try:
        rows = utils.get_sheet_data(TARGET_TAB)
        for row in rows:
            name = normalize(row.get("Name", "")).lower()
            url = normalize(row.get("URL", row.get("Kontaktdaten", ""))).lower()
            if name or url:
                keys.add((name, url))
    except Exception as e:
        log("WARNUNG", f"Bestehende Seed-Kontakte konnten nicht geladen werden: {e}")
    return keys


def main():
    if not os.path.exists(CSV_FILE):
        log("FEHLER", f"CSV-Datei nicht gefunden: {CSV_FILE}")
        return

    existing = load_existing_keys()
    rows_to_write = []

    with open(CSV_FILE, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            name = normalize(row.get("Name"))
            typ = normalize(row.get("Typ"))
            ansprechpartner = normalize(row.get("Ansprechpartner"))
            adresse = normalize(row.get("Adresse"))
            freiexemplar = normalize(row.get("Freiexemplar"))
            artikel = normalize(row.get("Artikel / Anfrage"))
            kontaktdaten = normalize(row.get("Kontaktdaten"))
            infos = normalize(row.get("Infos"))
            turnus = normalize(row.get("Turnus"))
            auflage = normalize(row.get("Auflage"))

            # Leere Zeilen ignorieren
            if not any([name, typ, ansprechpartner, adresse, kontaktdaten, infos]):
                continue

            # URL grob aus Kontaktdaten/Infos erkennen
            url = ""
            for candidate in [kontaktdaten, infos]:
                if "http://" in candidate or "https://" in candidate or "www." in candidate:
                    url = candidate
                    break

            dedupe_key = (name.lower(), (url or kontaktdaten).lower())
            if dedupe_key in existing:
                continue

            existing.add(dedupe_key)

            rows_to_write.append([
                name,
                typ,
                ansprechpartner,
                adresse,
                freiexemplar,
                artikel,
                kontaktdaten,
                infos,
                turnus,
                auflage,
                url,
                "Altbestand CSV",
                "Neu importiert",
                ""
            ])

    if not rows_to_write:
        log("INFO", "Keine neuen Seed-Kontakte zum Import gefunden.")
        return

    utils.write_to_sheet(TARGET_TAB, rows_to_write)
    log("OK", f"{len(rows_to_write)} Seed-Kontakte importiert.")
    utils.send_telegram(
        f"📥 <b>Seed-Kontakte importiert</b>\n\n"
        f"✅ Neue Einträge: {len(rows_to_write)}\n"
        f"📄 Quelle: <code>{CSV_FILE}</code>\n"
        f"📋 Ziel-Tab: <b>{TARGET_TAB}</b>",
        parse_mode="HTML"
    )


if __name__ == "__main__":
    main()