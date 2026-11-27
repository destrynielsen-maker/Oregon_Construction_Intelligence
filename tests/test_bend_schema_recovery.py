import unittest
from unittest.mock import patch
from oregon_permits.collectors.bend import BendCollector
from test_bend import row, poly

class BendSchemaRecoveryTests(unittest.TestCase):
    def test_current_city_schema_and_full_collector(self):
        p = poly()
        p.pop("CensusStructureDesc")
        responses = [
            {"features": [{"attributes": row()}]},
            {"features": [{"attributes": p}]},
        ]
        class Response:
            def __init__(self, payload): self.payload = payload
            def raise_for_status(self): pass
            def json(self): return self.payload
        class Session:
            def get(self, url, *, params, timeout):
                payload = responses.pop(0)
                actual = set(payload["features"][0]["attributes"])
                self_fields = set(params["outFields"].split(","))
                if not self_fields <= actual:
                    return Response({"error":{"code":400,"details":["'outFields' parameter is invalid"]}})
                return Response(payload)
        out=BendCollector().collect(Session())
        self.assertEqual(len(out.permits),1)
        self.assertEqual(out.permits[0].units,1)
        self.assertEqual(out.permits[0].contractor,"PAHLISCH HOMES")
        self.assertEqual(out.permits[0].building_use,"Single Family Dwelling")
        self.assertFalse(responses)
