from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from oregon_permits.classify import classify_permit
from oregon_permits.collectors.malheur import MalheurCollector


OCTOBER = date(2026, 10, 1)
OCTOBER_URL = "https://bldgmalheurco.org/wp-content/uploads/2026/11/oct.pdf"
SEPTEMBER_URL = "https://bldgmalheurco.org/wp-content/uploads/2026/10/sep.pdf"


def issued_record(number, category="Single Family Dwelling", work="New", issued="10/18/26"):
    return (
        f"{number} Issued: {issued} Fees: $120.00 Valuation: $250,000.00\n"
        "1 EXAMPLE WAY, ONTARIO, OR 97914 12A345Address: Parcel:\n"
        "Owner: EXAMPLE PRIVATE OWNER\nLicensed Prof: EXAMPLE PROFESSIONAL\n"
        f"Category of Construction: {category} Type of Work: {work}\n"
        "Work Description: New primary building\n"
    )


class MalheurTests(unittest.TestCase):
    def setUp(self):
        self.collector = MalheurCollector()

    def parse(self, records, count=None):
        count = len(records) if count is None else count
        page = (
            "MALHEUR COUNTY BUILDING DEPARTMENT\nPermits Issued\n"
            "10/1/2026 through 10/31/2026\nRecord Types Selected: -All-\n"
            + "".join(records) + f"{count} permits issued $270,000.00\n"
        )
        pdf = SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda: page)])
        with patch("oregon_permits.collectors.malheur.PdfReader", return_value=pdf):
            return self.collector._parse(b"%PDF-sample", OCTOBER_URL, OCTOBER)

    def test_selects_two_completed_official_months_at_year_rollover(self):
        html = (
            f'<a href="{SEPTEMBER_URL}">Permits Issued Details September 2026</a>'
            f'<a href="{OCTOBER_URL}"><span>Permits Issued Detail October 2026</span></a>'
            '<a href="/wp-content/uploads/2026/12/nov.pdf">Permits Issued Detail November 2026</a>'
            '<a href="/wp-content/uploads/2026/12/dec.pdf">Permits Issued Detail December 2026</a>'
            '<a href="https://foreign.invalid/">Permits Issued Detail January 2027</a>'
        ).encode()
        self.assertEqual(self.collector._reports(html, date(2026, 11, 27)), [
            (OCTOBER, OCTOBER_URL), (date(2026, 9, 1), SEPTEMBER_URL),
        ])
        self.assertEqual([month.month for month, _ in self.collector._reports(html, date(2027, 1, 2))], [12, 11])

    def test_rejects_official_looking_link_to_unrelated_host(self):
        html = (
            f'<a href="{SEPTEMBER_URL}">Permits Issued Details September 2026</a>'
            '<a href="https://bldgmalheurco.org.other.invalid/doc.pdf">Permits Issued Detail October 2026</a>'
        ).encode()
        with self.assertRaisesRegex(RuntimeError, "outside its official"):
            self.collector._reports(html, date(2026, 11, 27))

    def test_get_stops_on_denied_response_without_retry_or_redirect(self):
        session = MagicMock()
        response = session.get.return_value.__enter__.return_value
        response.raise_for_status.side_effect = RuntimeError("403")
        with self.assertRaisesRegex(RuntimeError, "403"):
            self.collector._get(session, OCTOBER_URL)
        session.get.assert_called_once_with(OCTOBER_URL, timeout=(8, 20), allow_redirects=False, stream=True)
        response.iter_content.assert_not_called()

    def test_primary_only_uses_official_issue_date_and_source_identity(self):
        rows, seen, latest = self.parse([
            issued_record("541-26-000100-STR"),
            issued_record("541-26-000101-STR", "Commercial"),
            issued_record("541-26-000102-STR", "Two Family Dwelling"),
            issued_record("541-26-000103-ELEC", "Commercial", issued="10/30/26"),
            issued_record("541-26-000104-STR", "Detached Accessory Structure"),
            issued_record("541-26-000105-STR", "Commercial", "Addition"),
            issued_record("541-26-000106-STR-01", "Commercial"),
        ])
        self.assertEqual((seen, latest), (7, date(2026, 10, 30)))
        self.assertEqual([classify_permit(row).classification for row in rows], ["SINGLE_FAMILY", "COMMERCIAL", "MULTIFAMILY"])
        self.assertEqual([row.issued_date for row in rows], ["2026-10-18"] * 3)
        self.assertEqual(rows[0].jurisdiction, "Malheur County")  # Postal city is Ontario.
        self.assertEqual(rows[0].source_url, OCTOBER_URL + "#page=1")
        self.assertEqual(rows[0].raw["issuing_agency_code"], "541")
        self.assertEqual(rows[0].valuation, 250000)
        self.assertIsNone(rows[0].owner)
        self.assertIsNone(rows[0].contractor)

    def test_issue_date_issuer_identity_and_printed_count_fail_closed(self):
        row = issued_record("541-26-000100-STR")
        for records in ([issued_record("653-26-000100-STR")], [row, row],
                        [issued_record("541-26-000100-STR", issued="11/1/26")]):
            with self.subTest(records=records), self.assertRaisesRegex(RuntimeError, "Unexpected Malheur issuer"):
                self.parse(records)
        with self.assertRaisesRegex(RuntimeError, "printed grand total"):
            self.parse([row], count=2)
        self.assertEqual(self.parse([]), ([], 0, None))
