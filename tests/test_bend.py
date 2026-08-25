import unittest

from oregon_permits.classify import classify_permit
from oregon_permits.collectors.bend import BendCollector


def row(**overrides):
    value = {
        "ApplicationNumber": "PRNC202603983",
        "StatusDesc": "Permit(s) Issued",
        "ApplicationType": "New Construction/Installation",
        "BuildingUse": "Single Family Dwelling",
        "ApplicationDate": 1781568000000,
        "PermitTypeCode": "BLDG",
        "PermitTypeDescription": "Building Permit",
        "PermitIssueDate": 1787583387000,
        "SQFT": 2060,
        "ProjectValuation": 307887.98,
        "ZoningDesc": "Residential Urban Standard Density",
        "Description": "PT416 - 3156 NE Terra Pl - Single Family Dwelling",
        "Address": "3156 NE TERRA PL, BEND, OR 97701",
        "Owner": "PAHLISCH HOMES AT PETROSA LP",
        "TAXLOT": "171223AB01920",
        "ContractorName": None,
        "GeneralContractorName": "PAHLISCH HOMES",
        "OBJECTID": 85246,
    }
    value.update(overrides)
    return value


def poly(**overrides):
    value = {
        "ApplicationNumber": "PRNC202603983",
        "IssueDate": 1787583387000,
        "SQFT": 2060,
        "Units": 1,
        "ProjectValuation": 307887.98,
        "TypeDesc": "New Construction/Installation",
        "UseDesc": "Single Family Dwelling",
        "BuildingCategory": "Residential",
        "Owner": "PAHLISCH HOMES AT PETROSA LP",
        "CensusStructureDesc": "Single Family Houses - Detached",
        "Address": "3156 NE TERRA PL, BEND, OR 97701",
        "OBJECTID": 426000,
    }
    value.update(overrides)
    return value


class Tests(unittest.TestCase):
    def test_single_family_maps_and_classifies(self):
        permit = BendCollector._permit(row(), poly())
        self.assertEqual(permit.jurisdiction, "Bend")
        self.assertEqual(permit.contractor, "PAHLISCH HOMES")
        self.assertEqual(permit.owner, "PAHLISCH HOMES AT PETROSA LP")
        self.assertEqual(permit.units, 1)
        self.assertEqual(permit.valuation, 307887.98)
        classify_permit(permit)
        self.assertTrue(permit.qualifies)
        self.assertEqual(permit.classification, "SINGLE_FAMILY")

    def test_multifamily_units_promote(self):
        permit = BendCollector._permit(
            row(
                ApplicationNumber="PRNC202600111",
                BuildingUse="Multi-Family Dwelling",
                Description="New apartment building",
                GeneralContractorName="EXAMPLE BUILDERS",
                ProjectValuation=8000000,
            ),
            poly(ApplicationNumber="PRNC202600111", Units=36, UseDesc="Multi-Family Dwelling", BuildingCategory="Residential"),
        )
        classify_permit(permit)
        self.assertTrue(permit.qualifies)
        self.assertEqual(permit.classification, "MULTIFAMILY")
        self.assertEqual(permit.units, 36)

    def test_commercial_new_construction(self):
        permit = BendCollector._permit(
            row(
                ApplicationNumber="PRNC202600222",
                BuildingUse="Warehouse",
                Description="New warehouse and distribution building",
                GeneralContractorName="EXAMPLE COMMERCIAL GC",
                ProjectValuation=12000000,
            ),
            poly(ApplicationNumber="PRNC202600222", Units=None, UseDesc="Warehouse", BuildingCategory="Non-Residential"),
        )
        classify_permit(permit)
        self.assertTrue(permit.qualifies)
        self.assertEqual(permit.classification, "COMMERCIAL")

    def test_accessory_structure_excluded(self):
        permit = BendCollector._permit(
            row(
                ApplicationNumber="PRNC202600333",
                BuildingUse="Shop/Garage/Shed/Greenhouse/Carport",
                Description="New detached storage shed",
            ),
            poly(ApplicationNumber="PRNC202600333", Units=None, UseDesc="Shop/Garage/Shed/Greenhouse/Carport"),
        )
        classify_permit(permit)
        self.assertFalse(permit.qualifies)
        self.assertEqual(permit.classification, "OTHER")

    def test_schema_guard(self):
        class Response:
            def raise_for_status(self):
                pass
            def json(self):
                return {"features": [{"attributes": {"ApplicationNumber": "PRNC1"}}]}
        class Session:
            def get(self, *args, **kwargs):
                return Response()
        with self.assertRaises(RuntimeError):
            BendCollector._query(Session(), BendCollector.table_url, "1=1", "*", "OBJECTID DESC", "test", {"ApplicationNumber", "PermitIssueDate"})


if __name__ == "__main__":
    unittest.main()
