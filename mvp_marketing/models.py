from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


def now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


@dataclass
class CampaignBrief:
    buchtitel: str
    genre: str
    zielgruppe: str
    kernbotschaften: list[str]
    region_land: str
    kanaele: list[str]
    budgetrahmen: str
    kampagnenzeitraum: str


@dataclass
class Contact:
    id: str
    name: str
    organisation: str
    kanaltyp: str
    region: str
    email: str = ""
    website: str = ""
    instagram: str = ""
    youtube: str = ""
    notizen: str = ""
    quelle: str = ""
    confidence_score: int = 0
    status: str = "neu"


@dataclass
class OutreachDraft:
    id: str
    contact_id: str
    kanal: str
    text: str
    status: str = "draft"
    approval_status: str = "pending"
    approval_id: str = ""
    created_at: str = field(default_factory=now_iso)
    sent_at: str = ""


@dataclass
class CoverageEntry:
    id: str
    titel: str
    quelle: str
    typ: str
    link: str
    text: str
    status: str = "neu"


def to_dict(item: Any) -> dict[str, Any]:
    return asdict(item)
