"""Three root-requested referential-destination controls, separate from the 37."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys

from .text_fastpath_review import context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--controller", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Preserve earlier attempts; choose a fresh report path")
    root = args.candidate.resolve()
    source = root / "participant/planner.py"
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    sys.path.insert(0, str(root))
    package = importlib.import_module("participant")
    package.__path__.append(str(args.controller.resolve() / "participant"))
    module = importlib.import_module("participant.planner")
    assert Path(module.__file__).resolve() == source
    results = []
    for destination in ("work", "school", "nearby"):
        words = "Search flights to " + destination
        proposal = module._simple_flight_search(context(words))
        results.append({"text": words, "expected": "defer", "passed": proposal is None, "decision": proposal})
    report = {"scope": "Three separately requested root counterexamples; original 37 grammar controls are unchanged.",
              "planner_sha256": before, "sources_unchanged": before == hashlib.sha256(source.read_bytes()).hexdigest(),
              "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "context_helper_sha256": hashlib.sha256(Path(__file__).with_name("text_fastpath_review.py").read_bytes()).hexdigest(),
              "provider_calls": 0, "external_service_calls": 0, "passed": sum(row["passed"] for row in results),
              "total": len(results), "results": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes((json.dumps(report, indent=2) + "\n").encode("utf-8"))
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["sources_unchanged"] and report["passed"] == report["total"] else 1)


if __name__ == "__main__":
    main()
