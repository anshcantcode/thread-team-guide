import copy
import json
from pathlib import Path
import tempfile
import unittest
import wave
from thread_agent.fdb3_evidence import verify_series, file_hash


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        identity = dict.fromkeys(("code", "configuration", "dataset", "benchmark", "judge", "dependencies"), "fixture-only")
        artifacts={}
        for kind in identity:
            path=self.root/(kind+'.fixture'); path.write_text('independent fixture '+kind)
            identity[kind]=file_hash(path); artifacts[kind]={'path':path.name,'sha256':identity[kind]}
        self.series = {"frozen_identity": identity,"identity_artifacts":artifacts, "recordings": [str(i) for i in range(100)], "runs": []}
        for index in range(3):
            rid = "run-" + str(index)
            cases = []
            for case_id in self.series["recordings"]:
                case = {"recording":case_id,"status":"completed","strict_pass":True,"input_sha256":"fixture"}
                for kind in ("inference", "evaluation", "audio"):
                    path = self.root / f"{rid}-{case_id}-{kind}.json"
                    body = {"run_id":rid,"status":"completed","input_sha256":"fixture",
                            "recording":case_id,
                            "actual_tool_calls":[{"function":"independent_fixture"}],
                            "judge_enabled":True,"strict":{"passed":True}}
                    path.write_text(json.dumps(body))
                    if kind == "audio":
                        with wave.open(str(path),"wb") as audio:
                            audio.setparams((1,2,16000,0,"NONE","fixture"))
                            audio.writeframes(b"\x01\x00"*160)
                    case[kind] = {"path":path.name,"sha256":file_hash(path)}
                cases.append(case)
                inference=self.root/case['inference']['path']
                body=json.loads(inference.read_text()); body.update(qualification_eligible=True,fresh_inference=True,
                    identity=identity,audio_sha256=case['audio']['sha256'],transcript='Independent fixture speech')
                inference.write_text(json.dumps(body)); case['inference']['sha256']=file_hash(inference)
                evaluation=self.root/case['evaluation']['path']
                body=json.loads(evaluation.read_text()); body.update(qualification_eligible=True,
                    inference_sha256=case['inference']['sha256'],judge_identity_sha256=identity['judge'],
                    judge_requests=[{'valid':True,'status_code':200}])
                evaluation.write_text(json.dumps(body)); case['evaluation']['sha256']=file_hash(evaluation)
            self.series["runs"].append({"run_id":rid,"identity":identity,"registered_at":1,"started_at":2,
                "fresh_inference":True,"judge_enabled":True,"cases":cases})

    def test_accepts_complete_fixture_structure_not_actual_qualification(self):
        self.assertTrue(verify_series(self.series,self.root)["passed"])

    def test_missing_case_and_duplicate_case_fail(self):
        for duplicate in (False, True):
            series = copy.deepcopy(self.series)
            series["runs"][0]["cases"].pop()
            if duplicate:
                series["runs"][0]["cases"].append(series["runs"][0]["cases"][0])
            self.assertFalse(verify_series(series,self.root)["passed"])

    def test_zero_exit_style_claim_cannot_replace_missing_files(self):
        for file in self.root.iterdir():
            file.unlink()
        self.assertFalse(verify_series(self.series,self.root)["passed"])

    def test_judge_disabled_changed_configuration_or_late_registration_fail(self):
        for change in ({"judge_enabled":False},{"identity":{}},{"registered_at":3},{"fresh_inference":False}):
            series = copy.deepcopy(self.series)
            series["runs"][1].update(change)
            self.assertFalse(verify_series(series,self.root)["passed"])

    def test_malformed_report_or_empty_tool_trace_fails_even_with_rehashed_artifact(self):
        artifact = self.series["runs"][0]["cases"][0]["inference"]
        path = self.root / artifact["path"]
        for content in ("{}", "not json", json.dumps({"run_id":"run-0","status":"completed","input_sha256":"fixture","actual_tool_calls":[]})):
            path.write_text(content)
            artifact["sha256"] = file_hash(path)
            self.assertFalse(verify_series(self.series,self.root)["passed"])

    def test_failed_attempt_is_not_hidden_by_other_two(self):
        self.series["runs"][2]["cases"][99]["strict_pass"] = False
        self.assertFalse(verify_series(self.series,self.root)["passed"])

    def test_one_saved_audio_cannot_stand_in_for_fresh_runs(self):
        self.series["runs"][1]["cases"][0]["audio"] = self.series["runs"][0]["cases"][0]["audio"]
        self.assertFalse(verify_series(self.series,self.root)["passed"])

    def test_explicit_failed_or_diagnostic_judge_cannot_qualify(self):
        case=self.series['runs'][0]['cases'][0]
        artifact=case['evaluation']; path=self.root/artifact['path']
        body=json.loads(path.read_text())
        body.update(infrastructure_error='judge failed',qualification_eligible=False,
                    judge_requests=[],native_judge_calls=[{'outcome':'error'}])
        path.write_text(json.dumps(body)); artifact['sha256']=file_hash(path)
        self.assertFalse(verify_series(self.series,self.root)['passed'])

    def test_identity_declarations_without_actual_artifacts_fail(self):
        self.series['identity_artifacts'].pop('code')
        self.assertFalse(verify_series(self.series,self.root)['passed'])

    def test_evaluation_for_different_inference_fails(self):
        case=self.series['runs'][0]['cases'][0]
        path=self.root/case['evaluation']['path']; body=json.loads(path.read_text())
        body['inference_sha256']='different-run'
        path.write_text(json.dumps(body)); case['evaluation']['sha256']=file_hash(path)
        self.assertFalse(verify_series(self.series,self.root)['passed'])


if __name__ == "__main__": unittest.main()
