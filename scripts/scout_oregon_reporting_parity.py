import json
from pathlib import Path
a,b=Path("baseline"),Path("candidate")
paths=["data/permits.json","public/data/permits.json","public/data/builders.json"]
paths.extend(str(p.relative_to(a)) for p in (a/"public/feeds").glob("*.xml"))
assert len(paths)==8
for path in paths:
    assert (a/path).read_bytes()==(b/path).read_bytes(),path
x,y=(json.loads((p/"public/data/sources.json").read_text()) for p in (a,b))
manifest=y.pop("reporting_v1")
assert x==y
assert manifest["schema_version"]==1 and manifest["generated_at"]==x["generated_at"]
rows={r["id"]:r for r in manifest["sources"]}
assert len(rows)==11
assert rows["portland"]["observed_records"]==8000 and rows["portland"]["new_since_previous_success"]==0
assert rows["bend"]["observed_records"] is None and rows["bend"]["retained_records"]==1951
assert rows["hillsboro"]["latest_authoritative_date"] is None
assert rows["hermiston"]["collection_outcome"]=="manual_only"
assert all(rows[n]["mode"]=="uncovered" for n in ["pendleton","la-grande","ontario","baker-city"])
print("8 generated payloads byte-identical; legacy sources equivalent except additive reporting_v1")
