"""Independent read-only QA of production #329; no publication or mutation."""
import hashlib, io, json, subprocess, tarfile, time, urllib.request, zipfile
from collections import Counter
from pathlib import PurePosixPath
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

REPO="destrynielsen-maker/Oregon_Construction_Intelligence"
RUN=45975017251
MERGE="075b3fd56871181b81da2d799f634c644e89e5e6"
BEFORE="b4b8ebf6a806a8fc56ce9bf2d74e61dd9b627099"
SITE="https://destrynielsen-maker.github.io/Oregon_Construction_Intelligence/"
def gh(path):
    return subprocess.check_output(["gh","api",f"repos/{REPO}/{path}"])
def git(*args):
    return subprocess.check_output(["git",*args])
def sha(b): return hashlib.sha256(b).hexdigest()
def blob(commit,path): return git("show",f"{commit}:{path}")
def key(r): return (r["state"],r["jurisdiction"].strip().lower(),r["permit_number"].strip().lower())
def rows(doc):
    items=doc["permits"]
    index={key(p):p for p in items}
    assert len(index)==len(items),"duplicate permit identities"
    return index
def live(name):
    req=urllib.request.Request(SITE+name+"?accept=329-"+str(time.time_ns()),headers={"Cache-Control":"no-cache","User-Agent":"Oregon-public-snapshot-verifier/1.0"})
    with urllib.request.urlopen(req,timeout=60) as r: return r.read()

for i in range(36):
    run=json.loads(gh(f"actions/runs/{RUN}"))
    assert run["head_sha"]==MERGE and run["event"]=="push"
    if run["status"]=="completed": break
    time.sleep(15)
else: raise RuntimeError("production did not complete in acceptance window")
assert run["conclusion"]=="success",f"Production {run['conclusion']}"
a=json.loads(gh(f"actions/runs/{RUN}/artifacts"))["artifacts"]
a=[x for x in a if x["name"]=="github-pages" and not x["expired"]]
assert len(a)==1
a=a[0]
zip_data=gh(f"actions/artifacts/{a['id']}/zip")
assert a["digest"]=="sha256:"+sha(zip_data)
git("fetch","origin","main")
main=git("rev-parse","origin/main").decode().strip()
assert git("rev-parse",main+"^").decode().strip()==MERGE,"not exact generated commit"
print("Exact main",main,"artifact",a["id"],a["digest"],flush=True)
required=["index.html","data/permits.json","data/builders.json","data/sources.json","feeds/commercial.xml","feeds/multifamily.xml","feeds/new-construction.xml","feeds/single-family.xml","feeds/top-opportunities.xml"]
with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
    names=[x for x in z.namelist() if x.endswith(".tar") or x.endswith(".tar.gz")]
    assert len(names)==1,names
    with tarfile.open(fileobj=io.BytesIO(z.read(names[0])),mode="r:*") as t:
        members={str(PurePosixPath(m.name)):m for m in t.getmembers() if m.isfile()}
        for name in required:
            archive=t.extractfile(members[name]).read()
            assert archive==blob(main,"public/"+name),name+" archive/main mismatch"
            assert archive==live(name),name+" archive/live mismatch"
            print("LIVE EXACT",name,sha(archive),flush=True)
before=rows(json.loads(blob(BEFORE,"data/permits.json")))
after=rows(json.loads(blob(main,"data/permits.json")))
assert not before.keys()-after.keys(),"historical identities lost"
assert all(after[k]["first_seen_at"]==p["first_seen_at"] for k,p in before.items()),"first-seen changed"
new=[p for k,p in after.items() if k not in before]
bend_new=[p for p in new if p["jurisdiction"]=="Bend"]
bend_old={k:p for k,p in before.items() if p["jurisdiction"]=="Bend"}
other_changes=Counter()
for k,old in before.items():
    current=after[k]
    if k in bend_old:
        assert all(current.get(f)==v for f,v in old.items() if f not in ("last_seen_at","raw")),(k,"accepted Bend fields changed")
        assert all((current.get("raw") or {}).get(f)==v for f,v in (old.get("raw") or {}).items()),(k,"Bend raw evidence lost")
    else:
        fields=[f for f,v in old.items() if f not in ("last_seen_at","raw") and current.get(f)!=v]
        if fields: other_changes.update((old["jurisdiction"],f) for f in fields)
        if any((current.get("raw") or {}).get(f)!=v for f,v in (old.get("raw") or {}).items()):
            other_changes[(old["jurisdiction"],"raw changed")]+=1
