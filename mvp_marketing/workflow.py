import json
import os
from datetime import datetime, timedelta
from typing import Any

from mvp_marketing.adapters.google_sheets import GoogleSheetsAdapter
from mvp_marketing.adapters.local_llm import LocalLLMAdapter
from mvp_marketing.adapters.telegram import TelegramAdapter
from mvp_marketing.models import now_iso
from mvp_marketing.sources.contact_sources import mock_contact_source
from mvp_marketing.sources.coverage_sources import mock_coverage_source, website_reviews_source
from mvp_marketing.storage import load_state, save_state


SHEET_HEADERS = {
    "campaigns": [
        "id",
        "buchtitel",
        "genre",
        "zielgruppe",
        "region_land",
        "budgetrahmen",
        "kampagnenzeitraum",
        "status",
        "created_at",
    ],
    "contacts": [
        "id",
        "name",
        "organisation",
        "kanaltyp",
        "region",
        "email",
        "website",
        "instagram",
        "youtube",
        "notizen",
        "quelle",
        "confidence_score",
        "status",
    ],
    "outreach_queue": [
        "id",
        "contact_id",
        "kanal",
        "text",
        "status",
        "approval_status",
        "approval_id",
        "created_at",
        "sent_at",
    ],
    "coverage": ["id", "titel", "quelle", "typ", "link", "text", "status"],
    "reviews": ["id", "titel", "quelle", "typ", "link", "text", "status"],
}


def _campaign_id(brief: dict[str, Any]) -> str:
    date = datetime.utcnow().strftime("%Y%m%d")
    title = "".join(c for c in brief.get("buchtitel", "buch") if c.isalnum()).lower()[:20] or "buch"
    return f"cmp_{date}_{title}"


def default_marketing_plan(brief: dict[str, Any]) -> list[dict[str, Any]]:
    channels = ", ".join(brief.get("kanaele", []))
    return [
        {"prioritaet": 1, "massnahme": f"Buchhandlungen in {brief.get('region_land', 'DACH')} priorisieren", "kanal": "buchhandlung"},
        {"prioritaet": 2, "massnahme": "Lokalzeitungen und Kulturblogs ansprechen", "kanal": "presse"},
        {"prioritaet": 3, "massnahme": f"Regionale Creator/Podcasts für {channels} identifizieren", "kanal": "creator"},
    ]


def generate_marketing_plan(llm: LocalLLMAdapter, brief: dict[str, Any], dry_run: bool) -> list[dict[str, Any]]:
    fallback = {"maßnahmen": default_marketing_plan(brief)}
    prompt = (
        "Erstelle einen priorisierten Offline-Marketingplan als JSON. "
        "Format: {\"maßnahmen\": [{\"prioritaet\": 1, \"massnahme\": \"...\", \"kanal\": \"...\"}]}. "
        f"Briefing: {json.dumps(brief, ensure_ascii=False)}"
    )
    result = llm.complete_json(prompt, fallback=fallback, dry_run=dry_run)
    actions = result.get("maßnahmen") if isinstance(result, dict) else None
    return actions or fallback["maßnahmen"]


def generate_outreach_draft(llm: LocalLLMAdapter, brief: dict[str, Any], contact: dict[str, Any], kanal: str, dry_run: bool) -> str:
    if dry_run:
        return (
            f"[DRY-RUN] Hallo {contact.get('name')}, wir stellen das Buch '{brief.get('buchtitel')}' vor "
            f"und würden uns über Austausch via {kanal} freuen."
        )
    prompt = (
        f"Schreibe einen {kanal}-Outreach-Entwurf für Kontakt {contact.get('organisation')} ({contact.get('name')}). "
        f"Buch: {brief.get('buchtitel')}, Genre: {brief.get('genre')}, Zielgruppe: {brief.get('zielgruppe')}."
    )
    text = llm.complete(prompt, dry_run=False)
    return text or f"Hallo {contact.get('name')}, wir freuen uns über einen Austausch zu {brief.get('buchtitel')}."


