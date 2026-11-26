from pathlib import Path
from oregon_permits import pipeline
from oregon_permits.storage import load_permits
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime
import json,runpy
root=Path.cwd()
stamp="2026-11-26T19:58:39+00:00"
frozen=datetime.fromisoformat(stamp)
class Clock(datetime):
 @classmethod
 def now(cls,tz=None):return frozen
before=json.loads((root/"public/data/sources.json").read_text())
loaded=load_permits(root/"data/permits.json")
collectors=[]
def fail(name):raise RuntimeError(f"{name} fixture source unavailable")
for s in before["sources"]:
 n=s["source"]
 permits=[p for p in loaded.values() if p.jurisdiction==n and p.last_seen_at==before["generated_at"]]
 def collect(n=n,s=s,permits=permits):
  if s["technical_status"]!="ok": return fail(n)
  return SimpleNamespace(source=n,permits=permits,source_url=s["source_url"],note=s["note"])
 collectors.append(SimpleNamespace(name=n,collect=collect,freshness_days=s["freshness_threshold_days"],source_url=s["source_url"]))
with patch.object(pipeline,"datetime",Clock),patch.object(pipeline,"COLLECTORS",collectors):
 runpy.run_module("oregon_permits.main",run_name="__main__")
