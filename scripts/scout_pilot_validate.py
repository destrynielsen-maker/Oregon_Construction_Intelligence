# Validation-only branch. No repository Git or external writes.
import json
import runpy
from pathlib import Path

from oregon_permits import pipeline

MARKET = 'Hermiston'


def rows():
    payload = json.loads(Path("data/permits.json").read_text())
    return payload if isinstance(payload, list) else payload["permits"]


def keyed(items):
    result = {(r["state"], r["jurisdiction"], r["permit_number"]): r for r in items}
    assert len(items) == len(result), "Duplicate stored permit identities"
    return result


def run():
    pipeline.COLLECTORS = []  # Validate pilot only and preserve preexisting data in the checkout.
    runpy.run_module("oregon_permits.main", run_name="__main__")
    sources = json.loads(Path("public/data/sources.json").read_text())["sources"]
    status = next(s for s in sources if s["source"] == MARKET)
    assert status["technical_status"] == "ok", str(status)
    assert status["freshness_status"] == "fresh", str(status)
    assert status["records_seen"] > 0, str(status)
    return status


baseline = keyed(rows())
status = run()
after = keyed(rows())
assert baseline.keys() <= after.keys(), "Existing permit identities were lost"
assert all(v["first_seen_at"] == after[k]["first_seen_at"] for k, v in baseline.items())
pilot = [v for k, v in after.items() if k[1] == MARKET]
assert all(r["qualifies"] for r in pilot), "Pilot stored a nonqualifying record"
assert len(pilot) == status["qualifying_records"], str(status)
if MARKET == "Hermiston":
    assert pilot and all(not r["contractor"] and r["raw"]["contractor_role"] == "unverified" for r in pilot)
else:
    assert all(not r["contractor"] or r["raw"]["source_role"] == "Contractor" for r in pilot)
status2 = run()
repeat = keyed(rows())
assert after.keys() == repeat.keys(), "Second source snapshot added or removed identities"
assert all(v["first_seen_at"] == repeat[k]["first_seen_at"] for k, v in after.items())
print("SCOUT_VALIDATION", json.dumps({
    "baseline_count": len(baseline), "after_count": len(after),
    "pilot_count": len(pilot), "source_records": status["records_seen"],
    "newest": status["newest_permit_date"], "freshness": status["freshness_status"],
    "reported_contractor_count": sum(bool(r["contractor"]) for r in pilot),
    "rerun_count": len(repeat), "second_qualifying": status2["qualifying_records"],
}))
