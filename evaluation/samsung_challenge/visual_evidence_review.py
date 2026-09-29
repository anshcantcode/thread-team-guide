"""Bounded offline review of literal image evidence and per-step target bases.

Calls the real planner validator only; no model, image decoder or provider is
invoked. Consistency of self-reports is not independent evidence of OCR truth.
"""
import argparse
import ast
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import sys


MEDIA = [{"message_index": 7, "mime_type": "image/png"}]
TOOLS = {"manual_lookup": {"kind": "read_only", "args": {"query": {"type": "string", "required": True}}}}


def step(query="Aurora Lamp", *, basis="printed_text", phrase="Aurora Lamp"):
    return {"api_name": "manual_lookup", "args": {"query": query},
            "response_template": "See {documents.0.title}.",
            "result_evidence": {"path": "documents.0.title", "contains": phrase, "target_basis": basis}}


def decision(*calls, literal=("Aurora Lamp",)):
    return {"intent": "lookup", "slots": {}, "tool_calls": list(calls), "response": None, "clarification": None,
            "observations": [{"message_index": 7, "type": "image", "observation": "The target is in the upper left.",
                              "visible_text": list(literal), "uncertain": False}]}


def probes():
    rows = []

    def add(name, value, accept, kind="behavior"):
        rows.append({"probe": name, "kind": kind, "expected_accept": accept, "decision": value})

    add("matching_literal_query_citation", decision(step()), True)
    add("explicit_unlabelled_spatial_target", decision(step("upper-left circular button", basis="explicit_target", phrase="circular button"), literal=()), True)
    add("mixed_visual_and_nonvisual_calls", decision(step(), step("battery disposal", basis="non_visual", phrase="battery disposal")), True)
    value = decision(step())
    del value["tool_calls"][0]["result_evidence"]["target_basis"]
    add("missing_target_basis", value, False)
    add("malformed_target_basis", decision(step(basis={"printed_text": True})), False)
    add("printed_phrase_missing_from_literal_entries", decision(step(phrase="Aurora")), False)
    # Revised contract: argument semantics are not inferred from arbitrary APIs.
    # A required literal string rejected valid numeric/ID-only/parameterless reads.
    add("query_disagrees_with_literal_and_citation", decision(step("Boreal Lamp")), True, "semantic_limit")
    add("matching_phrase_only_in_another_call", decision(step("Boreal Lamp"), step()), True, "semantic_limit")
    value = decision(step())
    value["tool_calls"][0]["result_evidence"]["path"] = "documents.1.title"
    add("citation_path_does_not_match_template", value, False)
    value = decision(step())
    value["observations"][0]["visible_text"] = "Aurora Lamp"
    add("visible_text_is_not_a_list", value, False)
    add("false_nonvisual_basis_can_bypass_literal_match", decision(step("Boreal Lamp", basis="non_visual", phrase="Boreal Lamp")), True, "self_report_limit")
    add("false_explicit_basis_can_bypass_literal_match", decision(step("Boreal Lamp", basis="explicit_target", phrase="Boreal Lamp")), True, "self_report_limit")
    add("internally_consistent_invented_transcription", decision(step("Invented Lamp", phrase="Invented Lamp"), literal=("Invented Lamp",)), True, "self_report_limit")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Preserve earlier attempts; choose a fresh output path")
    root = args.candidate.resolve()
    paths = sorted((root / "participant").glob("*.py"))
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    sys.path.insert(0, str(root))
    module = importlib.import_module("participant.planner")
    if not Path(module.__file__).resolve().is_relative_to(root):
        raise ValueError("Wrong participant import")
    results = []
    for row in probes():
        error = None
        try:
            module.Planner._validate(deepcopy(row["decision"]), deepcopy(MEDIA), deepcopy(TOOLS))
            accepted = True
        except Exception as exc:
            accepted = False
            error = {"type": type(exc).__name__, "message": str(exc)}
        results.append({**row, "accepted": accepted, "error": error,
                        "expectation_met": accepted == row["expected_accept"] and (accepted or error["type"] == "ValueError")})
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    baseline_path = args.baseline.resolve() / "participant/planner.py"
    spec = importlib.util.spec_from_file_location("participant._visual_review_baseline", baseline_path)
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    compatibility = {"text_schema_unchanged": module._schema() == baseline._schema(),
                     "audio_schema_unchanged": module._schema([{"message_index": 8, "mime_type": "audio/mpeg"}]) == baseline._schema([{"message_index": 8, "mime_type": "audio/mpeg"}]),
                     "common_and_audio_prompts_unchanged": all(getattr(module, key) == getattr(baseline, key) for key in ("SYSTEM", "AUDIO_GUIDANCE", "ACOUSTIC_SYSTEM"))}
    methods = []
    for path in (baseline_path, Path(module.__file__)):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Planner")
        methods.append({node.name: ast.dump(node, include_attributes=False) for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))})
    changed_methods = sorted(key for key in methods[0].keys() | methods[1].keys() if methods[0].get(key) != methods[1].get(key))
    compatibility["other_planner_methods_unchanged"] = set(changed_methods) <= {"_decide", "_validate"}
    # Exercise the unchanged controller's actual named-record guard separately.
    package_spec = importlib.util.spec_from_file_location("_visual_review_controller", baseline_path.parent / "__init__.py",
                                                        submodule_search_locations=[str(baseline_path.parent)])
    package = importlib.util.module_from_spec(package_spec)
    sys.modules[package_spec.name] = package
    package_spec.loader.exec_module(package)
    controller = importlib.import_module("_visual_review_controller.agent")
    source_checks = {}
    for title, expected in (("Aurora Lamp care guide", True), ("Boreal Lamp care guide", False)):
        operation = {"step": step(), "result": {"documents": [{"title": title}]}}
        source_checks[title] = controller.ParticipantAgent._source_matches(operation, operation["step"]["response_template"]) == expected
    report = {"scope": "Thirteen synthetic validator probes under the revised contract: eight behavior checks, two unvalidated argument-semantics limits and three self-report limits; not new frozen cases or model/OCR accuracy evidence.",
              "candidate": str(root), "import_path": module.__file__, "source_sha256": before, "sources_unchanged": before == after,
              "baseline_planner_sha256": hashlib.sha256(baseline_path.read_bytes()).hexdigest(), "compatibility": compatibility,
              "changed_planner_methods": changed_methods, "tools": TOOLS,
              "source_relevance": {"controller_sha256": hashlib.sha256(Path(controller.__file__).read_bytes()).hexdigest(),
                                   "controller_import_path": controller.__file__, "checks": source_checks},
              "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "provider_calls": 0,
              "external_service_calls": 0, "image_decodes": 0, "media": MEDIA,
              "expectations_met": sum(row["expectation_met"] for row in results), "total": len(results), "results": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes((json.dumps(report, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=2))
    for row in results:
        print(json.dumps({key: value for key, value in row.items() if key != "decision"}))
    raise SystemExit(0 if before == after and all(compatibility.values()) and all(source_checks.values()) and all(row["expectation_met"] for row in results) else 1)


if __name__ == "__main__":
    main()
