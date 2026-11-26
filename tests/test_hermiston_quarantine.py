from datetime import date
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from oregon_permits import pipeline
from oregon_permits.models import Permit
from oregon_permits.storage import load_permits, save_permits

FLAG = "OREGON_QUARANTINE_HERMISTON_OUTPUT"
COLLECT = "OREGON_ENABLE_HERMISTON_PILOT"


class PublicationQuarantineTests(unittest.TestCase):
    def test_default_then_quarantine_then_restore_without_touching_history(self):
        def record(state, market, number):
            return Permit(state, market, number, date.today().isoformat(),
                          building_use="single family dwelling", project_name="new single family dwelling",
                          contractor="FICTIONAL SHARED HOMES", first_seen_at="2026-10-15T00:00:00+00:00")

        rows = [record("OR", "Hermiston", "CITY-1"), record("OR", "Eugene", "CITY-1"),
                record("WA", "Hermiston", "CITY-1")]
        ids = {r.key for r in rows}
        only_city = rows[0].key
        with tempfile.TemporaryDirectory() as temp, patch.object(pipeline, "COLLECTORS", []):
            root = Path(temp)
            history = root/"data/permits.json"
            save_permits(history, rows, "2026-11-26T00:00:00+00:00")
            def run(value):
                settings = {COLLECT: "0"}
                if value is not None:
                    settings[FLAG] = value
                with patch.dict(os.environ, settings, clear=True):
                    return pipeline.run(root)
            def visible():
                return {Permit.from_dict(x).key for x in json.loads((root/"public/data/permits.json").read_text())["permits"]}
            def builders():
                return json.loads((root/"public/data/builders.json").read_text())["builders"]
            def feeds():
                files = list((root/"public/feeds").glob("*.xml"))
                self.assertEqual(len(files), 5)
                return {file.name:{e.text for e in ET.parse(file).findall(".//guid")} for file in files}

            default = run(None)
            self.assertNotIn("qualifying_published", default)
            self.assertFalse(default["sources"])
            self.assertEqual(visible(), ids)
            self.assertEqual(builders()[0]["permits_90d"], 3)
            baseline_feeds = feeds()
            stored = {k:v.to_dict() for k,v in load_permits(history).items()}

            hidden = run("1")
            self.assertEqual((hidden["qualifying_stored"],hidden["qualifying_published"],
                              hidden["hermiston_qualifying_withheld"]), (3, 2, 1))
            self.assertEqual(visible(), ids - {only_city})
            self.assertEqual(builders()[0]["permits_90d"], 2)
            self.assertEqual({k:v.to_dict() for k,v in load_permits(history).items()}, stored)
            self.assertTrue(all(only_city not in ids for ids in feeds().values()))
            self.assertEqual(hidden["sources"][0]["technical_status"], "not_attempted")
            self.assertEqual(hidden["sources"][0]["publication_status"], "quarantined")

            restored = run("0")
            self.assertNotIn("hermiston_qualifying_withheld", restored)
            self.assertEqual(visible(), ids)
            self.assertEqual(builders()[0]["permits_90d"], 3)
            self.assertEqual(feeds(), baseline_feeds)
            self.assertEqual({k:v.to_dict() for k,v in load_permits(history).items()}, stored)

    def test_live_health_is_preserved_and_annotated_instead_of_replaced(self):
        statuses = [{"source":"Hermiston","status":"degraded","technical_status":"error","note":"Source unavailable."},
                    {"source":"Portland","status":"healthy","note":"Unchanged"}]
        with patch.dict(os.environ, {FLAG: "1"}):
            public, summary = pipeline._publication_view([], statuses)
        self.assertEqual(public, [])
        self.assertEqual(summary["hermiston_qualifying_withheld"], 0)
        self.assertEqual(len(statuses), 2)
        self.assertEqual(statuses[0]["technical_status"], "error")
        self.assertEqual(statuses[0]["publication_status"], "quarantined")
        self.assertTrue(statuses[0]["note"].startswith("Source unavailable."))
        self.assertEqual(statuses[1], {"source":"Portland","status":"healthy","note":"Unchanged"})
