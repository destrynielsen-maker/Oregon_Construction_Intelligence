import unittest
from datetime import date

from oregon_permits.classify import classify_permit
from oregon_permits.collectors.beaverton import BeavertonCollector


def contact(capacity, first="", last="", company=""):
    return {
        "capacity": {"description": capacity},
        "contact": {
            "identity": {
                "firstName": first,
                "lastName": last,
                "companyName": company,
            }
        },
    }


def row(**overrides):
    value = {
        "id": 24433,
        "applicationNumber": "R2026-01592",
        "commonId": 30686,
        "applicationName": "LOLICH FARMS SCHOLLS HEIGHTS LOT 109",
        "applicationDateTime": "2026-03-30T15:07:38.0000000-07:00",
        "issuedDateTime": "2026-08-25T10:27:02.0000000-07:00",
        "status": "Pending",
        "statusDescription": "Processing",
        "processState": "Permit Issued",
        "workType": "HouseOrAdu",
        "workTypeDescription": "New House/ADU",
        "occupancyType": "SFRdetNew",
        "occupancyTypeDescription": "SFR Detached - New (Combo permit)",
        "declaredValuation": 323890.56,
        "calculatedValuation": 0,
        "squareFootage": 1647,
        "comments": "SINGLE FAMILY DETACHED HOME",
        "locationLine1": "12760 SW DOUBLETOP DR ",
        "locationLine2": "BEAVERTON OR 97007 ",
        "applicationType": {"code": "R", "description": "Residential Building Permit", "id": 1013},
        "applicationContacts": [
            contact("Contractor", "South Cooper Mountain Owner LLC", "South Cooper Mountain Owner LLC"),
            contact("Electrical contractor", last="GARNER ELECTRIC"),
        ],
        "primaryContactName": "Taylor Morrison Northwest LLC",
    }
    value.update(overrides)
    return value


class Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")

    def json(self):
        return self._payload


class QuerySession:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response({"data": self.rows})


class Tests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 8, 25)
        self.cutoff = date(2026, 7, 11)

    def test_issued_new_sfr_qualifies_even_when_status_says_processing(self):
        permit = BeavertonCollector._permit(row(), self.cutoff, self.today)
        self.assertIsNotNone(permit)
        classify_permit(permit)
        self.assertTrue(permit.qualifies)
        self.assertEqual(permit.classification, "SINGLE_FAMILY")
        self.assertEqual(permit.issued_date, "2026-08-25")
        self.assertEqual(permit.contractor, "South Cooper Mountain Owner LLC")
        self.assertEqual(permit.valuation, 323890.56)
        self.assertEqual((permit.raw or {}).get("total_sqft"), 1647.0)

    def test_minimum_pending_issue_date_is_rejected(self):
        permit = BeavertonCollector._permit(
            row(issuedDateTime="0001-01-01T00:00:00.0000000-08:00"),
            self.cutoff,
            self.today,
        )
        self.assertIsNone(permit)

    def test_multifamily_newcon_qualifies(self):
        permit = BeavertonCollector._permit(
            row(
                applicationNumber="MF2026-01234",
                applicationType={"code": "MF", "description": "Multifamily Building Permit", "id": 1008},
                workType="NewCon",
                workTypeDescription="New Construction",
                occupancyType="MFNew",
                occupancyTypeDescription="Multifamily - New",
                applicationName="New apartment building",
            ),
            self.cutoff,
            self.today,
        )
        self.assertIsNotNone(permit)
        classify_permit(permit)
        self.assertTrue(permit.qualifies)
        self.assertEqual(permit.classification, "MULTIFAMILY")

    def test_commercial_newcon_qualifies(self):
        permit = BeavertonCollector._permit(
            row(
                applicationNumber="C2026-01234",
                applicationType={"code": "C", "description": "Commercial Building Permit", "id": 1001},
                workType="NewCon",
                workTypeDescription="New Construction",
                occupancyType="CommInd",
                occupancyTypeDescription="Commercial or industrial",
                applicationName="New commercial building",
            ),
            self.cutoff,
            self.today,
        )
        self.assertIsNotNone(permit)
        classify_permit(permit)
        self.assertTrue(permit.qualifies)
        self.assertEqual(permit.classification, "COMMERCIAL")

    def test_non_primary_newcon_trade_or_sewer_is_rejected(self):
        permit = BeavertonCollector._permit(
            row(
                applicationNumber="SWR2026-01645",
                applicationType={"code": "SWR", "description": "Sewer Permit", "id": 1016},
                workType="NewCon",
                workTypeDescription="New Construction",
            ),
            self.cutoff,
            self.today,
        )
        self.assertIsNone(permit)

    def test_house_or_adu_requires_detached_new_occupancy(self):
        permit = BeavertonCollector._permit(
            row(occupancyType="ADUNew", occupancyTypeDescription="Accessory Dwelling Unit - New"),
            self.cutoff,
            self.today,
        )
        self.assertIsNone(permit)

    def test_old_and_future_issue_dates_are_rejected(self):
        old = BeavertonCollector._permit(row(issuedDateTime="2026-07-01T10:00:00-07:00"), self.cutoff, self.today)
        future = BeavertonCollector._permit(row(issuedDateTime="2026-12-01T10:00:00-08:00"), self.cutoff, self.today)
        self.assertIsNone(old)
        self.assertIsNone(future)

    def test_query_uses_native_work_type_filter_and_issue_sort(self):
        session = QuerySession([row()])
        rows = BeavertonCollector._query(session, "HouseOrAdu", 1)
        self.assertEqual(len(rows), 1)
        _, kwargs = session.calls[0]
        self.assertEqual(kwargs["params"]["WorkType"], "HouseOrAdu")
        self.assertEqual(kwargs["params"]["OrderBy"], "[{Property:IssuedDateTime,Direction:Desc}]")
        self.assertIn("Max:20", kwargs["params"]["Page"])

    def test_query_fails_closed_if_work_type_filter_leaks(self):
        session = QuerySession([row(workType="Deck")])
        with self.assertRaises(RuntimeError):
            BeavertonCollector._query(session, "HouseOrAdu", 1)

    def test_collect_queries_both_new_construction_work_types(self):
        class Probe(BeavertonCollector):
            page_size = 2
            max_pages_per_work_type = 3

            @staticmethod
            def _today():
                return date(2026, 8, 25)

            @classmethod
            def _query(cls, session, work_type, start):
                session.seen.append((work_type, start))
                if start > 1:
                    return []
                if work_type == "HouseOrAdu":
                    return [row()]
                return [
                    row(
                        applicationNumber="C2026-01234",
                        applicationType={"code": "C", "description": "Commercial Building Permit", "id": 1001},
                        workType="NewCon",
                        workTypeDescription="New Construction",
                        occupancyType="CommInd",
                        occupancyTypeDescription="Commercial or industrial",
                    )
                ]

        class Session:
            def __init__(self):
                self.headers = {}
                self.seen = []

            def get(self, url, **kwargs):
                if url.endswith("anonymous/auth"):
                    return Response({"sessionId": "anon", "userName": "BeavertonProdAnon"})
                return Response({"ok": True})

        session = Session()
        result = Probe().collect(session)
        self.assertEqual(len(result.permits), 2)
        self.assertEqual(session.seen, [("HouseOrAdu", 1), ("NewCon", 1)])


if __name__ == "__main__":
    unittest.main()
