import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from oregon_permits.classify import classify_permit
from oregon_permits.collectors.hermiston import HermistonCollector


def blank_page(entries):
    return "\n".join((
        "CITY OF HERMISTON BUILDING DEPARTMENT",
        "Structural Permits Issued",
        "10/1/2026 00:00:00 - 10/31/2026 23:59:59",
        *entries,
    ))


def entry(number, use="Single Family Dwelling", work="New", desc="3-BEDROOM SFD WITH ATTACHED GARAGE", issue="10/28/26"):
    return (
        f"Permit: {number}\n"
        "Site Addr: 1 DEMO WAY, HERMISTON    Valuation: $250,001.10\n"
        f"Parcel No: TEST    Date Issued: {issue}\n"
        f"Type of Work: {work}     Category of Construction: {use}     Sq Footage: 1,200\n"
        f"Work Desc: {desc}\n"
        "CCB 123456: DEMO COMPANY\n11 PRIVATE EXAMPLE ST\n000-000-0000\n"
    )


class HermistonTests(unittest.TestCase):
    def setUp(self):
        self.c = HermistonCollector()
        self.month = date(2026, 10, 1)

    def parse(self, rows, today=date(2026, 11, 26), month=None):
        page = SimpleNamespace(extract_text=lambda **_: blank_page(rows))
        with patch("oregon_permits.collectors.hermiston.PdfReader", return_value=SimpleNamespace(pages=[page])):
            return self.c._parse(b"%PDF-fake", "https://www.hermiston.gov/sample.pdf", month or self.month, today)

    def test_primary_only_and_ccb_role_not_assigned(self):
        rows, newest = self.parse([
            entry("407-26-000100-DWL"),
            entry("407-26-000101-FIRE", "Multi-family", issue="10/31/26"),
            entry("407-26-000102-DWL", work="Alteration"),
            entry("407-26-000103-DWL", desc="NEW STAND-ALONE COVERED PATIO"),
            entry("407-26-000104-STR", "Commercial"),
        ])
        self.assertEqual(newest, date(2026, 10, 31))
        self.assertEqual(len(rows), 1)
        row = classify_permit(rows[0])
        self.assertEqual(row.classification, "SINGLE_FAMILY")
        self.assertEqual(row.source_url, "https://www.hermiston.gov/sample.pdf#page=1")
        self.assertTrue(row.qualifies)
        self.assertIsNone(row.contractor)
        self.assertEqual(row.raw["contractor_role"], "unverified")
        self.assertTrue(row.raw["ccb_entry_present"])
        self.assertNotIn("DEMO COMPANY", str(row.to_dict()))

    def test_future_issue_and_month_mismatch_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError, "future issue date"):
            self.parse([entry("407-26-000100-DWL")], today=date(2026, 10, 25))
        with self.assertRaisesRegex(RuntimeError, "month could not be verified"):
            self.parse([entry("407-26-000100-DWL")], month=date(2026, 9, 1))

    def test_empty_or_changed_layout_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "no dated permit blocks"):
            self.parse([])
        with self.assertRaisesRegex(RuntimeError, "unrecognized permit layout"):
            self.parse(["Permit: broken !"])

    def test_official_links_only(self):
        base = self.c.source_url
        self.assertIsNone(self.c._official_url(base, "https://fake.example/commdev/page/2026", "/commdev/page/"))
        self.assertIsNone(self.c._official_url(base, "https://www.hermiston.gov.evil.test/commdev/page/2026", "/commdev/page/"))
        self.assertIsNone(self.c._official_url(base, "http://www.hermiston.gov/commdev/page/2026", "/commdev/page/"))
        self.assertEqual(self.c._official_url(base, "/commdev/page/2026", "/commdev/page/"), "https://www.hermiston.gov/commdev/page/2026")

    def test_dedup_preserves_newer_report_and_rejects_identity_conflict(self):
        rows, newest = self.parse([entry("407-26-000100-DWL")])
        other, _ = self.parse([entry("407-26-000100-DWL")])
        other[0].source_url = "older"
        docs = [(date(2026, 10, 1), "new"), (date(2026, 9, 1), "old")]
        with patch.object(self.c, "_reports", return_value=docs), patch.object(self.c, "_get", return_value=SimpleNamespace(content=b"")):
            with patch.object(self.c, "_parse", side_effect=[(rows, newest), (other, newest)]):
                result = self.c.collect(session=object(), today=date(2026, 11, 26))
                self.assertEqual(result.permits, rows)
                self.assertNotEqual(result.permits[0].source_url, "older")
            other[0].address = "Different address"
            with patch.object(self.c, "_parse", side_effect=[(rows, newest), (other, newest)]):
                with self.assertRaisesRegex(RuntimeError, "Conflicting Hermiston"):
                    self.c.collect(session=object(), today=date(2026, 11, 26))
