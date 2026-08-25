import unittest
from datetime import date

from oregon_permits.classify import classify_permit
from oregon_permits.collectors.hillsboro import HillsboroCollector
from oregon_permits.models import Permit
from oregon_permits.pipeline import _preserve_observed_issue_date


def row(**overrides):
    value = {
        "application_date": "2026-08-20",
        "permit_number": "STR26-0600",
        "record_type": "Commercial Structural Permit",
        "description": "New warehouse shell",
        "project_name": "North Hillsboro Warehouse",
        "status": "Inspection Phase",
        "expiration_date": "2027-02-20",
        "address": "1000 NE EXAMPLE ST, HILLSBORO OR 97124",
        "source_url": "https://aca-prod.accela.com/HILLSBORO/Cap/CapDetail.aspx?Module=Building&TabName=Building&capID1=26CAP&capID2=00000&capID3=TEST&agencyCode=HILLSBORO&IsToShowInspection=",
    }
    value.update(overrides)
    return value


def detail(**overrides):
    value = {
        "subtype": "New Commercial",
        "new_building_area": 15000.0,
        "stories": 2,
        "parcel": "1N231CC04100",
        "contractor": "EXAMPLE COMMERCIAL BUILDERS LLC",
        "project_description": "New 15,000 square foot warehouse shell",
        "occupancy": "S-1",
        "use": "Warehouse",
        "sqft": 15000.0,
        "construction_type": "III-A",
        "units": None,
        "valuation": 2500000.0,
    }
    value.update(overrides)
    return value


class Tests(unittest.TestCase):
    def test_validated_new_commercial_qualifies(self):
        permit = HillsboroCollector._permit(row(), detail(), True, date(2026, 8, 25))
        self.assertIsNotNone(permit)
        self.assertEqual(permit.jurisdiction, "Hillsboro")
        self.assertEqual(permit.issued_date, "2026-08-25")
        self.assertTrue(permit.raw["source_issued_validated"])
        self.assertEqual(permit.raw["issued_date_basis"], "first_observed_issued")
        classify_permit(permit)
        self.assertTrue(permit.qualifies)
        self.assertEqual(permit.classification, "COMMERCIAL")

    def test_unvalidated_new_construction_is_not_published(self):
        permit = HillsboroCollector._permit(
            row(status="Ready to Issue"), detail(), False, date(2026, 8, 25)
        )
        self.assertIsNotNone(permit)
        self.assertEqual(permit.issued_date, "")
        classify_permit(permit)
        self.assertFalse(permit.qualifies)
        self.assertEqual(permit.classification, "OTHER")

    def test_residential_new_building_maps_single_family(self):
        permit = HillsboroCollector._permit(
            row(
                permit_number="STR26-0601",
                record_type="Residential Structural Permit",
                description="New detached dwelling",
                project_name="Example Residence",
            ),
            detail(
                subtype="New Single Family",
                use="Single Family Dwelling",
                occupancy="R-3",
                units=1,
                contractor="EXAMPLE HOMES LLC",
                valuation=650000.0,
            ),
            True,
            date(2026, 8, 25),
        )
        classify_permit(permit)
        self.assertTrue(permit.qualifies)
        self.assertEqual(permit.classification, "SINGLE_FAMILY")

    def test_multifamily_units_promote(self):
        permit = HillsboroCollector._permit(
            row(
                permit_number="STR26-0602",
                record_type="Commercial Structural Permit",
                description="New apartment building",
                project_name="Example Apartments",
            ),
            detail(
                subtype="New Commercial",
                use="Apartments",
                occupancy="R-2",
                units=48,
                valuation=12000000.0,
            ),
            True,
            date(2026, 8, 25),
        )
        classify_permit(permit)
        self.assertTrue(permit.qualifies)
        self.assertEqual(permit.classification, "MULTIFAMILY")
        self.assertEqual(permit.units, 48)

    def test_non_new_subtype_is_rejected_before_classification(self):
        permit = HillsboroCollector._permit(
            row(status="Inspection Phase"),
            detail(subtype="Addition/Alteration Commercial"),
            True,
            date(2026, 8, 25),
        )
        self.assertIsNone(permit)

    def test_first_observed_issue_date_is_preserved(self):
        old = Permit(
            state="OR",
            jurisdiction="Hillsboro",
            permit_number="STR26-0600",
            issued_date="2026-08-22",
            raw={"issued_date_basis": "first_observed_issued"},
        )
        current = HillsboroCollector._permit(row(), detail(), True, date(2026, 8, 25))
        self.assertEqual(current.issued_date, "2026-08-25")
        _preserve_observed_issue_date(current, old)
        self.assertEqual(current.issued_date, "2026-08-22")
        self.assertEqual(current.raw["first_observed_issued_date"], "2026-08-22")


if __name__ == "__main__":
    unittest.main()
