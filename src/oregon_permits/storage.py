from __future__ import annotations
import json
from pathlib import Path
from .models import Permit

def load_permits(path: Path) -> dict[str, Permit]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(raw, dict):
        raw = raw.get("permits", [])
    return {p.key:p for p in (Permit.from_dict(x) for x in raw)}

def save_permits(path: Path, permits: list[Permit], generated_at: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    values = sorted(permits, key=lambda p:(p.issued_date or "",p.jurisdiction,p.permit_number), reverse=True)
    path.write_text(json.dumps({"generated_at":generated_at,"permits":[p.to_dict() for p in values]},indent=2),encoding="utf-8")
