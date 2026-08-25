import unittest
from oregon_permits.models import Permit
from oregon_permits.classify import classify_permit

def p(number="26-012345-000-00-CO", work="New Construction", use="Business", desc="Construct new office", units=None, value=1000000, kind="commercial", authoritative=False):
    return Permit(state="OR",jurisdiction="Portland",permit_number=number,issued_date="2026-08-20",
        permit_type=f"{kind} / {work}",building_use=use,project_name=desc,units=units,valuation=value,
        contractor="Example GC",owner="Example Owner",raw={"report_kind":kind,"work_proposed":work,"type_of_use":use,"description":desc,"source_construction_layer":authoritative})

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

    def test_single_family_with_adu_stays_single_family(self):
        x=p(number="22-104491-000-00-RS",use="Single Family Dwelling",desc="New single family residence with basement ADU",units=2,kind="residential",authoritative=True)
        classify_permit(x)
        self.assertTrue(x.qualifies); self.assertEqual(x.classification,"SINGLE_FAMILY")

    def test_standalone_adu_excluded(self):
        x=p(number="26-111112-000-00-RS",use="Accessory Dwelling Unit",desc="New detached ADU",units=1,kind="residential",authoritative=True)
        classify_permit(x)
        self.assertFalse(x.qualifies)

    def test_authoritative_layer_alone_is_not_new_construction_evidence(self):
        x=p(number="26-222222-000-00-RS",work="Construction Permit",use="R-3",desc="Residence",kind="residential",authoritative=True)
        classify_permit(x)
        self.assertFalse(x.qualifies)

    def test_authoritative_new_structure_qualifies(self):
        x=p(number="26-222223-000-00-RS",work="New Structure",use="R-3",desc="Residence",kind="residential",authoritative=True)
        classify_permit(x)
        self.assertTrue(x.qualifies); self.assertEqual(x.classification,"SINGLE_FAMILY")

    def test_authoritative_commercial_units_promote_to_multifamily(self):
        x=p(work="New Structure",use="R-2",desc="Housing",units=24,kind="commercial",authoritative=True)
        classify_permit(x)
        self.assertTrue(x.qualifies); self.assertEqual(x.classification,"MULTIFAMILY")

    def test_remodel_with_new_finishes_stays_excluded(self):
        x=p(work="Alteration",desc="Remodel office with new finishes",authoritative=True)
        classify_permit(x)
        self.assertFalse(x.qualifies)

    def test_demolition_plus_construct_new_building_qualifies(self):
        x=p(work="New Construction",desc="Demolish existing shed and construct new office building",authoritative=True)
        classify_permit(x)
        self.assertTrue(x.qualifies); self.assertEqual(x.classification,"COMMERCIAL")

    def test_deferred_submittal_excluded(self):
        x=p(number="24-029091-DFS-11-CO",use="Apartments/Condos (3 or more units)",desc="New Jamii Court Apts DFS 11",units=60,authoritative=True); classify_permit(x)
        self.assertFalse(x.qualifies)

    def test_revision_excluded(self):
        x=p(number="25-098533-REV-01-CO",use="Apartments/Condos (3 or more units)",desc="New apartment revision",units=20,authoritative=True); classify_permit(x)
        self.assertFalse(x.qualifies)

    def test_alteration_excluded_without_authoritative_layer(self):
        x=p(work="Alteration",desc="Tenant improvement"); classify_permit(x)
        self.assertFalse(x.qualifies)

if __name__=="__main__": unittest.main()
