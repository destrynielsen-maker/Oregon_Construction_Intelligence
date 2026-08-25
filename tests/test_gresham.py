import unittest
from datetime import date

from oregon_permits.classify import classify_permit
from oregon_permits.collectors.gresham import GreshamCollector


def row(**overrides):
    value = {
        "CaseId": "a4873058-455a-4931-86e2-d08510232e27",
        "CaseNumber": "BLDR-26-02076",
        "CaseTypeId": "type-id",
        "CaseType": "Residential New Construction",
        "CaseWorkclassId": "workclass-id",
        "CaseWorkclass": "New Construction",
        "CaseStatusId": "status-id",
        "CaseStatus": "Issued",
        "ProjectName": "Butler Creek Subdivision- Clearwater Homes",
        "IssueDate": "2026-08-24T00:00:00",
        "ApplyDate": "2026-04-23T11:17:12.81",
        "AddressDisplay": "3675 SW RODLUN RD GRESHAM OR 97080",
        "MainParcel": "R123456",
        "Description": "Butler Creek Lot 106 - Clearwater Homes",
        "ModuleName": 2,
    }
    value.update(overrides)
    return value


class Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = "json"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")

    def json(self):
        return self._payload


class Session:
    def __init__(self, pages):
        self.headers = {}
        self.pages = list(pages)
        self.posts = []

    def get(self, url, **kwargs):
        if url.endswith("api/energov/search/criteria"):
            return Response({"Result": {"PermitCriteria": {}}})
        return Response({"ok": True})

    def post(self, url, **kwargs):
        self.posts.append(kwargs["json"])
        return Response({"Result": self.pages.pop(0)})


class Tests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 8, 25)
        self.cutoff = date(2026, 7, 11)

    def test_residential_new_construction_qualifies(self):
        permit = GreshamCollector._permit(row(), self.cutoff, self.today)
        self.assertIsNotNone(permit)
        classify_permit(permit)
        self.assertTrue(permit.qualifies)
        self.assertEqual(permit.classification, "SINGLE_FAMILY")
        self.assertEqual(permit.issued_date, "2026-08-24")

    def test_multifamily_new_construction_qualifies(self):
        permit = GreshamCollector._permit(
            row(
                CaseNumber="BLDMF-25-02376",
                CaseType="Multi-Family New Construction",
                Description="Townhome units 103-107",
            ),
            self.cutoff,
            self.today,
        )
        self.assertIsNotNone(permit)
        classify_permit(permit)
        self.assertTrue(permit.qualifies)
        self.assertEqual(permit.classification, "MULTIFAMILY")

    def test_middle_housing_residential_new_maps_multifamily(self):
        permit = GreshamCollector._permit(
            row(
                CaseNumber="BLDR-26-02722",
                ProjectName="Beaver Creek Meadows",
                Description="Middle Housing Lot #21 Cedar Ridge Homes",
            ),
            self.cutoff,
            self.today,
        )
        self.assertIsNotNone(permit)
        classify_permit(permit)
        self.assertEqual(permit.classification, "MULTIFAMILY")

    def test_commercial_new_construction_qualifies(self):
        permit = GreshamCollector._permit(
            row(CaseNumber="BLDC-26-09999", CaseType="Commercial New Construction"),
            self.cutoff,
            self.today,
        )
        self.assertIsNotNone(permit)
        classify_permit(permit)
        self.assertEqual(permit.classification, "COMMERCIAL")

    def test_trade_permit_with_new_in_description_is_rejected(self):
        permit = GreshamCollector._permit(
            row(
                CaseNumber="ELEC-26-04439",
                CaseType="Commercial Electrical",
                CaseWorkclass="Electrical Commercial",
                Description="Install new LED lighting",
            ),
            self.cutoff,
            self.today,
        )
        self.assertIsNone(permit)

    def test_future_and_old_issue_dates_are_rejected(self):
        future = GreshamCollector._permit(row(IssueDate="2026-12-07T08:56:48"), self.cutoff, self.today)
        old = GreshamCollector._permit(row(IssueDate="2026-07-01T00:00:00"), self.cutoff, self.today)
        self.assertIsNone(future)
        self.assertIsNone(old)

    def test_collect_pages_newest_first_and_stops_on_old_page(self):
        class Probe(GreshamCollector):
            page_size = 2
            max_pages = 4
            lookback_days = 45

            @staticmethod
            def _today():
                return date(2026, 8, 25)

        recent = row()
        future = row(CaseNumber="BLDR-26-09998", IssueDate="2026-12-07T00:00:00")
        old1 = row(CaseNumber="BLDR-26-01001", IssueDate="2026-07-01T00:00:00")
        old2 = row(CaseNumber="BLDR-26-01002", IssueDate="2026-06-30T00:00:00")
        session = Session([
            {"EntityResults": [recent, future]},
            {"EntityResults": [old1, old2]},
        ])

        result = Probe().collect(session)
        self.assertEqual([p.permit_number for p in result.permits], ["BLDR-26-02076"])
        self.assertEqual(len(session.posts), 2)
        self.assertEqual(session.posts[0]["FilterModule"], 2)
        self.assertEqual(session.posts[0]["SortBy"], "IssueDate")
        self.assertFalse(session.posts[0]["SortAscending"])

    def test_module_leak_fails_closed(self):
        class Probe(GreshamCollector):
            page_size = 1
            max_pages = 1

            @staticmethod
            def _today():
                return date(2026, 8, 25)

        leaked = row(ModuleName=8)
        session = Session([{"EntityResults": [leaked]}])
        with self.assertRaises(RuntimeError):
            Probe().collect(session)


if __name__ == "__main__":
    unittest.main()
