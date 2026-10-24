import unittest
from analyze_scores_v10 import analyze,rating,FIELDS
class AnalysisTests(unittest.TestCase):
 def setUp(self):
  self.runs=[{'run_id':str(i),'model_family':'model','flow':'flow','reference_fee_cny':'0.01'} for i in range(2)]
  self.scores=[dict(run_id=str(i),F='2',E='2',C='2',B='2',key_error='no',standard_u='no',factual_claims_present='yes',citation_required='yes',na_reason='',adjudicated_by='TEST_ONLY',reason='synthetic test',rule_version='test') for i in range(2)]
 def test_blank_is_missing(self):
  r=analyze(self.runs,[{k:(str(i) if k=='run_id' else '') for k in FIELDS} for i in range(2)])[0]
  self.assertIsNone(r['pass_n']);self.assertIsNone(r['cost_per_qualified'])
 def test_zero_pass_cost_undefined(self):
  for r in self.scores:r['key_error']='yes'
  x=analyze(self.runs,self.scores)[0];self.assertEqual(x['pass_n'],0);self.assertIsNone(x['cost_per_qualified'])
 def test_u_keeps_full_cost_and_denominator(self):
  self.scores[1]['standard_u']='yes';x=analyze(self.runs,self.scores)[0]
  self.assertEqual(x['reference_fee_cny'],'0.02');self.assertEqual(x['all_slots_pass_rate_lower'],.5);self.assertEqual(x['all_slots_pass_rate_upper'],1);self.assertIsNone(x['cost_per_qualified'])
 def test_na_cannot_hide_claims(self):
  self.scores[0]['F']='NA';self.scores[0]['na_reason']='empty claim'
  with self.assertRaises(ValueError):rating(self.scores[0])
 def test_partial_rejected(self):
  self.scores[1]={k:('1' if k=='run_id' else '') for k in FIELDS}
  with self.assertRaises(ValueError):analyze(self.runs,self.scores)
 def test_real_no_claim_na(self):
  r=self.scores[0];r.update(F='NA',E='NA',factual_claims_present='no',citation_required='no',na_reason='truly no factual claim or required evidence citation')
  self.assertEqual(rating(r),1)
if __name__=='__main__':unittest.main()
