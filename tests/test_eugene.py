import unittest
from unittest.mock import patch

from oregon_permits.classify import classify_permit
from oregon_permits.collectors.eugene import EugeneCollector


def row(**overrides):
    value = {
        "Issued Date": "7/27/2026",
        "Log Number": "26-2694-01",
        "Application Type": "Residential",
        "Permit Type": "B ",
        "Work Involved": "New Building",
        "Address": "511 HONEYSUCKLE LN",
        "Owner": "HELIKSON HOMES LLC",
        "Owner Address": "733 LEIGH ST,EUGENE,OR 97401",
        "Contractor": "Owner",
        "Dwellings": 0.0,
        "Map/Taxlot": "17032812 02300",
        "Occup. Group": "R3",
        "Zoning District": "Low-density Residential Zone",
        "Existing Use": "Single Family Dwelling",
        "Proposed Use": "Single Family Dwelling",
        "Div. Value": "$482,879.96",
        "Permit Fees": "$6,451.58",
        "Project": "Single family dwelling with attached garage.",
        "Special Conditions": "",
    }
    value.update(overrides)
    return value


class Response:
    def __init__(self, text="", content=b""):
        self.text = text
        self.content = content
    def raise_for_status(self):
        return None


class Tests(unittest.TestCase):
    def test_residential_new_build_maps_and_classifies(self):
        permit = EugeneCollector._permit(row())
        self.assertIsNotNone(permit)
        self.assertEqual(permit.state, "OR")
        self.assertEqual(permit.jurisdiction, "Eugene")
        self.assertEqual(permit.issued_date, "2026-07-27")
        self.assertEqual(permit.address, "511 HONEYSUCKLE LN, Eugene, OR")
        self.assertEqual(permit.valuation, 482879.96)
        self.assertEqual(permit.owner, "HELIKSON HOMES LLC")
        self.assertIsNone(permit.contractor)
        classify_permit(permit)
        self.assertTrue(permit.qualifies)
        self.assertEqual(permit.classification, "SINGLE_FAMILY")

    def test_commercial_new_build_maps_contractor_and_value(self):
        permit = EugeneCollector._permit(row(
            **{
                "Log Number": "24-09083-01",
                "Application Type": "Commercial",
                "Address": "90800 HWY 99N",
                "Contractor": "SIERRA CONSTRUCTION CO INC",
                "Existing Use": "Vacant Land",
                "Proposed Use": "Warehouse - General",
                "Div. Value": "$28,351,947.54",
                "Project": "New eCommerce warehouse & distribution facility with parking & fleet storage",
            }
        ))
        classify_permit(permit)
        self.assertTrue(permit.qualifies)
        self.assertEqual(permit.classification, "COMMERCIAL")
        self.assertEqual(permit.contractor, "SIERRA CONSTRUCTION CO INC")
        self.assertEqual(permit.valuation, 28351947.54)
        self.assertIn("log=24-09083-01", permit.source_url)

    def test_accessory_shed_is_not_promoted(self):
        permit = EugeneCollector._permit(row(
            **{
                "Log Number": "25-3453-01",
                "Proposed Use": "Duplex or 2-Family Hs",
                "Existing Use": "Duplex or 2-Family Hs",
                "Project": "New storage shed for washer & dryer use by existing two-family dwelling",
            }
        ))
        self.assertTrue(permit.raw["source_accessory_structure"])
        classify_permit(permit)
        self.assertFalse(permit.qualifies)
        self.assertEqual(permit.classification, "OTHER")

    def test_token_guard(self):
        token = EugeneCollector._token('<input name="__RequestVerificationToken" type="hidden" value="abc123" />')
        self.assertEqual(token, "abc123")
        with self.assertRaises(RuntimeError):
            EugeneCollector._token("<html>No token</html>")

    def test_non_excel_export_rejected(self):
        with self.assertRaises(RuntimeError):
            EugeneCollector._parse_export(b"<html>error</html>")

    def test_collect_posts_official_export_parameters(self):
        calls = []
        permit = EugeneCollector._permit(row())
        class Session:
            def get(self, url, timeout):
                calls.append(("get", url, None))
                return Response('<input name="__RequestVerificationToken" value="token" />')
            def post(self, url, data, timeout):
                calls.append(("post", url, dict(data)))
                return Response(content=b"fake")
        with patch.object(EugeneCollector, "_parse_export", return_value=[permit]):
            result = EugeneCollector().collect(Session())
        self.assertEqual(len(result.permits), 1)
        posted = calls[-1][2]
        self.assertEqual(posted["issued.ApplicationType"], "A")
        self.assertEqual(posted["issued.PermitType"], "B")
        self.assertEqual(posted["issued.FormatForExport"], "True")
        self.assertEqual(posted["issued.ValueOfWork"], "0")


if __name__ == "__main__":
    unittest.main()
