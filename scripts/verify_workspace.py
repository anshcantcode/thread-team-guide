"""Run the repository checks and write a reviewable per-test result record."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
rows=[]
class Recorded(unittest.TextTestResult):
    def addSuccess(self,test): super().addSuccess(test);rows.append({'test':test.id(),'status':'passed'})
    def addFailure(self,test,err): super().addFailure(test,err);rows.append({'test':test.id(),'status':'failed','error':self._exc_info_to_string(err,test)})
    def addError(self,test,err): super().addError(test,err);rows.append({'test':test.id(),'status':'error','error':self._exc_info_to_string(err,test)})
    def addSkip(self,test,reason): super().addSkip(test,reason);rows.append({'test':test.id(),'status':'skipped','reason':reason})

started=time.perf_counter();log=io.StringIO()
suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
result=unittest.TextTestRunner(stream=log,verbosity=1,resultclass=Recorded).run(suite)
node=[]
for path in ['tests/audio-check.mjs','tests/live-audio-check.mjs','tests/workspace-check.mjs']:
    run=subprocess.run(['node',path],cwd=ROOT,capture_output=True,text=True)
    node.append({'script':path,'passed':run.returncode==0,'output':(run.stdout+run.stderr)[-4000:]})
hashes={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for base in ['thread_agent','web','tests','scripts'] for p in (ROOT/base).rglob('*') if p.suffix in ('.py','.js','.mjs','.html','.css') and '__pycache__' not in p.parts}
report={'format':'THREAD expanded verification v1','date':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':round(time.perf_counter()-started,2),
        'passed':result.wasSuccessful() and all(n['passed'] for n in node),'python_test_count':result.testsRun,'python_cases':rows,'javascript_suites':node,
        'coverage_note':'Deterministic execution/controller/protocol/rendering checks. Network responses in unit tests are controlled evidence; this count does not claim model understanding or Samsung hidden-test coverage.',
        'source_sha256':hashes}
(ROOT/'reports'/'verification-expanded.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(log.getvalue())
for entry in node: print(entry['script'],entry['passed'],entry['output'][:250])
print('Verification report: reports/verification-expanded.json')
raise SystemExit(0 if report['passed'] else 1)
