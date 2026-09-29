from copy import deepcopy
import unittest
from scripts.fdb3_summarize import judged_pass


class DiagnosticPassAccounting(unittest.TestCase):
    def test_raw_true_with_failed_judge_never_counts(self):
        good={'strict':{'passed':True},'judge_enabled':True,
              'judge_requests':[{'valid':True,'status_code':200}]}
        self.assertTrue(judged_pass(good))
        failed=deepcopy(good)
        failed['judge_requests'].insert(0,{'valid':False,'status_code':200})
        self.assertFalse(judged_pass(failed))
        failed=deepcopy(good)
        failed['native_judge_calls']=[{'outcome':'error','inference_requests':0}]
        self.assertFalse(judged_pass(failed))
        failed=deepcopy(good)
        failed['infrastructure_error']='silently fell back'
        self.assertFalse(judged_pass(failed))

    def test_truncated_context_cannot_be_rescued_by_a_raw_pass(self):
        report={'strict':{'passed':True},'judge_enabled':True,
            'judge_requests':[{'valid':True,'status_code':200}],
            'native_judge_calls':[{'outcome':'success','inference_requests':1,
                'native_response':{'truncated':True}}]}
        self.assertFalse(judged_pass(report))
