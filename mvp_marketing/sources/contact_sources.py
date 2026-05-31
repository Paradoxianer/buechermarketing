import re
from hashlib import sha1


def _slug(value: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return raw[:40] or sha1(value.encode("utf-8")).hexdigest()[:12]


def mock_contact_source(brief: dict) -> list[dict]:
    region = brief.get("region_land", "DACH")
    title = brief.get("buchtitel", "buch")
    return [
        {
            "id": f"ct_{_slug('lokale-buchhandlung-'+region)}",
            "name": "Inhaberin Pressekontakt",
            "organisation": f"Buchhandlung {region}",
            "kanaltyp": "buchhandlung",
            "region": region,
            "email": f"kontakt@buchhandlung-{_slug(region)}.de",
            "website": "https://example.org/buchhandlung",
            "notizen": f"Interesse an Lesung zu {title}",
            "quelle": "mock_contact_source",
            "confidence_score": 65,
            "status": "neu",
        },
        {
            "id": f"ct_{_slug('lokalblog-'+region)}",
            "name": "Redaktion",
            "organisation": f"Kulturblog {region}",
            "kanaltyp": "blog",
            "region": region,
            "email": f"redaktion@kulturblog-{_slug(region)}.de",
            "website": "https://example.org/blog",
            "instagram": "https://instagram.com/kulturblog",
            "notizen": "Regionale Reichweite",
            "quelle": "mock_contact_source",
            "confidence_score": 58,
            "status": "neu",
        },
    ]
