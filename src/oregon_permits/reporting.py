"""Additive source observability. No eligibility, storage or feed decisions live here."""
from __future__ import annotations

from datetime import date, datetime
from collections.abc import Iterable

from .models import Permit

_EASTERN = (
    ("hermiston", "Hermiston", "manual", "Official monthly reports for manual review; pilot is off"),
    ("pendleton", "Pendleton", "uncovered", "State permit lookup only; no automated coverage"),
    ("la-grande", "La Grande", "uncovered", "State permit lookup only; no automated coverage"),
    ("ontario", "Ontario", "uncovered", "State permit lookup only; no automated coverage"),
    ("baker-city", "Baker City", "uncovered", "Historical permit archive only; no automated coverage"),
)


def _issuer(p: Permit, name: str) -> bool:
    return p.state == "OR" and p.jurisdiction.strip().casefold() == name.strip().casefold()


def _issue_date(p: Permit, today: date) -> date | None:
    # Hillsboro's portal only establishes first observed issuance, not its issue date.
    if p.jurisdiction.strip().casefold() == "hillsboro" or (p.raw or {}).get("issued_date_basis") == "first_observed_issued":
        return None
    if not p.issued_date:
        return None
    try:
        value = date.fromisoformat(p.issued_date)
    except ValueError:
        return None
    return value if value <= today else None


def _known_success(value: str | None) -> bool:
    try:
        return bool(value and datetime.fromisoformat(value).tzinfo)
    except (ValueError, TypeError):
        return False


def compile_reporting(generated: str, today: date, statuses: Iterable[dict],
                      loaded: dict[str, Permit], retained: dict[str, Permit],
                      accepted_by_source: dict[str, set[str]], previous: dict[str, dict],
                      same_checkpoint: bool) -> dict:
    rows = []
    for status in statuses:
        issuer = status["source"]
        if status.get("technical_status") not in {"ok", "error"}:
            continue
        saved = {key: p for key, p in retained.items() if _issuer(p, issuer)}
        prior = {key for key, p in loaded.items() if _issuer(p, issuer)}
        success = status["technical_status"] == "ok"
        accepted = set(accepted_by_source.get(issuer, ())) & saved.keys()
        attempted = [saved[key] for key in accepted]
        dates = [d for p in (attempted if success else saved.values()) if (d := _issue_date(p, today))]
        latest = max(dates, default=None)
        past = previous.get(issuer, {})
        known_empty = past.get("technical_status") == "ok" and past.get("records_seen") == 0
        comparable = success and same_checkpoint and (bool(prior) or known_empty) and _known_success(past.get("last_success_at"))
        rows.append({
            "id": issuer.strip().casefold().replace(" ", "-"),
            "label": issuer,
            "mode": "automatic",
            "coverage": f"{issuer} building permits",
            "last_attempt_at": status.get("last_attempt_at"),
            "last_success_at": status.get("last_success_at"),
            "latest_authoritative_date": latest.isoformat() if latest else None,
            "latest_date_kind": "issued" if latest else "unknown",
            "date_provenance": ("current source records" if success else "cached source records") if latest else None,
            "source_age_days": (today - latest).days if latest else None,
            "new_since_previous_success": len(accepted - loaded.keys()) if comparable else None,
            "retained_records": len(saved),
            "observed_records": len(accepted) if success else None,
            "availability": "reachable" if success else "unavailable",
            "collection_outcome": ("success" if accepted else "no_data") if success else "error",
        })
    configured={row["id"] for row in rows}
    for identity,label,mode,coverage in _EASTERN:
        if identity in configured:
            continue
        rows.append({
            "id": identity, "label": label, "mode": mode, "coverage": coverage,
            "last_attempt_at": None, "last_success_at": None,
            "latest_authoritative_date": None, "latest_date_kind": "unknown",
            "source_age_days": None, "new_since_previous_success": None,
            "retained_records": None, "observed_records": None,
            "availability": "not_attempted",
            "collection_outcome": "manual_only" if mode == "manual" else "unknown",
        })
    return {"schema_version": 1, "generated_at": generated, "sources": rows}
