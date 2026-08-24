import unittest
from oregon_permits.models import Permit
from oregon_permits.classify import classify_permit

def p(number="26-012345-000-00-CO", work="New Construction", use="Business", desc="Construct new office", units=None, value=1000000, kind="commercial"):
    return Permit(state="OR",jurisdiction="Portland",permit_number=number,issued_date="2026-08-20",
        permit_type=f"{kind} / {work}",building_use=use,project_name=desc,units=units,valuation=value,
        contractor="Example GC",owner="Example Owner",raw={"report_kind":kind,"work_proposed":work,"type_of_use":use,"description":desc})

class Tests(unittest.TestCase):
    def test_commercial_new(self):
        x=p(); classify_permit(x)
        self.assertTrue(x.qualifies); self.assertEqual(x.classification,"COMMERCIAL"); self.assertGreaterEqual(x.score,40)

    def test_multifamily_new(self):
        x=p(use="Apartments/Condos (3 or more units)",desc="Construct new 48 unit apartment",units=48); classify_permit(x)
        self.assertTrue(x.qualifies); self.assertEqual(x.classification,"MULTIFAMILY")

    def test_single_family_new(self):
        x=p(number="26-111111-000-00-RS",use="Single Family Dwelling",desc="Construct new one-family dwelling",kind="residential",value=650000); classify_permit(x)
        self.assertTrue(x.qualifies); self.assertEqual(x.classification,"SINGLE_FAMILY")

    def test_deferred_submittal_excluded(self):
        x=p(number="24-029091-DFS-11-CO",use="Apartments/Condos (3 or more units)",desc="Jamii Court Apts DFS 11",units=60); classify_permit(x)
        self.assertFalse(x.qualifies)

    def test_revision_excluded(self):
        x=p(number="25-098533-REV-01-CO",use="Apartments/Condos (3 or more units)",desc="Apartment revision",units=20); classify_permit(x)
        self.assertFalse(x.qualifies)

    def test_alteration_excluded(self):
        x=p(work="Alteration",desc="Tenant improvement"); classify_permit(x)
        self.assertFalse(x.qualifies)

if __name__=="__main__": unittest.main()
