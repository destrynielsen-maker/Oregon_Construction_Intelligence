"""Read-only real-source acceptance. Never writes production or invokes the pipeline."""
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
from oregon_permits.collectors.bend import BendCollector
from oregon_permits.classify import classify_permit
from oregon_permits.storage import load_permits

store=Path("data/permits.json")
before=load_permits(store)
raw_rows=json.loads(store.read_text())["permits"]
assert len(raw_rows)==len(before), "duplicate history identities"
print("Baseline store sha256", hashlib.sha256(store.read_bytes()).hexdigest(), "historical identities",len(before))
collector=BendCollector()
def collect():
    result=collector.collect()
    candidates=[classify_permit(p) for p in result.permits]
    keys=[p.key for p in candidates]
    assert len(keys)==len(set(keys)), "duplicate candidates"
    dates=[date.fromisoformat(p.issued_date) for p in candidates]
    assert dates and max(dates)<=date.today(), "invalid or future issuance"
    assert (date.today()-max(dates)).days <= collector.freshness_days, "upstream data stale"
    return {p.key:p for p in candidates},max(dates)
first,newest=collect()
second,newest_repeat=collect()
print("Repeat",json.dumps({"first":len(first),"second":len(second),"only_first":len(first.keys()-second.keys()),"only_second":len(second.keys()-first.keys()),"first_latest":str(newest),"second_latest":str(newest_repeat)}))
candidates=list(second.values())
overlap=[p for p in candidates if p.key in before]
old=[p for p in before.values() if p.jurisdiction=="Bend"]
policy_deltas=[]
raw_evidence_changes=Counter()
changes=Counter()
for p in overlap:
    prior=before[p.key]
    old_dict,new_dict=prior.to_dict(),p.to_dict()
    changed=[k for k in old_dict if k not in {"first_seen_at","last_seen_at","raw"} and old_dict[k]!=new_dict[k]]
    changes.update(changed)
    old_raw,new_raw=prior.raw or {},p.raw or {}
    raw_changed=[k for k,v in old_raw.items() if v not in (None,"") and v!=new_raw.get(k)]
    raw_evidence_changes.update(raw_changed)
    if (p.qualifies,p.classification,p.score)!=(prior.qualifies,prior.classification,prior.score):
        # The permit ID and classification-driving quantities are public source evidence.
        # Do not log personal party names; report presence/absence and equality only.
        fields=("classification","qualifies","score","units","valuation","issued_date")
        policy_deltas.append({"key":p.key,"old":{k:old_dict[k] for k in fields},"new":{k:new_dict[k] for k in fields},"changed_fields":changed,"raw_fields_changed":raw_changed,"contractor_present":[bool(prior.contractor),bool(p.contractor)],"owner_present":[bool(prior.owner),bool(p.owner)],"reclassified_old":{k:getattr(classify_permit(type(prior).from_dict(old_dict)),k) for k in ("classification","qualifies","score")}})
raw_evidence_loss=[p.key for p in overlap if (before[p.key].raw or {}).get("census_structure") and not (p.raw or {}).get("census_structure")]
print(json.dumps({"collected":len(candidates),"qualifying":sum(p.qualifies for p in candidates),"latest_issued":str(newest_repeat),"age_days":(date.today()-newest_repeat).days,"cached":len(old),"overlap":len(overlap),"new_identities":len(second.keys()-before.keys()),"qualification_or_score_deltas":policy_deltas,"prior_census_evidence_missing":len(raw_evidence_loss),"changed_fields":dict(changes),"prior_raw_evidence_changed_fields":dict(raw_evidence_changes),"classification":dict(Counter(p.classification for p in candidates))},indent=2),flush=True)
assert first.keys()==second.keys(), "repeat collection membership changed; reconcile before release"
assert not policy_deltas, "existing classifications or scores changed: review before release"
assert not raw_evidence_loss, "preserve old source evidence before release"
assert not raw_evidence_changes, "prior source evidence changed; review preservation before release"
