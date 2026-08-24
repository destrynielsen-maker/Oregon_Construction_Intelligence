from __future__ import annotations
import json, os
from datetime import date, datetime, timezone
from pathlib import Path
from .classify import classify_permit
from .collectors import COLLECTORS
from .dashboard import write_public_data
from .feeds import write_all_feeds
from .models import Permit
from .storage import load_permits, save_permits

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
    existing=load_permits(store); previous=_previous(public/"data"/"sources.json"); statuses=[]; total=0
    for collector in COLLECTORS:
        prev=previous.get(collector.name)
        try:
            result=collector.collect(); total+=len(result.permits); qualified=0
            for p in result.permits:
                classify_permit(p); qualified+=int(p.qualifies)
                old=existing.get(p.key)
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
