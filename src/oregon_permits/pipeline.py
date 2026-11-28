from __future__ import annotations
import json, os, re
from datetime import date, datetime, timezone
from pathlib import Path
from .classify import classify_permit
from .collectors import COLLECTORS
from .dashboard import write_public_data
from .feeds import write_all_feeds
from .models import Permit
from .storage import load_permits, save_permits

PORTLAND_CASE_RE=re.compile(r"^\d{2,4}-\d{6}-",re.I)

def _site() -> str:
    configured=os.environ.get("SITE_BASE_URL","").strip()
    if configured: return configured.rstrip("/")+"/"
    repo=os.environ.get("GITHUB_REPOSITORY","")
    if "/" in repo:
        owner,name=repo.split("/",1); return f"https://{owner}.github.io/{name}/"
    return "https://example.invalid/Oregon_Construction_Intelligence/"

def _previous(path: Path) -> dict:
    if not path.exists(): return {}
    try: payload=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError): return {}
    return {str(x.get("source")):x for x in payload.get("sources",[]) if x.get("source")}

def _dates(items: list[Permit]) -> list[str]:
    values=[]
    for p in items:
        if not p.issued_date: continue
        try: date.fromisoformat(p.issued_date)
        except ValueError: continue
        values.append(p.issued_date)
    return values

def _keep_existing(p: Permit) -> bool:
    raw=p.raw or {}
    if p.jurisdiction=="Portland" and raw.get("source_construction_layer") is True:
        return bool(PORTLAND_CASE_RE.match(p.permit_number or ""))
    return True

def _preserve_observed_issue_date(current: Permit, old: Permit | None) -> None:
    raw=current.raw or {}
    if raw.get("issued_date_basis") != "first_observed_issued" or not old:
        return
    old_raw=old.raw or {}
    if old.issued_date and old_raw.get("issued_date_basis") == "first_observed_issued":
        current.issued_date=old.issued_date
        current.raw={**raw,"first_observed_issued_date":old.issued_date}

def _preserve_bend_recovery_observation(current: Permit, old: Permit | None, generated: str) -> Permit:
    """Additive recovery: retain accepted publication and every differing source observation.

    The historical contractor/score are not a current attribution; latest reported
    values (including explicit absence) are stored separately in the evidence log.
    Reconciliation of previously published fields is a separate review, not a
    side effect of repairing the source query.
    """
    if current.jurisdiction != "Bend" or old is None:
        return current
    from copy import deepcopy
    kept = deepcopy(old)
    raw = kept.raw or {}
    kept.raw = raw
    key = "bend_recovery_observations_v1"
    events = raw.get(key, [])
    if not isinstance(events, list):
        raise ValueError("unexpected Bend recovery evidence format")
    prior_fields = old.to_dict()
    observed_fields = current.to_dict()
    omit = {"raw", "first_seen_at", "last_seen_at", "classification", "qualifies", "score", "new_construction_confidence"}
    changed = {k: v for k, v in observed_fields.items() if k not in omit and v != prior_fields.get(k)}
    baseline_raw = {k: v for k, v in raw.items() if k != key}
    observed_raw = current.raw or {}
    raw_changes = {k: v for k, v in observed_raw.items() if k not in baseline_raw or baseline_raw[k] != v}
    absent = sorted(set(baseline_raw) - set(observed_raw))
    evidence = {"fields": changed, "raw_changed": raw_changes, "raw_absent": absent}
    if events:
        last = {k: events[-1][k] for k in evidence}
        differs = evidence != last
    else:
        differs = bool(changed or raw_changes or absent)
    if differs:
        raw[key] = [*events, {"observed_at": generated, **evidence}]
    return kept

