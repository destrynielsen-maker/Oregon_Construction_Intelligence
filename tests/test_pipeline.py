import unittest
from oregon_permits.models import Permit
from oregon_permits.pipeline import _keep_existing

class Tests(unittest.TestCase):
    def test_prunes_malformed_portland_construction_history(self):
        bad=Permit(state="OR",jurisdiction="Portland",permit_number="Residential 1 & 2 Family Permit",issued_date="2022-01-01",raw={"source_construction_layer":True})
        good=Permit(state="OR",jurisdiction="Portland",permit_number="2025-056087-000-00-RS",issued_date="2026-08-20",raw={"source_construction_layer":True})
        self.assertFalse(_keep_existing(bad))
        self.assertTrue(_keep_existing(good))

    def test_non_portland_history_is_untouched(self):
        p=Permit(state="OR",jurisdiction="Other",permit_number="anything",issued_date="2026-01-01",raw={})
        self.assertTrue(_keep_existing(p))

if __name__=="__main__": unittest.main()
