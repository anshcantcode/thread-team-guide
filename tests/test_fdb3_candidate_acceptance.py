import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

_spec = importlib.util.spec_from_file_location("candidate_acceptance", Path(__file__).resolve().parents[1] / "scripts/fdb3_accept_candidate.py")
acceptance = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(acceptance)


class CandidateAcceptanceTests(unittest.TestCase):
    def test_complete_evidence_accepts_but_source_or_artifact_change_blocks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, run = root / "source", root / "run"
            (source / "participant").mkdir(parents=True)
            code = source / "participant/agent.py"
            code.write_text("# frozen candidate\n", encoding="utf-8")
            lock = source / "requirements-fdb3.lock"
            lock.write_text("# pinned\n", encoding="utf-8")
            folder = run / "fresh"
            folder.mkdir(parents=True)
            def write(path, value):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value), encoding="utf-8")
            for name in ("input.wav", "faithful.txt", "actual-asr.txt"):
                (folder / name).write_bytes(b"authored fixture bytes")
            write(folder / "expected-metadata.json", {"expected_tool_calls": []})
            settings = {"model_sha256": "0" * 64, "dependency_lock_sha256": acceptance.digest(lock),
                        "planner_prompt_cache": True, "planner_arg_normalize": True, "planner_guidance": 1,
                        "planner_follow_up": "1", "planner_cache_scope": "scenario", "whisper_prompt": "contract",
                        "whisper_sha256": {"model.bin": "1" * 64}}
            for name in ("contract", "evaluator"):
                write(folder / name / "pinned.py", "# unchanged upstream")
                settings[name + "_sha256"] = {"pinned.py": acceptance.digest(folder / name / "pinned.py")}
            (folder / "source/participant").mkdir(parents=True)
            (folder / "source/participant/agent.py").write_bytes(code.read_bytes())
            identity = {**settings, "source_sha256": {"participant/agent.py": acceptance.digest(code)},
                        "input_sha256": acceptance.digest(folder / "input.wav"),
                        "faithful_transcript_sha256": acceptance.digest(folder / "faithful.txt"),
                        "evaluator_only_metadata_sha256": acceptance.digest(folder / "expected-metadata.json")}
            write(folder / "identity.json", identity)
            modes = {}
            for mode in acceptance.MODES:
                inference = {"status": "completed", "actual_tool_calls": [], "input_sha256": identity["input_sha256"]}
                if mode != "live_audio":
                    inference["replay_text_sha256"] = acceptance.digest(folder / ("faithful.txt" if mode == "text" else "actual-asr.txt"))
                write(folder / mode / "inference/result.json", inference)
                evaluation = {"status": "completed", "strict": {"passed": True},
                              "input_sha256": identity["input_sha256"],
                              "metadata_sha256": identity["evaluator_only_metadata_sha256"],
                              "evaluator_sha256": identity["evaluator_sha256"],
                              "inference_sha256": acceptance.digest(folder / mode / "inference/result.json")}
                artifacts = {"evaluation.json": evaluation, "layers.json": {"dispatched_calls_and_results": []},
                             "inference/result.json": inference}
                for name, value in artifacts.items():
                    write(folder / mode / name, value)
                modes[mode] = {"status": "completed", "exit_code": 0, "strict_pass": True,
                               "artifact_sha256": {name: acceptance.digest(folder / mode / name) for name in artifacts}}
            write(folder / "report.json", {"identity_sha256": acceptance.digest(folder / "identity.json"), "modes": modes})
            spec = {"fixtures": [{"id": "fresh", "expected_tool_calls": []}]}
            check = lambda: acceptance.assess(spec, run, source, settings)
            self.assertTrue(check()["eligible_for_next_experiment"])
            code.write_text("# changed candidate\n", encoding="utf-8")
            self.assertFalse(check()["eligible_for_next_experiment"])
            code.write_text("# frozen candidate\n", encoding="utf-8")
            # Even self-consistent file inventories cannot excuse wrong links.
            inference_path = folder / "text/inference/result.json"
            result = acceptance.read(inference_path)
            result["input_sha256"] = "WRONG-AUDIO-HASH"
            write(inference_path, result)
            modes["text"]["artifact_sha256"]["inference/result.json"] = acceptance.digest(inference_path)
            evaluation_path = folder / "text/evaluation.json"
            evaluation = acceptance.read(evaluation_path)
            evaluation["inference_sha256"] = acceptance.digest(inference_path)
            write(evaluation_path, evaluation)
            modes["text"]["artifact_sha256"]["evaluation.json"] = acceptance.digest(evaluation_path)
            write(folder / "report.json", {"identity_sha256": acceptance.digest(folder / "identity.json"), "modes": modes})
            self.assertFalse(check()["eligible_for_next_experiment"])

    def test_null_or_missing_settings_are_not_frozen_identity(self):
        self.assertFalse(acceptance.valid_settings(dict.fromkeys(acceptance.SETTINGS)))
        self.assertFalse(acceptance.valid_settings({}))

    def test_identifier_punctuation_is_not_normalized_away(self):
        wanted = {"function": "add_to_cart", "args": {"product_id": "SKU_A", "quantity": 1}}
        actual = {"function": "add_to_cart", "args": {"product_id": "SKU A", "quantity": 1}}
        self.assertEqual(acceptance.unmatched_writes([wanted], [actual]), [actual])

    def test_duplicate_write_is_not_consumed_twice(self):
        call = {"function": "add_to_cart", "args": {"product_id": "A4", "quantity": 2}}
        self.assertEqual(acceptance.unmatched_writes([call], [call]), [])
        self.assertEqual(acceptance.unmatched_writes([call], [call, call]), [call])

    def test_recognition_error_remains_unmatched(self):
        wanted = {"function": "book_flight", "args": {"passenger_name": "Nadia Perez"}}
        heard = {"function": "book_flight", "args": {"passenger_name": "Malia Perez"}}
        self.assertEqual(acceptance.unmatched_writes([wanted], [heard]), [heard])

    def test_sign_decimal_and_boolean_are_not_erased(self):
        def call(value):
            return {"function": "update_search_filter", "args": {"filter_name": "threshold", "value": value}}
        for expected, actual in [("-10", "10"), ("1.5", "15"), (True, 1)]:
            self.assertEqual(acceptance.unmatched_writes([call(expected)], [call(actual)]), [call(actual)])

    def test_read_is_not_mislabelled_as_write(self):
        self.assertEqual(acceptance.unmatched_writes([], [{"function": "search_products", "args": {"query": "lamp"}}]), [])

    def test_missing_run_or_empty_fixture_set_cannot_promote(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for fixtures in ([], [{"id": "fresh_control", "expected_tool_calls": []}]):
                result = acceptance.assess({"fixtures": fixtures}, root / "absent", root, {})
                self.assertFalse(result["eligible_for_next_experiment"])
                self.assertTrue(result["errors"])
