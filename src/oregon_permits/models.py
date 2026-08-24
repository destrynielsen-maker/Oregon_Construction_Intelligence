from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any

@dataclass
class Permit:
    state: str
    jurisdiction: str
    permit_number: str
    issued_date: str
    permit_type: str = ""
    building_use: str | None = None
    project_name: str | None = None
    address: str = ""
    units: int | None = None
    valuation: float | None = None
    contractor: str | None = None
    owner: str | None = None
    status: str | None = None
    source_name: str = ""
    source_url: str = ""
    raw: dict[str, Any] | None = None
    classification: str = "OTHER"
    qualifies: bool = False
    score: int = 0
    new_construction_confidence: str = "LOW"
    first_seen_at: str | None = None
    last_seen_at: str | None = None

    @property
    def key(self) -> str:
        return f"{self.state}|{self.jurisdiction.strip().lower()}|{self.permit_number.strip().lower()}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> "Permit":
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{k: value.get(k) for k in allowed if k in value})
