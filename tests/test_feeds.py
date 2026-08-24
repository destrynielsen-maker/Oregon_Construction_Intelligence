import tempfile, unittest
from pathlib import Path
import xml.etree.ElementTree as ET
from oregon_permits.models import Permit
from oregon_permits.feeds import write_all_feeds

class Tests(unittest.TestCase):
    def test_feeds_are_valid_xml(self):
        p=Permit(state="OR",jurisdiction="Portland",permit_number="1",issued_date="2026-08-20",project_name="New project",source_url="https://www.portlandmaps.com/",classification="COMMERCIAL",qualifies=True,score=45)
        with tempfile.TemporaryDirectory() as d:
            out=Path(d); write_all_feeds(out,[p],"https://example.com/")
            for name in ("new-construction.xml","single-family.xml","multifamily.xml","commercial.xml","top-opportunities.xml"):
                ET.parse(out/name)
if __name__=="__main__": unittest.main()
