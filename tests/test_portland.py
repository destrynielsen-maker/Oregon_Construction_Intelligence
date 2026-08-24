import unittest
from oregon_permits.collectors.portland import PortlandCollector

HTML='''<!doctype html><html><body><h4>Metro: Commercial Issued Building Permits Report</h4>
<table><tr><th>PERMIT DETAILS</th><th>CASE NUMBER</th><th>ADDRESS</th><th>WORK PROPOSED</th><th>TYPE OF USE</th><th>DESCRIPTION OF WORK</th><th>VALUATION</th><th>DATE RECEIVED</th><th>DATE ISSUED</th><th>STATUS</th><th>IVR NUMBER</th><th>PROPERTY LEGAL DESCRIPTION</th><th>PERMIT INFO</th><th>CONTRACTOR</th><th>OWNER 1</th></tr>
<tr><td><a href="https://www.portlandmaps.com/detail/permit/1234567_did/">detail</a></td><td>26-012345-000-00-CO</td><td>100 SW TEST ST, 97201</td><td>New Construction</td><td>Apartments/Condos (3 or more units)</td><td>Test Apartments - Construct new 48 unit apartment building</td><td>12500000</td><td>08/01/2026 10:00</td><td>08/20/2026 11:00</td><td>Issued</td><td>1234567</td><td>TEST LOT</td><td></td><td>Example Construction LLC</td><td>Example Owner LLC</td></tr>
</table></body></html>'''

class Tests(unittest.TestCase):
    def test_parse_portland_commercial_report(self):
        rows=PortlandCollector.parse_page(HTML,"Commercial Issued Building Permits Report","commercial")
        self.assertEqual(len(rows),1)
        p=rows[0]
        self.assertEqual(p.state,"OR")
        self.assertEqual(p.jurisdiction,"Portland")
        self.assertEqual(p.permit_number,"26-012345-000-00-CO")
        self.assertEqual(p.issued_date,"2026-08-20")
        self.assertEqual(p.units,48)
        self.assertEqual(p.valuation,12500000.0)
        self.assertEqual(p.contractor,"Example Construction LLC")

    def test_identity_heading_required(self):
        with self.assertRaises(RuntimeError):
            PortlandCollector.parse_page(HTML,"Residential Issued Building Permits Report","residential")

    def test_foreign_link_rejected(self):
        bad=HTML.replace("www.portlandmaps.com","evil.example")
        with self.assertRaises(RuntimeError):
            PortlandCollector.parse_page(bad,"Commercial Issued Building Permits Report","commercial")

    def test_collect_uses_native_report_params_only(self):
        residential=HTML.replace("Commercial Issued Building Permits Report","Residential Issued Building Permits Report").replace("26-012345-000-00-CO","26-012345-000-00-RS")
        calls=[]
        class Response:
            def __init__(self,text): self.text=text
            def raise_for_status(self): return None
        class Session:
            def get(self,url,params,timeout):
                calls.append(dict(params))
                return Response(residential if params["action"]=="rs-issued" else HTML)
        collector=PortlandCollector(); collector.max_pages=1
        result=collector.collect(Session())
        self.assertEqual(len(result.permits),2)
        self.assertEqual(calls,[{"action":"rs-issued","page":1},{"action":"co-issued","page":1}])
        self.assertTrue(all("start_date" not in x and "end_date" not in x for x in calls))

if __name__=="__main__": unittest.main()
