"""One numeric-labelled read whose declared API accepts no string arguments."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys

from .visual_evidence_review import MEDIA, decision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Preserve earlier attempts; choose a fresh report path")
    root = args.candidate.resolve()
    path = root / "participant/planner.py"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    sys.path.insert(0, str(root))
    module = importlib.import_module("participant.planner")
    if Path(module.__file__).resolve() != path:
        raise ValueError("Wrong participant import")
    tools = {"channel_reference": {"kind": "read_only", "description": "Return the manual entry for the numbered channel on the current device.",
                                  "args": {"channel": {"type": "integer", "required": True}}}}
    call = {"api_name": "channel_reference", "args": {"channel": 2},
            "response_template": "If you mean the labelled channel 2, see {manual.title}.",
            "result_evidence": {"path": "manual.title", "contains": "2", "target_basis": "printed_text"}}
    proposal = decision(call, literal=("2",))
    error = None
    try:
        module.Planner._validate(proposal, MEDIA, tools)
        accepted = True
    except Exception as exc:
        accepted = False
        error = {"type": type(exc).__name__, "message": str(exc)}
    report = {"scope": "One descriptor-valid numeric-labelled read, synthetic validator diagnostic; no actual model or tool execution.",
              "candidate": str(root), "import_path": module.__file__, "planner_sha256": before,
              "sources_unchanged": before == hashlib.sha256(path.read_bytes()).hexdigest(),
              "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "helper_sha256": hashlib.sha256(Path(__file__).with_name("visual_evidence_review.py").read_bytes()).hexdigest(),
              "provider_calls": 0, "external_service_calls": 0, "image_decodes": 0,
              "tools": tools, "media": MEDIA, "decision": proposal,
              "argument_contract_valid": set(call["args"]) == {"channel"} and type(call["args"]["channel"]) is int,
              "expected_accept": True, "accepted": accepted, "error": error}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes((json.dumps(report, indent=2) + "\n").encode("utf-8"))
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if accepted and report["sources_unchanged"] and report["argument_contract_valid"] else 1)


if __name__ == "__main__":
    main()
