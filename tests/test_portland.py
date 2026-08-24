import unittest
from datetime import datetime, timezone
from oregon_permits.collectors.portland import PortlandCollector


def ms(y,m,d):
    return int(datetime(y,m,d,tzinfo=timezone.utc).timestamp()*1000)


def feature(number, issued, link, **overrides):
    attrs={
        "PERMIT":number,"TYPE":"New Construction","WORK_DESCRIPTION":"New Structure","ISSUED":issued,
        "DESCRIPTION":"Construct residential structure","STATUS":"Issued","GIS_PROCESS_STATUS":"MAPPED - ISSUED",
        "HOUSE":"100","DIRECTION":"SE","PROPSTREET":"TEST","STREETTYPE":"ST","CITY":"PORTLAND",
        "PORTLAND_MAPS_URL":link,"OCCUPANCYGROUP":"Single Family Dwelling","CONSTRUCTIONTYPE":"V-B",
        "SUBMITTEDVALUATION":650000,"FINALVALUATION":700000,"NUMNEWUNITS":1,"TOTALSQFT":2400,
        "NUMBSTORIES":2,"COUNTY":"Multnomah","OBJECTID":1,
    }
    attrs.update(overrides)
    return {"attributes":attrs}


class Response:
    def __init__(self,payload): self.payload=payload
    def raise_for_status(self): return None
    def json(self): return self.payload


class Tests(unittest.TestCase):
    def test_collect_maps_official_layers(self):
        residential={"features":[feature("26-100001-000-00-RS",ms(2026,8,22),"https://www.portlandmaps.com/detail/permit/1001_did/")]}
        commercial={"features":[feature(
            "26-200001-000-00-CO",ms(2026,8,21),"https://www.portlandmaps.com/detail/permit/2001_did/",
            DESCRIPTION="Construct 48 unit apartment building",OCCUPANCYGROUP="Apartments",NUMNEWUNITS=48,
            FINALVALUATION=12500000,OBJECTID=2
        )]}
        calls=[]
        class Session:
            def get(self,url,params,timeout):
                calls.append((url,dict(params)))
                return Response(residential if "/5/query" in url else commercial)
        result=PortlandCollector().collect(Session())
        self.assertEqual(len(result.permits),2)
        r=next(p for p in result.permits if p.permit_number.endswith("RS"))
        c=next(p for p in result.permits if p.permit_number.endswith("CO"))
        self.assertEqual(r.state,"OR"); self.assertEqual(r.jurisdiction,"Portland")
        self.assertEqual(r.issued_date,"2026-08-22"); self.assertEqual(r.valuation,700000.0)
        self.assertEqual(r.address,"100 SE TEST ST, PORTLAND, OR")
        self.assertEqual(c.units,48); self.assertEqual(c.valuation,12500000.0)
        self.assertTrue(all(p[1]["where"]=="ISSUED IS NOT NULL" for p in calls))
        self.assertTrue(all(p[1]["orderByFields"]=="ISSUED DESC" for p in calls))
        self.assertTrue(all(p[1]["returnGeometry"]=="false" for p in calls))

    def test_arcgis_error_rejected(self):
        with self.assertRaises(RuntimeError):
            PortlandCollector._validate_payload({"error":{"code":500}},"Residential Construction Permit")

    def test_schema_guard_requires_portland_fields(self):
        with self.assertRaises(RuntimeError):
            PortlandCollector._validate_payload({"features":[{"attributes":{"PERMIT":"1"}}]},"Residential Construction Permit")

    def test_foreign_permit_link_rejected(self):
        attrs=feature("26-300001-000-00-RS",ms(2026,8,20),"https://evil.example/permit/1")["attributes"]
        with self.assertRaises(RuntimeError):
            PortlandCollector._permit(attrs,5,"Residential Construction Permit","residential")

if __name__=="__main__": unittest.main()
