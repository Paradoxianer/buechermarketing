# Offline-Marketing-Agentur MVP (lokal)

Dieses Repository enthält jetzt ein MVP für eine lokal laufende, agentische Offline-Marketing-Pipeline mit **Datenschutzfokus** und **manueller Freigabe**.

## MVP-Architektur (neu)

- `mvp_marketing/cli.py` – CLI-Einstiegspunkt (`run`, `approve`)
- `mvp_marketing/workflow.py` – Happy-Path-Orchestrierung
- `mvp_marketing/models.py` – gemeinsame Datenmodelle
- `mvp_marketing/storage.py` – lokale JSON-Persistenz (`mvp_state.json`)
- `mvp_marketing/adapters/local_llm.py` – lokales LLM über OpenAI-kompatiblen Endpoint
- `mvp_marketing/adapters/google_sheets.py` – Google-Sheets-Sync (Tabs: `campaigns`, `contacts`, `outreach_queue`, `coverage`, `reviews`)
- `mvp_marketing/adapters/telegram.py` – Freigabeanforderung + Versand-Gate
- `mvp_marketing/sources/*` – Kontakt-/Coverage-/Review-Quellen (MVP: sichere Mock-Quellen + bestehende Website-Reviews als funktionierende Quelle)

## Happy Path (lokal)

1. Briefing als JSON erstellen (Beispiel unten)
2. Workflow starten (standardmäßig Dry-Run)
3. Approval-ID aus `mvp_state.json` oder Telegram nutzen
4. Freigabe setzen
5. Workflow erneut starten (Versand nur bei expliziter Freigabe)

### Beispiel-Briefing

```json
{
  "buchtitel": "What is Love?",
  "genre": "Jugendroman",
  "zielgruppe": "Young Adult Leserinnen 14-25",
  "kernbotschaften": ["erste Liebe", "Identität", "Mut"],
  "region_land": "Deutschland",
  "kanaele": ["buchhandlung", "lokalzeitung", "podcast"],
  "budgetrahmen": "2.000-5.000 EUR",
  "kampagnenzeitraum": "2026-06 bis 2026-09"
}
```

### CLI

```bash
python -m mvp_marketing.cli run --briefing /absoluter/pfad/briefing.json
python -m mvp_marketing.cli approve --state mvp_state.json --approval-id appr_xxxxxxxx --decision approved
python -m mvp_marketing.cli run --briefing /absoluter/pfad/briefing.json
```

## Sicherheitsgrenzen / Datenschutz

- Standard ist **Dry-Run** (`run` ohne `--no-dry-run`): keine produktiven API-Aktionen.
- Kritische Aktion (ausgehende Nachricht) wird nur ausgeführt, wenn `approval_status=approved`.
- Lokales LLM ist frei konfigurierbar (`LOCAL_LLM_ENDPOINT`), keine Cloud-Bindung erzwungen.

## Produktionsstatus im MVP

- ✅ Kampagnenplanung (lokales LLM + Fallback)
- ✅ Kontaktmodell & kontaktquellenbasierte Pipeline (MVP: Mock-Quelle)
- ✅ Google-Sheets-Sync in neue Blätter (`campaigns`, `contacts`, `outreach_queue`, `coverage`, `reviews`)
- ✅ Outreach-Entwürfe (E-Mail + Telegram)
- ✅ Telegram-Freigabe-Gate vor Versand
- ✅ Regelbasiertes Follow-up (X Tage ohne Antwort)
- ✅ Coverage/Review-Ingestion-Grundgerüst + funktionierende Quelle (`autoren_website/src/_data/reviews.json`)
- ✅ Website-Integration vorbereitet: Workflow exportiert aggregierte Reviews nach `autoren_website/src/_data/reviews.json`

## Nächster Ausbau

- Reale Kontaktquellen (APIs/Crawler) als zusätzliche Adapter
- E-Mail-Versandadapter mit gleicher Approval-Logik
- Bessere Telegram-Interaktionslogik mit Callback-Buttons
- Erweiterte Tests für Adapter mit Mocks
