"""Small offline negative controls for complete denominator and timing diagnostics."""
import json
from pathlib import Path
import tempfile

from .gate import coverage, evidence_hashes_match, imports_match, sha, timing_diagnostics


def main():
    ids = [f"public{i}" for i in range(9)]
    rows = [{"attempt": i + 1, "scenario_id": sid} for i, sid in enumerate(s for s in ids for _ in range(3))]
    assert coverage(rows, ids)
    assert not coverage(rows[:-1], ids)
    assert not coverage(rows + [rows[-1]], ids)
    assert not coverage(rows[:-1] + [{"attempt": 27, "scenario_id": ids[0]}], ids)
    assert not coverage([{**r, "attempt": 1} for r in rows], ids)
    assert not coverage([], [])
    scenario = {"events": [{"timestamp_ms": 100}], "ground_truth": {"latency": {"respond_to": [{"event_index": 0}]}}}
    trace = [{"kind": "event", "event_type": "user_speech_chunk", "t_ms": 93},
             {"kind": "action", "action": "final_response", "t_ms": 93, "payload": {"text": "Actual answer"}}]
    diagnostic = timing_diagnostics(scenario, trace)[0]
    assert diagnostic["delivery_relative_ms"] == 0 and diagnostic["speech_before_nominal"]
    assert diagnostic["changes_official_or_strict_gate"] is False
    manifest = {"submission": "C:/candidate", "kit": "C:/candidate"}
    imports = {"participant.agent": "C:/candidate/participant/agent.py", "participant.planner": "C:/candidate/participant/planner.py"}
    assert imports_match({"imports": imports}, manifest)
    assert not imports_match({"imports": {**imports, "participant.agent": "C:/other/participant/agent.py"}}, manifest)
    assert not imports_match({"imports": {}}, manifest)
    with tempfile.TemporaryDirectory(prefix="acceptance-evidence-control-") as directory:
        root = Path(directory)
        for name in ("manifest.json", "official-report.json", "attempt-index.json", "console.log", "attempt-001-public.json"):
            (root / name).write_text("{}", encoding="utf-8")
        index = {p.name: sha(p) for p in root.iterdir()}
        index_path = root / "evidence-sha256.json"
        index_path.write_text(json.dumps(index), encoding="utf-8")
        attempts = [root / "attempt-001-public.json"]
        assert evidence_hashes_match(root, attempts)
        index_path.write_text(json.dumps({k: v for k, v in index.items() if k != "manifest.json"}), encoding="utf-8")
        assert not evidence_hashes_match(root, attempts)
        index_path.write_text(json.dumps({k: v for k, v in index.items() if k != attempts[0].name}), encoding="utf-8")
        assert not evidence_hashes_match(root, attempts)
        index_path.write_text(json.dumps(index), encoding="utf-8")
        (root / "official-report.json").write_text('{"changed":true}', encoding="utf-8")
        assert not evidence_hashes_match(root, attempts)
    print("15 offline gate controls passed; zero participant/provider executions")


if __name__ == "__main__":
    main()
