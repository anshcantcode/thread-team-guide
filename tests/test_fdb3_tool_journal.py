"""Durable admission must precede effects; receipt loss is not non-submission."""
import json
from pathlib import Path
import tempfile
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from thread_agent.fdb3 import ControllerBridge
from thread_agent.fdb3_evidence import read_tool_journal, verify_tool_trace


class ToolJournalTests(unittest.TestCase):
    def bridge(self,root,call):
        bridge=ControllerBridge({},SimpleNamespace(call=call),None)
        bridge.tool_journal=root/'calls.jsonl'
        bridge.controller.revision=1
        bridge.controller.operations['authored']={'status':'pending'}
        return bridge

    def test_backend_observes_durable_unknown_admission_before_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def backend(name,**args):
                rows=[json.loads(x) for x in (root/'calls.jsonl').read_text().splitlines()]
                self.assertEqual(len(rows),1)
                self.assertEqual(rows[0]['phase'],'dispatch_intent')
                self.assertEqual(rows[0]['call']['outcome'],'unknown')
                return {'status':'success','receipt':'independent-17'}
            bridge=self.bridge(root,backend)
            bridge._invoke({'call_id':'authored','api_name':'reserve','args':{'person':'Iona'}},1)
            rows=[json.loads(x) for x in bridge.tool_journal.read_text().splitlines()]
            self.assertEqual(rows[-1]['phase'],'finished')
            self.assertEqual(rows[-1]['call']['result']['receipt'],'independent-17')

    def test_failed_admission_journal_prevents_backend_invocation(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge=self.bridge(Path(directory),lambda *a,**k:self.fail('Backend must not run'))
            with patch.object(bridge,'_journal_tool',side_effect=OSError('authored disk failure')):
                with self.assertRaises(OSError):
                    bridge._invoke({'call_id':'authored','api_name':'reserve','args':{}},1)
            self.assertFalse(bridge.controller.operations['authored'].get('execution_admitted'))
            self.assertEqual(bridge.calls,[])

    def test_abrupt_exit_after_effect_retains_unknown_possible_invocation(self):
        with tempfile.TemporaryDirectory() as directory:
            script='''import os,sys
from pathlib import Path
from types import SimpleNamespace
from thread_agent.fdb3 import ControllerBridge
root=Path(sys.argv[1])
def backend(*args,**kwargs):
    (root/'effect.txt').write_text('effect occurred')
    os._exit(23)
b=ControllerBridge({},SimpleNamespace(call=backend),None)
b.tool_journal=root/'calls.jsonl'
b.controller.revision=1
b.controller.operations['fixture']={'status':'pending'}
b._invoke({'call_id':'fixture','api_name':'reserve','args':{}},1)
'''
            child=subprocess.run([sys.executable,'-c',script,directory],
                cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=20)
            self.assertEqual(child.returncode,23,child.stderr)
            self.assertTrue((Path(directory)/'effect.txt').is_file())
            evidence=read_tool_journal(Path(directory)/'calls.jsonl')
            self.assertEqual(evidence['completed_invocations'],[])
            self.assertEqual(len(evidence['possible_invocations']),1)
            self.assertEqual(evidence['possible_invocations'][0]['outcome'],'unknown')
            with self.assertRaisesRegex(ValueError,'Unresolved'):
                verify_tool_trace([],Path(directory)/'calls.jsonl')

    def test_final_result_cannot_omit_a_durable_completed_call(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'calls.jsonl'
            call={'call_id':'fixture','function':'lookup','args':{},'outcome':'success'}
            path.write_text(json.dumps({'phase':'finished','call':call})+'\n')
            verify_tool_trace([call],path)
            with self.assertRaisesRegex(ValueError,'differs'):
                verify_tool_trace([],path)

    def test_receipt_journal_failure_preserves_actual_outcome_and_invalidates_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge=self.bridge(Path(directory),lambda *a,**k:{'status':'success','receipt':'independent-19'})
            original=bridge._journal_tool
            def journal(phase,record):
                if phase=='finished':raise OSError('authored receipt disk failure')
                original(phase,record)
            with patch.object(bridge,'_journal_tool',side_effect=journal):
                result,status=bridge._invoke({'call_id':'authored','api_name':'reserve','args':{}},1)
            self.assertEqual(status,'success')
            self.assertEqual(result['receipt'],'independent-19')
            self.assertTrue(bridge.evidence_errors)
            rows=bridge.tool_journal.read_text().splitlines()
            self.assertEqual(len(rows),1)
            self.assertEqual(json.loads(rows[0])['call']['outcome'],'unknown')

    def test_correction_during_journal_flush_wins_before_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge=self.bridge(Path(directory),lambda *a,**k:self.fail('Stale backend must not run'))
            original=bridge._journal_tool
            def journal(phase,record):
                original(phase,record)
                if phase=='dispatch_intent':bridge.speech_started()
            with patch.object(bridge,'_journal_tool',side_effect=journal):
                result=bridge._invoke({'call_id':'authored','api_name':'reserve','args':{}},1)
            self.assertIsNone(result)
            rows=[json.loads(x) for x in bridge.tool_journal.read_text().splitlines()]
            self.assertEqual(rows[-1]['phase'],'not_submitted')
            self.assertEqual(bridge.calls,[])