def _success(result, qualified: int, prev: dict | None, generated: str, today: date, threshold: int) -> dict:
    dates=_dates(result.permits); newest=max(dates) if dates else None; oldest=min(dates) if dates else None
    age=(today-date.fromisoformat(newest)).days if newest else None
    freshness="fresh" if age is not None and age<=threshold else ("stale" if age is not None else "unknown")
    prev_count=(prev or {}).get("records_seen"); change=None; volume="normal"
    if prev_count and prev_count>=20:
        change=((len(result.permits)-prev_count)/prev_count)*100
        drop=max(0,(prev_count-len(result.permits))/prev_count)
        if drop>=.80: volume="degraded"
        elif drop>=.50: volume="warning"
    status="no_data" if not result.permits else ("stale" if freshness=="stale" else ("degraded" if volume=="degraded" else ("warning" if volume=="warning" else "healthy")))
    return {"source":result.source,"status":status,"technical_status":"ok","freshness_status":freshness,"volume_status":volume,
            "records_seen":len(result.permits),"qualifying_records":qualified,"newest_permit_date":newest,"oldest_permit_date":oldest,
            "days_since_newest_permit":age,"freshness_threshold_days":threshold,"previous_records_seen":prev_count,
            "record_count_change_pct":None if change is None else round(change,1),"last_attempt_at":generated,"last_success_at":generated,
            "cached_data_available":bool(result.permits),"source_url":result.source_url,"note":result.note}

def _fail(collector, exc: Exception, prev: dict | None, existing: dict[str,Permit], generated: str, today: date) -> dict:
    cached=[p for p in existing.values() if p.jurisdiction==collector.name]; dates=_dates(cached)
    newest=max(dates) if dates else (prev or {}).get("newest_permit_date"); threshold=getattr(collector,"freshness_days",30)
    age=(today-date.fromisoformat(newest)).days if newest else None
    freshness="fresh" if age is not None and age<=threshold else ("stale" if age is not None else "unknown")
    last=(prev or {}).get("last_success_at")
    for p in cached: classify_permit(p)
    note=f"{type(exc).__name__}: {exc}"
    if cached: note="Live collection failed; cached permits retained. "+note
    return {"source":collector.name,"status":"degraded" if cached or last else "error","technical_status":"error",
            "freshness_status":freshness,"volume_status":"unknown","records_seen":0,"qualifying_records":0,
            "cached_records":len(cached),"cached_qualifying_records":sum(int(p.qualifies) for p in cached),
            "newest_permit_date":newest,"oldest_permit_date":min(dates) if dates else None,"days_since_newest_permit":age,
            "freshness_threshold_days":threshold,"previous_records_seen":(prev or {}).get("records_seen"),
            "record_count_change_pct":None,"last_attempt_at":generated,"last_success_at":last,
            "cached_data_available":bool(cached or last),"source_url":getattr(collector,"source_url",""),"note":note}

def run(root: Path) -> dict:
    now=datetime.now(timezone.utc).replace(microsecond=0); generated=now.isoformat()
    store=root/"data"/"permits.json"; public=root/"public"
    loaded=load_permits(store)
    existing={k:p for k,p in loaded.items() if _keep_existing(p)}
    previous=_previous(public/"data"/"sources.json"); statuses=[]; total=0
    for collector in COLLECTORS:
        prev=previous.get(collector.name)
        try:
            result=collector.collect(); total+=len(result.permits); qualified=0
            for p in result.permits:
                old=existing.get(p.key)
                # New Hermiston collection never rewrites accepted historical evidence.
                if old and p.jurisdiction == collector.name == 'Hermiston':
                    classify_permit(p); qualified+=int(p.qualifies)
                    continue
                p = _preserve_bend_recovery_observation(p,old,generated)
                _preserve_observed_issue_date(p,old)
                classify_permit(p); qualified+=int(p.qualifies)
                p.first_seen_at=old.first_seen_at if old and old.first_seen_at else generated
                p.last_seen_at=generated; existing[p.key]=p
            statuses.append(_success(result,qualified,prev,generated,now.date(),getattr(collector,"freshness_days",30)))
        except Exception as exc:
            statuses.append(_fail(collector,exc,prev,existing,generated,now.date()))
    permits=list(existing.values())
    for p in permits: classify_permit(p)
    save_permits(store,permits,generated)
    write_public_data(public,permits,statuses,generated)
    write_all_feeds(public/"feeds",permits,_site())
    return {"generated_at":generated,"total_collected_this_run":total,"total_stored":len(permits),
            "qualifying_stored":sum(int(p.qualifies) for p in permits),"sources":statuses}
