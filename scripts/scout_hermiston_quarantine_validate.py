"""Exercise actual CLI in temp dirs; official-format fixtures, never live network."""
import contextlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from datetime import date
import runpy
import shutil
import tempfile
from unittest.mock import patch
import xml.etree.ElementTree as ET

from oregon_permits import pipeline
from oregon_permits.collectors.hermiston import HermistonCollector


def rows(root, path):
    permits = json.loads((root / path).read_text())["permits"]
    result = {(p["state"], p["jurisdiction"].strip().casefold(), p["permit_number"].strip().casefold()): p for p in permits}
    assert len(result) == len(permits)
    return result


def active(root):
    return rows(root, "public/data/permits.json")


def history(root):
    return rows(root, "data/permits.json")


def feeds(root):
    output = {f.name: [g.text for g in ET.parse(f).findall(".//guid")] for f in (root / "public/feeds").glob("*.xml")}
    assert len(output) == 5
    return output


def builders(root):
    return json.loads((root / "public/data/builders.json").read_text())["builders"]


def is_hermiston(identity):
    return identity[:2] == ("OR", "hermiston")



def simulated_report():
    lines = ["CITY OF HERMISTON BUILDING DEPARTMENT", "Structural Permits Issued",
             "10/1/2026 00:00:00 - 10/31/2026 23:59:59"]
    for i in range(1, 34):
        lines += [f"Permit: 407-26-{900000+i:06d}-DWL",
                  f"Site Addr: {i} FICTIONAL WAY, HERMISTON    Valuation: $250,000",
                  "Parcel No: DEMO    Date Issued: 10/30/26",
                  "Type of Work: New     Category of Construction: Single Family Dwelling     Sq Footage: 1,200",
                  "Work Desc: NEW PRIMARY SFD WITH ATTACHED GARAGE",
                  "CCB 123456: FICTIONAL COMPANY"]
    return "\n".join(lines)

def emit(root, collect="0", quarantine="0"):
    original = Path.cwd()
    actual_run = pipeline.run
    os.chdir(root)
    try:
        pdf = SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda **_: simulated_report())])
        with patch.object(pipeline, "run", side_effect=lambda _repo_root: actual_run(root)), patch.object(
            pipeline, "COLLECTORS", []
        ), patch.object(
            HermistonCollector, "_reports", return_value=[(date(2026, 10, 1), "https://www.hermiston.gov/october-fixture.pdf")]
        ), patch.object(HermistonCollector, "_get", return_value=SimpleNamespace(content=b"%PDF-synthetic")), patch(
            "oregon_permits.collectors.hermiston.PdfReader", return_value=pdf
        ), patch.dict(os.environ, {
            "OREGON_ENABLE_HERMISTON_PILOT": collect,
            "OREGON_QUARANTINE_HERMISTON_OUTPUT": quarantine,
        }), contextlib.redirect_stdout(io.StringIO()):
            runpy.run_module("oregon_permits.main", run_name="__main__")
    finally:
        os.chdir(original)


with tempfile.TemporaryDirectory(prefix="scout-hermiston-qa-") as directory:
    root = Path(directory)
    for key in ("data", "public"):
        shutil.copytree(key, root / key)
    before = history(root)
    assert len(before) >= 10722 and not any(map(is_hermiston, before))
    emit(root)
    assert history(root) == before
    public_before, rss_before, builders_before = active(root), feeds(root), builders(root)

    emit(root, collect="1")
    after = history(root)
    public_opt = active(root)
    imported = {k: v for k, v in after.items() if k not in before}
    assert before.keys() <= after.keys() and all(before[k] == after[k] for k in before)
    assert len(imported) == 33 and all(map(is_hermiston, imported))
    assert max(p["issued_date"] for p in imported.values()) == "2026-10-30"
    assert all(not (p["owner"] or p["contractor"]) for p in imported.values())
    assert public_opt.keys() - public_before.keys() == imported.keys()
    assert builders_before == builders(root)
    # Normalize through the stored sort before testing a cached-publication restore.
    emit(root)
    assert history(root) == after and active(root) == public_opt
    rss_opt = feeds(root)
    assert rss_opt != rss_before

    emit(root, quarantine="1")
    assert history(root) == after and active(root) == public_before
    assert feeds(root) == rss_before and builders(root) == builders_before
    sources = json.loads((root / "public/data/sources.json").read_text())["sources"]
    hermiston = next(s for s in sources if s["source"] == "Hermiston")
    assert hermiston["publication_status"] == "quarantined"
    assert hermiston["technical_status"] == "not_attempted"
    assert hermiston["withheld_qualifying_records"] == 33

    emit(root)
    assert history(root) == after and active(root) == public_opt
    assert feeds(root) == rss_opt and builders(root) == builders_before

    print(json.dumps({"history_initial": len(before), "history_end": len(after),
        "published_default": len(public_before), "published_opt_in": len(public_opt),
        "published_quarantine": len(public_before), "published_restore": len(public_opt),
        "hermiston_opt_in_quarantine_restore": [33, 0, 33], "restored_all_five_ordered_rss": True,
        "first_seen_and_history_preserved": True, "newest_issued": "2026-10-30",
        "fixture": "synthetic extracted-text official layout; no network"}))
