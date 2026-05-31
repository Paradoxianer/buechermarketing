import json
import os
import re
from hashlib import sha1


def _id(prefix: str, value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    if clean:
        return f"{prefix}_{clean[:40]}"
    return f"{prefix}_{sha1(value.encode('utf-8')).hexdigest()[:12]}"


def website_reviews_source(repo_root: str) -> list[dict]:
    path = os.path.join(repo_root, "autoren_website", "src", "_data", "reviews.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    results = []
    for row in rows:
        text = row.get("text") or row.get("Zitat") or row.get("Zitat / O-Ton") or ""
        author = row.get("author") or row.get("autor") or row.get("Medium/Name") or "Unbekannt"
        source = row.get("source") or row.get("plattform") or row.get("Typ") or "Web"
        link = row.get("link") or row.get("Link zum Beitrag") or ""
        results.append(
            {
                "id": _id("rvw", f"{author}-{source}-{text[:30]}"),
                "titel": f"Review von {author}",
                "quelle": source,
                "typ": "review",
                "link": link,
                "text": text,
                "status": "importiert",
            }
        )
    return results


def mock_coverage_source(brief: dict) -> list[dict]:
    region = brief.get("region_land", "DACH")
    title = brief.get("buchtitel", "Unbekannt")
    base = f"{title}-{region}"
    return [
        {
            "id": _id("cov", base),
            "titel": f"Lokale Erwähnung zu {title}",
            "quelle": "Mock-Zeitung",
            "typ": "coverage",
            "link": "https://example.org/coverage",
            "text": f"Stub-Erwähnung für {title} in {region}.",
            "status": "neu",
        }
    ]
