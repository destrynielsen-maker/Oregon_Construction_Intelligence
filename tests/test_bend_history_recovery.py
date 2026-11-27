import copy
import unittest
from oregon_permits.models import Permit
from oregon_permits.pipeline import _preserve_bend_recovery_observation
from oregon_permits.classify import classify_permit

class BendHistoryRecoveryTests(unittest.TestCase):
    def test_missing_gc_and_changed_raw_remain_separate_from_accepted_history(self):
        old=Permit("OR","Bend","PRNC123456","2026-05-08",building_use="Single Family Dwelling",project_name="New construction",contractor="Prior reported GC",owner="Reported owner",raw={"work_proposed":"New construction","general_contractor_reported":"Prior reported GC","table_object_id":1,"extra_evidence":"preserve"},first_seen_at="2026-05-09")
        classify_permit(old)
        before=copy.deepcopy(old.to_dict())
        new=copy.deepcopy(old)
        new.contractor=None
        new.raw={"work_proposed":"New construction","general_contractor_reported":"","table_object_id":2}
        classify_permit(new)
        kept=_preserve_bend_recovery_observation(new,old,"2026-11-27")
        self.assertEqual(old.to_dict(),before)
        self.assertEqual(kept.contractor,old.contractor)
        self.assertEqual(kept.first_seen_at,old.first_seen_at)
        self.assertEqual(kept.score,old.score)
        self.assertEqual({k:kept.raw[k] for k in old.raw},old.raw)
        events=kept.raw["bend_recovery_observations_v1"]
        self.assertEqual(events[0]["fields"]["contractor"],None)
        self.assertEqual(events[0]["raw_changed"]["general_contractor_reported"],"")
        self.assertEqual(events[0]["raw_absent"],["extra_evidence"])
        repeat=_preserve_bend_recovery_observation(new,kept,"2026-11-28")
        self.assertEqual(repeat.raw,kept.raw)
        returned=_preserve_bend_recovery_observation(old,repeat,"2026-11-29")
        self.assertEqual(len(returned.raw["bend_recovery_observations_v1"]),2)
        self.assertEqual(returned.raw["bend_recovery_observations_v1"][1]["fields"],{})
    def test_new_and_other_jurisdiction_unchanged(self):
        p=Permit("OR","Bend","PRNC123456","2026-11-24")
        self.assertIs(_preserve_bend_recovery_observation(p,None,"now"),p)
        p.jurisdiction="Eugene"
        self.assertIs(_preserve_bend_recovery_observation(p,copy.deepcopy(p),"now"),p)
