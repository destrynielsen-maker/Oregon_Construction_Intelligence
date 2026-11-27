"""Read-only real-source acceptance; never runs the production pipeline."""
import json
from collections import Counter
from datetime import date
from pathlib import Path
from oregon_permits.collectors.bend import BendCollector
from oregon_permits.classify import classify_permit
from oregon_permits.storage import load_permits

before = load_permits(Path("data/permits.json"))
collector=BendCollector()
result=collector.collect()
candidates=[classify_permit(p) for p in result.permits]
keys=[p.key for p in candidates]
assert len(keys)==len(set(keys)), "duplicate candidates"
dates=[date.fromisoformat(p.issued_date) for p in candidates]
assert dates and max(dates)<=date.today(), "invalid or future issuance"
old=[p for p in before.values() if p.jurisdiction=="Bend"]
overlap=[p for p in candidates if p.key in before]
policy_deltas=[p.key for p in overlap if (p.qualifies,p.classification,p.score)!=(before[p.key].qualifies,before[p.key].classification,before[p.key].score)]
raw_evidence_loss=[p.key for p in overlap if (before[p.key].raw or {}).get("census_structure") and not (p.raw or {}).get("census_structure")]
print(json.dumps({"collected":len(candidates),"qualifying":sum(p.qualifies for p in candidates),"latest_issued":max(dates).isoformat(),"age_days":(date.today()-max(dates)).days,"cached":len(old),"overlap":len(overlap),"new_identities":len(set(keys)-set(before)),"qualification_or_score_deltas":len(policy_deltas),"prior_census_evidence_missing":len(raw_evidence_loss),"classification":dict(Counter(p.classification for p in candidates))},indent=2))
assert (date.today()-max(dates)).days <= collector.freshness_days, "upstream data stale"
assert not policy_deltas, "existing classifications or scores changed: review before release"
assert not raw_evidence_loss, "preserve old source evidence before release"
