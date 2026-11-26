import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from oregon_permits.models import Permit
from oregon_permits.pipeline import run
from oregon_permits.reporting import compile_reporting
from oregon_permits.storage import save_permits


def permit(name, number, issued="2026-10-30", **raw):
    return Permit(state="OR", jurisdiction=name, permit_number=number,
                  issued_date=issued, permit_type="Residential Structural - Dwelling",
                  building_use="Single Family Dwelling", address="Fictional Way",
                  project_name="New primary single-family home", raw=raw)


class ReportingTests(unittest.TestCase):
    def test_compiler_unknown_and_observable_counts(self):
        a = permit("Portland", "A")
        b = permit("Portland", "B")
        c = permit("Bend", "B")
        d = permit("Hillsboro", "D", issued_date_basis="first_observed_issued")
        status = [{"source":name,"technical_status":ts} for name,ts in (
            ("Portland","ok"),("Bend","error"),("Hillsboro","ok"),("Eugene","ok"))]
        prior = {n:{"last_success_at":"2026-11-24T00:00:00+00:00"} for n in ("Portland","Bend","Hillsboro")}
        retained = {p.key:p for p in (a,b,c,d)}
        loaded = {p.key:p for p in (a,c)}
        accepted = {"Portland":{a.key,b.key},"Hillsboro":{d.key}}
        report = compile_reporting("2026-11-26T00:00:00+00:00",date(2026,11,26),status,loaded,retained,accepted,prior,True)
        pp,bend,hh,eugene,*gap=report["sources"]
        self.assertEqual([g["id"] for g in gap],["hermiston","pendleton","la-grande","ontario","baker-city"])
        self.assertTrue(all(g["observed_records"] is None for g in gap))
        self.assertEqual(report["schema_version"],1)
        self.assertEqual((pp["new_since_previous_success"],pp["observed_records"],pp["retained_records"]),(1,2,2))
        self.assertEqual((bend["new_since_previous_success"],bend["observed_records"],bend["retained_records"]),(None,None,1))
        self.assertEqual(bend["availability"],"unavailable")
        self.assertEqual((bend["latest_authoritative_date"],bend["latest_date_kind"]),("2026-10-30","issued"))
        self.assertIsNone(hh["latest_authoritative_date"])
        self.assertIsNone(hh["source_age_days"])
        self.assertIsNone(hh["new_since_previous_success"])
        self.assertEqual((eugene["collection_outcome"],eugene["observed_records"]),("no_data",0))
        stale_checkpoint=compile_reporting("x",date(2026,11,26),status,loaded,retained,accepted,prior,False)
        self.assertIsNone(stale_checkpoint["sources"][0]["new_since_previous_success"])

    def test_actual_pipeline_emits_additive_fields_without_altering_source_results(self):
        one=permit("Eugene","1")
        two=permit("Eugene","2")
        collector=SimpleNamespace(name="Eugene",collect=lambda:SimpleNamespace(
            source="Eugene",permits=[one,two],source_url="https://example.invalid",note="fixture"))
        with TemporaryDirectory() as td:
            root=Path(td)
            known="2026-11-24T00:00:00+00:00"
            one.first_seen_at=known
            save_permits(root/"data/permits.json",[one],known)
            state=root/"public/data/sources.json"
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({"generated_at":known,"sources":[{"source":"Eugene","technical_status":"ok",
                                 "records_seen":1,"last_success_at":known}]}))
            with patch("oregon_permits.pipeline.COLLECTORS",[collector]): result=run(root)
            payload=json.loads(state.read_text())
            self.assertEqual(set(payload),{"sources","generated_at","reporting_v1"})
            self.assertEqual(payload["sources"],result["sources"])
            self.assertEqual(payload["reporting_v1"]["sources"][0]["new_since_previous_success"],1)
            output=json.loads((root/"data/permits.json").read_text())
            self.assertEqual(next(p for p in output["permits"] if p["permit_number"]=="1")["first_seen_at"],known)
            self.assertEqual(len(list((root/"public/feeds").glob("*.xml"))),5)
