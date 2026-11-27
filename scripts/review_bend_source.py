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


# Exercise the actual production integration on an isolated copy, without
# contacting any unrelated collector. No writes to the repository data tree.
import tempfile
import shutil
from unittest.mock import patch
from oregon_permits import pipeline
from oregon_permits.collectors.base import CollectionResult
from oregon_permits.dashboard import builder_rollups
from oregon_permits.feeds import write_all_feeds
from xml.etree import ElementTree as ET

class ObservedBend:
    name="Bend"
    freshness_days=10
    source_url=collector.source_url
    def collect(self):
        return CollectionResult("Bend",[type(p).from_dict(p.to_dict()) for p in candidates],self.source_url,"verified municipal issued records")

def unchanged_fields(p):
    row=p.to_dict()
    row.pop("last_seen_at")
    raw=row.pop("raw")
    return row,raw

with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    (root/"data").mkdir()
    shutil.copyfile(store,root/"data/permits.json")
    (root/"public/data").mkdir(parents=True)
    shutil.copyfile("public/data/sources.json",root/"public/data/sources.json")
    with patch.object(pipeline,"COLLECTORS",[ObservedBend()]):
        result=pipeline.run(root)
    after=load_permits(root/"data/permits.json")
    assert len(json.loads((root/"data/permits.json").read_text())["permits"])==len(after)
    assert set(after)==set(before)|set(second), "identity loss or unexpected additions"
    for k,old in before.items():
        old_fields,old_raw=unchanged_fields(old)
        new_fields,new_raw=unchanged_fields(after[k])
        assert old_fields==new_fields,(k,"existing published field changed")
        assert all(new_raw.get(key)==value for key,value in (old_raw or {}).items()),(k,"raw evidence lost")
        if k not in second: assert old.to_dict()==after[k].to_dict(),(k,"unrelated record changed")
    new=[after[k] for k in second.keys()-before.keys()]
    expected=[*before.values(),*new]
    assert builder_rollups([p for p in after.values() if p.qualifies])==builder_rollups([p for p in expected if p.qualifies])
    # RSS ties can depend on input order. Compare each generated item by GUID
    # and validate membership against date/score boundary and expected rows.
    expected_dir=root/"expected_feeds"
    write_all_feeds(expected_dir,expected,pipeline._site())
    for path in (root/"public/feeds").glob("*.xml"):
        def items(p):
            return {e.findtext("guid"):ET.tostring(e) for e in ET.parse(p).findall("./channel/item")}
        actual,expected_items=items(path),items(expected_dir/path.name)
        assert actual==expected_items,(path.name,"unexpected RSS change")
    public=json.loads((root/"public/data/permits.json").read_text())["permits"]
    assert len(public)==sum(p.qualifies for p in after.values())
    assert len(public)==len({type(candidates[0]).from_dict(p).key for p in public})
    assert result["sources"][0]["technical_status"]=="ok"
    assert result["sources"][0]["freshness_status"]=="fresh"
    print("ADDITIVE INTEGRATION ACCEPTANCE",json.dumps({"before":len(before),"after":len(after),"new":len(new),"new_qualifying":sum(p.qualifies for p in new),"earliest_new_issue":min(p.issued_date for p in new) if new else None,"latest_new_issue":max(p.issued_date for p in new) if new else None,"existing_fields_preserved":len(before),"builder_rollups_exact":True,"rss_exact":True,"source":result["sources"][0]},indent=2),flush=True)
