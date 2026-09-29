"""Freeze a description-only appointment contract revision; no participant execution.

Run with python -B -m evaluation.samsung_acceptance.appointment_contract.
Existing source fixtures and output directories are never overwritten.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


VERSION = "2026-09-21.appointment-date-v1"
SLOT_DESCRIPTION = (
    "Calendar date of the appointment, in YYYY-MM-DD format, as supplied by the user. "
    "The specialist's morning/afternoon window is a selection criterion and is not part of this value."
)
CHALLENGE = Path(__file__).resolve().parents[1] / "samsung_challenge"
DEFAULT_OUT = Path(__file__).with_name("contracts") / "appointment-date-v1"
FAMILIES = ("semantic_novel_schema", "semantic_quoted_write", "semantic_multicorrection",
            "semantic_authorized_chain", "semantic_result_injection")
EXPECTED_IDS = {f"{family}.t{schedule}.p2" for family in FAMILIES for schedule in range(4)}


def identity(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def revised_case(case):
    revised = deepcopy(case)
    slot = revised["tools"]["schedule_visit"]["args"]["appointment"]["properties"]["slot"]
    if slot != {"required": True, "type": "string"}:
        raise ValueError(f"Unexpected original slot descriptor: {case['id']}")
    slot["description"] = SLOT_DESCRIPTION
    return revised


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-cases", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("--out already exists; immutable revisions must be preserved")
    source = identity(args.source_cases)
    parent = identity(args.source_cases.parent / "FREEZE.json")
    parent_manifest = json.loads(Path(parent["path"]).read_text(encoding="utf-8"))
    if parent_manifest["files"][args.source_cases.name]["sha256"] != source["sha256"]:
        raise ValueError("Source cases do not match their parent freeze")
    rows, metadata = [], []
    for line_number, raw in enumerate(args.source_cases.read_bytes().splitlines(), 1):
        case = json.loads(raw)
        if "schedule_visit" not in case["tools"]:
            continue
        if case["partition"] != "development" or case["version"] != "2026-09-21.semantic-v2":
            raise ValueError(f"Unexpected source contract: {case['id']}")
        revised = revised_case(case)
        encoded = json.dumps(revised, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
        rows.append(encoded + b"\n")
        metadata.append({"id": case["id"], "source_line": line_number,
                         "source_line_sha256_without_newline": hashlib.sha256(raw).hexdigest(),
                         "revised_line_sha256_without_newline": hashlib.sha256(encoded).hexdigest()})
    if len(rows) != 20 or {row["id"] for row in metadata} != EXPECTED_IDS:
        raise ValueError("Expected exactly the twenty affected development rows")
    if identity(args.source_cases) != source or identity(Path(parent["path"])) != parent:
        raise ValueError("Source changed during freeze")
    cases = b"".join(rows)
    manifest = {
        "version": VERSION, "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_cases": source, "parent_freeze": parent,
        "prior_outputs_seen": True, "provider_outputs_for_this_revision_before_freeze": False,
        "zero_new_independent_cases": True, "new_independent_cases": 0,
        "development_rows": 20, "holdout_rows_affected": 0,
        "revision_metadata_outside_cases": True,
        "only_case_change": "tools.schedule_visit.args.appointment.properties.slot.description",
        "description": SLOT_DESCRIPTION,
        "unchanged": ["case IDs and versions", "user events", "oracle rules", "reply arguments and data",
                      "timing and tail", "all other tool descriptor fields"],
        "source_files": {"appointment_contract.py": identity(__file__),
                         "semantic_oracle_v2.py": identity(CHALLENGE / "semantic_oracle_v2.py"),
                         "oracle.py": identity(CHALLENGE / "oracle.py")},
        "source_lines": metadata,
        "files": {"cases.jsonl": {"sha256": hashlib.sha256(cases).hexdigest(),
                                   "bytes": len(cases), "rows": len(rows)}},
    }
    args.out.mkdir(parents=True, exist_ok=False)
    with (args.out / "cases.jsonl").open("xb") as stream:
        stream.write(cases)
    with (args.out / "FREEZE.json").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"version": VERSION, "rows": len(rows),
                      "cases": identity(args.out / "cases.jsonl"),
                      "freeze": identity(args.out / "FREEZE.json")}, indent=2))


if __name__ == "__main__":
    main()