def schedule_followups(outreach_rows: list[dict[str, Any]], days: int = 5, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.utcnow()
    due: list[dict[str, Any]] = []
    for row in outreach_rows:
        if row.get("status") != "sent" or row.get("response_status") == "responded":
            continue
        sent_at = row.get("sent_at")
        if not sent_at:
            continue
        try:
            sent_time = datetime.fromisoformat(sent_at.replace("Z", ""))
        except ValueError:
            continue
        if now >= sent_time + timedelta(days=days):
            due.append(
                {
                    "id": f"fu_{row['id']}",
                    "draft_id": row["id"],
                    "contact_id": row["contact_id"],
                    "status": "due",
                    "due_at": (sent_time + timedelta(days=days)).replace(microsecond=0).isoformat() + "Z",
                }
            )
    return due


def export_website_reviews(state: dict[str, Any], repo_root: str) -> str:
    path = os.path.join(repo_root, "autoren_website", "src", "_data", "mvp_mentions.json")
    reviews = [
        {
            "text": row.get("text", ""),
            "author": row.get("titel", "Unbekannt"),
            "source": row.get("quelle", "Web"),
            "type": row.get("typ", "coverage"),
            "link": row.get("link", ""),
        }
        for row in state.get("reviews", []) + state.get("coverage", [])
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(reviews, f, indent=2, ensure_ascii=False)
    return path


def run_workflow(briefing_path: str, state_path: str, dry_run: bool = True) -> dict[str, Any]:
    with open(briefing_path, "r", encoding="utf-8") as f:
        brief = json.load(f)

    state = load_state(state_path)
    llm = LocalLLMAdapter()
    sheets = GoogleSheetsAdapter(dry_run=dry_run)
    telegram = TelegramAdapter(dry_run=dry_run)

    campaign_id = _campaign_id(brief)
    if not any(c["id"] == campaign_id for c in state["campaigns"]):
        state["campaigns"].append(
            {
                "id": campaign_id,
                "buchtitel": brief.get("buchtitel", ""),
                "genre": brief.get("genre", ""),
                "zielgruppe": brief.get("zielgruppe", ""),
                "region_land": brief.get("region_land", ""),
                "budgetrahmen": brief.get("budgetrahmen", ""),
                "kampagnenzeitraum": brief.get("kampagnenzeitraum", ""),
                "status": "planned",
                "created_at": now_iso(),
            }
        )

    plan = generate_marketing_plan(llm, brief, dry_run=dry_run)

    existing_contacts = {c["id"] for c in state["contacts"]}
    new_contacts = [c for c in mock_contact_source(brief) if c["id"] not in existing_contacts]
    state["contacts"].extend(new_contacts)

    drafts_added = 0
    existing_draft_keys = {(d["contact_id"], d["kanal"]) for d in state["outreach_queue"]}
    for contact in state["contacts"]:
        for kanal in ("email", "telegram"):
            key = (contact["id"], kanal)
            if key in existing_draft_keys:
                continue
            text = generate_outreach_draft(llm, brief, contact, kanal=kanal, dry_run=dry_run)
            draft = {
                "id": f"dr_{contact['id']}_{kanal}",
                "contact_id": contact["id"],
                "kanal": kanal,
                "text": text,
                "status": "draft",
                "approval_status": "pending",
                "approval_id": "",
                "created_at": now_iso(),
                "sent_at": "",
                "response_status": "none",
            }
            state["outreach_queue"].append(draft)
            existing_draft_keys.add(key)
            drafts_added += 1

    for draft in state["outreach_queue"]:
        if draft["approval_status"] != "pending" or draft["approval_id"]:
            continue
        contact = next((c for c in state["contacts"] if c["id"] == draft["contact_id"]), {"name": "Kontakt"})
        approval = telegram.request_approval(draft["id"], contact.get("name", "Kontakt"), draft["kanal"], draft["text"])
        draft["approval_id"] = approval["approval_id"]
        draft["approval_status"] = approval["status"]
        state["approvals"][approval["approval_id"]] = {
            "draft_id": draft["id"],
            "status": approval["status"],
        }

    for update_id, decision in telegram.fetch_approval_updates().items():
        if update_id not in state["approvals"]:
            continue
        state["approvals"][update_id]["status"] = decision
        draft_id = state["approvals"][update_id]["draft_id"]
        for draft in state["outreach_queue"]:
            if draft["id"] == draft_id:
                draft["approval_status"] = decision

    for draft in state["outreach_queue"]:
        if draft["status"] == "sent" or draft["approval_status"] != "approved":
            continue
        sent = telegram.send_message(draft["kanal"], draft["text"])
        if sent:
            draft["status"] = "sent"
            draft["sent_at"] = now_iso()

    existing_cov = {r["id"] for r in state["coverage"]}
    for row in mock_coverage_source(brief):
        if row["id"] not in existing_cov:
            state["coverage"].append(row)

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    existing_reviews = {r["id"] for r in state["reviews"]}
    for row in website_reviews_source(repo_root):
        if row["id"] not in existing_reviews:
            state["reviews"].append(row)

    due_followups = schedule_followups(state["outreach_queue"], days=int(os.getenv("FOLLOWUP_DAYS", "5")))
    known_followups = {f["id"] for f in state["followups"]}
    for fup in due_followups:
        if fup["id"] not in known_followups:
            state["followups"].append(fup)

    for sheet_name in ("campaigns", "contacts", "outreach_queue", "coverage", "reviews"):
        sheets.upsert_rows(sheet_name, SHEET_HEADERS[sheet_name], state[sheet_name], id_column="id")

    export_website_reviews(state, repo_root)
    save_state(state_path, state)

    return {
        "campaign_id": campaign_id,
        "plan": plan,
        "contacts_added": len(new_contacts),
        "drafts_added": drafts_added,
        "pending_approvals": len([d for d in state["outreach_queue"] if d["approval_status"] == "pending"]),
    }