public=rows(json.loads(blob(main,"public/data/permits.json")))
assert public=={k:p for k,p in after.items() if p["qualifies"]},"published permits differ from qualified store"
prior_pub=rows(json.loads(blob(BEFORE,"public/data/permits.json")))
assert not ({k for k,p in prior_pub.items() if p["jurisdiction"]=="Bend"}-public.keys())
sources=json.loads(blob(main,"public/data/sources.json"))
status=next(x for x in sources["sources"] if x["source"]=="Bend")
assert status["technical_status"]=="ok" and status["freshness_status"]=="fresh" and status["records_seen"]>0,status
assert status["newest_permit_date"]>="2026-11-24"
assert bend_new and sum(p["qualifies"] for p in bend_new)>0
# Validate every published RSS GUID and its score/issue date against actual data;
# the existing production feed policy sorts by issued date then score and caps at 250.
for filename in required:
    if not filename.startswith("feeds/"): continue
    root=ET.fromstring(blob(main,"public/"+filename))
    items=root.findall("./channel/item")
    expected={ "|".join(k):p for k,p in public.items() }
    pred={"feeds/commercial.xml":lambda p:p["classification"]=="COMMERCIAL","feeds/multifamily.xml":lambda p:p["classification"]=="MULTIFAMILY","feeds/single-family.xml":lambda p:p["classification"]=="SINGLE_FAMILY","feeds/top-opportunities.xml":lambda p:p["score"]>=30,"feeds/new-construction.xml":lambda p:True}[filename]
    eligible={g:p for g,p in expected.items() if pred(p)}
    guids=[e.findtext("guid") for e in items]
    assert len(guids)==len(set(guids))==min(250,len(eligible))
    assert set(guids)<=eligible.keys()
    rank=lambda p:(p["issued_date"],p["score"])
    if guids:
        last=min(rank(eligible[g]) for g in guids)
        assert all(rank(p)<=last for g,p in eligible.items() if g not in guids)
    for item in items:
        p=eligible[item.findtext("guid")]
        desc=item.findtext("description") or ""
        assert f"Score: {p['score']}" in desc and f"Issued: {p['issued_date']}" in desc
# Recompute builder aggregates independently from all qualified published rows.
from oregon_permits.dashboard import builder_rollups
from oregon_permits.models import Permit
expected=builder_rollups([Permit.from_dict(p) for p in public.values()])
actual=json.loads(blob(main,"public/data/builders.json"))["builders"]
assert {p["contractor"]:p for p in expected}=={p["contractor"]:p for p in actual}
print("PRODUCTION ACCEPTANCE",json.dumps({"main":main,"archive_id":a["id"],"historical_before":len(before),"historical_after":len(after),"historical_preserved":len(before),"published_before":len(prior_pub),"published_after":len(public),"new_bend":len(bend_new),"new_bend_qualifying":sum(p["qualifies"] for p in bend_new),"bend_date_min":min(p["issued_date"] for p in bend_new),"bend_date_max":max(p["issued_date"] for p in bend_new),"bend_source":status,"builders":len(actual),"other_source_new":dict(Counter(p["jurisdiction"] for p in new if p["jurisdiction"]!="Bend")),"other_source_observed_field_changes":{"/".join(k):v for k,v in other_changes.items()}},indent=2),flush=True)
