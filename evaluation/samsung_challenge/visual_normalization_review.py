"""Offline controls for visible-text normalization; no OCR or provider calls."""
import argparse
from copy import deepcopy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys

from visual_evidence_review import MEDIA, TOOLS, decision, step


def probes():
    rows = []

    def add(name, value, expected_text, error=None, kind="boundary"):
        rows.append({"probe": name, "kind": kind, "input": value,
                     "expected_visible_text": expected_text, "expected_error": error})

    def printed(text, subject="AUX"):
        return decision(step(subject, phrase=subject), literal=text)

    add("literal_plus_blank_and_symbol", printed(["", "  ", "\u23fb", "AUX"]), ["AUX"])
    add("retained_strings_are_verbatim_and_ordered", printed(["  USB-C  ", "+", "0", "\u6e2f", "  USB-C  "], "USB-C"),
        ["  USB-C  ", "0", "\u6e2f", "  USB-C  "])
    for name, label in (("cjk", "\u6e2f"), ("devanagari", "\u092a\u094b\u0930\u094d\u091f"), ("arabic_digit", "\u0662")):
        add("non_latin_" + name, printed(["\u23fb", label], label), [label])
    for name, text in (("empty", []), ("all_noise", ["", " \t", "\u23fb", "+", "\u0301"])):
        value = decision(literal=text)
        value["clarification"] = "Please identify the control."
        add(name + "_clarification", value, [])
        add(name + "_cannot_supply_printed_subject", printed(text, "Power"), [],
            "image subject is not literal visible text")
    add("discarded_symbol_is_not_a_printed_subject", printed(["\u23fb"], "\u23fb"), [],
        "image subject is not literal visible text")
    add("retained_label_does_not_become_power", printed(["AUX", "\u23fb"], "Power"), ["AUX"],
        "image subject is not literal visible text")
    add("printed_subject_must_match_a_whole_entry", printed(["USB", "C", "+"], "USB C"), ["USB", "C"],
        "image subject is not literal visible text")
    for name, text in (("scalar", "AUX"), ("null", None), ("object", {"text": "AUX"}),
                       ("null_member", ["AUX", None]), ("number_member", ["AUX", 2]),
                       ("boolean_member", ["AUX", True]), ("nested_member", ["AUX", ["AUX"]])):
        value = printed(["AUX"])
        value["observations"][0]["visible_text"] = text
        reason = "expected list" if name in {"scalar", "null", "object"} else "non-string entry"
        add("malformed_" + name, value, text, "invalid literal image text: " + reason)
    value = printed(["AUX"])
    del value["observations"][0]["visible_text"]
    add("missing_visible_text", value, None, "invalid literal image text: expected list")
    value = printed(["AUX", "\u23fb"])
    value["tool_calls"][0]["authorization"] = {"quote": "AUX", "message_index": 7}
    add("printed_target_cannot_supply_write_authorization", value, ["AUX"],
        "conditional image target is read-only")
    value = printed(["AUX", "\u23fb"])
    value["tool_calls"][0]["api_name"] = "reset_control"
    add("printed_target_cannot_use_state_modifying_tool", value, ["AUX"],
        "conditional image target is read-only")
    value = printed(["AUX", "\u23fb"])
    value["tool_calls"][0]["result_evidence"]["path"] = "documents.1.title"
    add("citation_path_must_appear_in_template", value, ["AUX"],
        "image citation lacks named-record evidence")
    for basis in ("explicit_target", "non_visual"):
        value = decision(step("Power", basis=basis, phrase="Power"), literal=["\u23fb"])
        add("empty_text_accepts_self_reported_" + basis, value, [], kind="existing_self_report_limit")
    return rows


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--controller", type=Path, required=True)
    parser.add_argument("--planner-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Preserve earlier attempts; choose a fresh output path")
    root, controller_root = args.candidate.resolve(), args.controller.resolve()
    paths = sorted((root / "participant").glob("*.py")) + sorted((controller_root / "participant").glob("*.py"))
    before = {str(path): sha(path) for path in paths}
    if sha(root / "participant/planner.py") != args.planner_sha256:
        raise ValueError("Planner differs from the requested snapshot")
    sys.path.insert(0, str(root))
    planner = importlib.import_module("participant.planner")
    if Path(planner.__file__).resolve() != root / "participant/planner.py":
        raise ValueError("Wrong planner import")
    spec = importlib.util.spec_from_file_location("_normalization_controller", controller_root / "participant/__init__.py",
                                                submodule_search_locations=[str(controller_root / "participant")])
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    controller = importlib.import_module("_normalization_controller.agent")
    tools = {**TOOLS, "reset_control": {"kind": "state_modifying"}}
    results = []
    for row in probes():
        value, error = deepcopy(row["input"]), None
        try:
            planner.Planner._validate(value, deepcopy(MEDIA), deepcopy(tools))
        except Exception as exc:
            error = {"type": type(exc).__name__, "message": str(exc)}
        observed = value["observations"][0].get("visible_text")
        expected_error = None if row["expected_error"] is None else {"type": "ValueError", "message": row["expected_error"]}
        results.append({**row, "output": value, "error": error,
                        "expectation_met": error == expected_error and observed == row["expected_visible_text"]})
    source_results = []
    for name, subject, basis, actual, template, expected in (
        ("matching_printed_source", "AUX", "printed_text", "AUX input guide", "See {documents.0.title}.", True),
        ("mismatched_printed_source", "AUX", "printed_text", "Power button guide", "See {documents.0.title}.", False),
        ("non_string_source", "AUX", "printed_text", ["AUX"], "See {documents.0.title}.", False),
        ("uncited_actual_source", "AUX", "printed_text", "AUX input guide", "See a guide.", False),
        ("matching_explicit_source", "Power", "explicit_target", "Power button guide", "See {documents.0.title}.", True),
        ("mismatched_explicit_source", "Power", "explicit_target", "AUX input guide", "See {documents.0.title}.", False),
    ):
        operation = {"step": step(subject, basis=basis, phrase=subject), "result": {"documents": [{"title": actual}]}}
        accepted = controller.ParticipantAgent._source_matches(operation, template)
        source_results.append({"probe": name, "operation": operation, "template": template,
                               "expected_accept": expected, "accepted": accepted, "expectation_met": accepted == expected})
    unchanged = before == {str(path): sha(path) for path in paths}
    report = {"scope": "General robustness controls using actual validators and synthetic decisions/results. No actual image decoding, OCR, provider attempt, or new frozen case. Actual008 rejected value remains unknown.",
              "candidate": str(root), "planner_import": planner.__file__, "planner_sha256": args.planner_sha256,
              "controller_import": controller.__file__, "controller_sha256": sha(Path(controller.__file__)),
              "source_sha256": before, "sources_unchanged": unchanged,
              "probe_sha256": sha(Path(__file__)), "helper_sha256": sha(Path(__file__).with_name("visual_evidence_review.py")),
              "provider_calls": 0, "external_service_calls": 0, "image_decodes": 0,
              "media": MEDIA, "tools": tools,
              "validator_expectations_met": sum(row["expectation_met"] for row in results), "validator_total": len(results),
              "source_expectations_met": sum(row["expectation_met"] for row in source_results), "source_total": len(source_results),
              "results": results, "source_results": source_results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes((json.dumps(report, indent=2, ensure_ascii=True) + "\n").encode("utf-8"))
    print(json.dumps({key: report[key] for key in ("planner_sha256", "controller_sha256", "sources_unchanged", "validator_expectations_met", "validator_total", "source_expectations_met", "source_total", "provider_calls")}))
    for row in results + source_results:
        if not row["expectation_met"]:
            print(json.dumps(row))
    raise SystemExit(0 if unchanged and all(row["expectation_met"] for row in results + source_results) else 1)


if __name__ == "__main__":
    main()
