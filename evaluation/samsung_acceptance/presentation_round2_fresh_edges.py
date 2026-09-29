"""Eight predeclared edge controls for candidate003; no provider/full-Agent run.

These are fresh inputs probing known repair areas, separate from the unchanged
24-control regression replay. Reuse the frozen first harness without modifying it.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import unicodedata


HELPER_SHA = "8e7c8da780a5e3f19725c7cb3a4f41b3f42cdbf3885c56f3e0dd7fc590694ca7"
AGENT_SHA = "640ba0263bfe7fa441e6a8184efb38e183944e764b3086ae2a6c667fe92c2eb8"
helper_path = Path(__file__).with_name("presentation_round2_review.py")
assert hashlib.sha256(helper_path.read_bytes()).hexdigest() == HELPER_SHA
spec = importlib.util.spec_from_file_location("frozen_presentation_helpers", helper_path)
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)
case, check = helpers.case, helpers.check
NOTE, OTHER, BASE = helpers.NOTE, helpers.OTHER, helpers.BASE
BRANCHES = {**BASE, "manufacturer_notes": {"washing": {"text": NOTE}, "electrical": {"text": OTHER}}}
LIST = {**BASE, "manufacturer_notes": [{"text": OTHER}, {"text": NOTE}]}

PRESENTATION_CASES = [
    case("uppercase_descendant_request_must_not_broaden", BRANCHES,
        "Show MANUFACTURER_NOTES.washing.", expect=check(NOTE, "quoted tool data", absent=[OTHER]),
        basis="The case-insensitive named-field matcher must not broaden a descendant request to its parent."),
    case("normalized_alias_descendant_must_not_broaden", BRANCHES,
        "Show manufacturerNotes.washing.", expect=check(NOTE, "quoted tool data", absent=[OTHER]),
        basis="A camel-case field alias accepted by label normalization must preserve the requested descendant boundary."),
    case("requested_later_object_list_item_is_presented", LIST,
        "Show manufacturer_notes.1.", expect=check(NOTE, absent=[OTHER]),
        basis="Fallback must present the expressly requested later list item without exposing its unrequested predecessor."),
    case("requested_later_object_list_item_template_control", LIST,
        "Show manufacturer_notes.1.", template="Requested note: {manufacturer_notes.1.text}.",
        expect=check(NOTE, "quoted tool data", absent=[OTHER]),
        basis="The exact same requested later list item also remains available to an exact scalar template."),
    case("single_message_explicit_supersession_control", helpers.WITH_NOTES,
        "Show manufacturer notes. Ignore my previous request. Only show the manual instructions.",
        expect=check(helpers.MANUAL, absent=[NOTE, "quoted tool data"]),
        basis="A realistic single completed message checks the earlier constructed-state supersession witness."),
    case("provided_condition_is_not_current_authority", helpers.WITH_NOTES,
        "Show manufacturer notes provided I approve first. For now, show the manual instructions.",
        expect=check(helpers.MANUAL, absent=[NOTE, "quoted tool data"]),
        basis="An express unsatisfied approval condition is not a present request to expose that field."),
]
UNICODE_CASES = [
    {"name": "greek_canonical_accent_equivalence", "requested": "Μονάδα",
     "actual": unicodedata.normalize("NFD", "Μονάδα") + " maintenance", "expected": True,
     "contract_basis": "Canonical decomposition of a Greek accented label remains equivalent."},
    {"name": "greek_distinct_accent_is_not_equivalent", "requested": "Μονάδα",
     "actual": "Μονὰδα maintenance", "expected": False,
     "contract_basis": "Distinct acute/grave marks are not silently stripped into the same source label."},
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-agent-sha256", default=AGENT_SHA)
    args = parser.parse_args()
    candidate, output = args.candidate.resolve(), args.out.resolve()
    if output.exists():
        parser.error("Refusing to overwrite preserved evidence: " + str(output))
    sha = helpers.sha
    agent_path = candidate / "participant" / "agent.py"
    if sha(agent_path) != args.expected_agent_sha256:
        parser.error("Candidate agent SHA-256 differs from the frozen requested source")
    manifest_path = candidate / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verified = {path: sha(candidate / path) for path in manifest["files"]}
    if verified != manifest["files"]:
        parser.error("Candidate files differ from their frozen manifest")
    sys.path.insert(0, str(candidate))
    module = importlib.import_module("participant.agent")
    if Path(module.__file__).resolve() != agent_path:
        parser.error("Agent import did not resolve to the frozen candidate")
    results = [dict(helpers.run_case(module.ParticipantAgent, fixture), control_kind="presentation_direct_render")
               for fixture in PRESENTATION_CASES]
    for fixture in UNICODE_CASES:
        template = "Reference: {sources.0.title}."
        operation = {"step": {"response_template": template, "result_evidence": {
            "path": "sources.0.title", "contains": fixture["requested"]}},
            "result": {"sources": [{"title": fixture["actual"]}]}}
        before = deepcopy(operation)
        actual = module.ParticipantAgent._source_matches(operation, template)
        results.append({"name": fixture["name"], "control_kind": "unicode_direct_source_comparator",
            "fixture": fixture, "actual": actual, "passed": actual == fixture["expected"] and operation == before,
            "operation_unchanged": operation == before})
    fixtures = {"presentation": PRESENTATION_CASES, "unicode": UNICODE_CASES}
    report = {"version": "presentation-round2-fresh-edges-v1", "created_utc": datetime.now(timezone.utc).isoformat(),
        "classification": "Fresh input edge controls on known repair areas, separate from original24 regression replay",
        "candidate_root": str(candidate), "agent_import_path": str(Path(module.__file__).resolve()),
        "agent_sha256": sha(agent_path), "candidate_manifest_sha256": sha(manifest_path),
        "candidate_manifest_verified_files": verified, "python_executable": sys.executable, "python_version": sys.version,
        "script": str(Path(__file__).resolve()), "script_sha256": sha(Path(__file__)),
        "frozen_helper_path": str(helper_path.resolve()), "frozen_helper_sha256": HELPER_SHA,
        "unicode_contract_sha256": sha(candidate.parent / "UNICODE.md"),
        "expectations_sha256": hashlib.sha256(json.dumps(fixtures, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        "provider_calls": 0, "full_agent_executions": 0,
        "limitations": ["Direct methods with constructed state; no planner, event-loop, timing, or integration evidence.",
            "All presentation controls use one completed message and therefore avoid the previous artificial two-turn fixture.",
            "Newly observed failures are not labeled introduced regressions without corresponding baseline execution.",
            "Expectations were frozen before execution. No original script or report was modified."],
        "summary": {"total": len(results), "passed": sum(row["passed"] for row in results),
                    "failed": sum(not row["passed"] for row in results)}, "results": results}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"report": str(output), "report_sha256": sha(output), **report["summary"],
                     "failed_cases": [row["name"] for row in results if not row["passed"]]}, indent=2))
    return 1 if report["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
