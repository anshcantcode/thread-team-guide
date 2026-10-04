"""Per-case failure dossier for a finished scripts/fdb3_run.py campaign. Evaluator-side analysis only.

For every recording it lays out, on one timeline: what THREAD heard, what the planner proposed (its raw
decision), what the controller admitted, blocked or asked, which tools were dispatched, what THREAD said,
and how the evaluator judged it. Failures get a layer label (ASR, planner, controller gate/validation,
judge strictness, timing window, infrastructure) so they can be fixed before the next GPU run.

It reads the run's own evidence and, for post-hoc analysis only, the released evaluator metadata (reference
dialogue and expected calls). Nothing in THREAD's runtime imports this file, and nothing here feeds back
into the agent: fixes must stay general mechanisms, never per-recording rules.

usage: python scripts/fdb3_case_dossier.py RUN_DIR [--assets DIR] [--baseline RUN_DIR] [--out DIR]
Writes OUT/SUMMARY.md, OUT/case-NNN.md for every recording and OUT/dossier.json (default OUT: RUN_DIR.dossier).
"""
import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import re
import sys

ARTICLES = {"the", "a", "an"}
NUMBER_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30,
                "fifty": 50, "hundred": 100, "thousand": 1000}
LAYER_HELP = {
    "INFRA": "run did not complete this recording",
    "GATE_BLOCKED": "planner proposed the expected call; the write/authorization gate refused it",
    "VALIDATION_BLOCKED": "planner proposed the call; schema validation turned it into a question",
    "PROPOSED_NOT_DISPATCHED": "planner proposed the call but it was superseded, cancelled or never admitted",
    "PREMATURE_PLAN": "planning ran before the user finished (correction still arriving)",
    "PLANNER_ASKED": "planner chose to ask a question instead of acting",
    "PLANNER_MISSED_CALL": "the heard text had what was needed, but the planner never proposed this call",
    "ASR_MISSING_VALUE": "a value the call needs is in the reference dialogue but not in what THREAD heard",
    "ASR_VALUE": "an argument is wrong because THREAD misheard it",
    "ARG_NOT_IN_CONTRACT": "expected argument is not declared in the public tool contract",
    "ARG_OMITTED": "a declared argument the user stated was left out",
    "PLANNER_WRONG_VALUE": "argument value differs and the heard text had the right value",
    "JUDGE_STRICT": "argument differs only in form (case, article, number/boolean as text); a lenient judge may pass it",
    "EXTRA_CALL": "an unexpected call was dispatched",
    "WINDOW_LATE": "a call landed after the upstream capture window",
    "UNCLASSIFIED": "no rule matched; read the timeline",
}


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def literal(value):
    """Metadata fields are sometimes Python-literal strings."""
    if isinstance(value, str):
        for parse in (json.loads, ast.literal_eval):
            try:
                return parse(value)
            except (ValueError, SyntaxError, TypeError):
                pass
    return value


def norm_text(text):
    text = str(text).lower().replace(",", "")
    text = re.sub(r"[^a-z0-9.$ ]+", " ", text)
    return " ".join(text.split())


def norm_value(value):
    """Canonical form for 'same value, different spelling' comparisons."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return f"{float(value):g}"
    text = norm_text(value).strip(" .$")
    if text in {"true", "yes"}:
        return "true"
    if text in {"false", "no"}:
        return "false"
    try:
        return f"{float(text):g}"
    except ValueError:
        pass
    words = [w for w in text.split() if w not in ARTICLES]
    return " ".join(words)


def value_tokens(value):
    """Tokens that should appear in speech if the user said this value."""
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float)):
        number = f"{float(value):g}"
        return [number]
    words = [w for w in norm_text(value).split() if w not in ARTICLES and len(w) > 1]
    return words[:4]


def mentioned(value, text):
    tokens = value_tokens(value)
    if not tokens:
        return None
    haystack = norm_text(text)
    for word, number in NUMBER_WORDS.items():
        haystack = re.sub(rf"\b{word}\b", str(number), haystack)
    return all(re.search(rf"\b{re.escape(t)}\b", haystack) or t in haystack.replace(" ", "") for t in tokens)


def contract_args(run):
    """{tool: {arg: spec}} from the run's own snapshot, if importable."""
    try:
        sys.path.insert(0, str(run / "source"))
        from thread_agent.fdb3 import load_contract  # noqa: E402
        tools = load_contract(run / "contract")
        return {name: (tool.get("args") or {}) for name, tool in tools.items()}
    except Exception:  # analysis aid only
        return {}
    finally:
        if sys.path and sys.path[0] == str(run / "source"):
            sys.path.pop(0)


def planner_rounds(result, origin):
    rounds = []
    for request in result.get("model_requests") or []:
        content = request.get("content")
        decision = None
        if isinstance(content, str):
            try:
                decision = json.loads(content)
            except ValueError:
                decision = None
        calls = [(c.get("api_name"), c.get("args")) for c in (decision or {}).get("tool_calls") or []
                 if isinstance(c, dict)]
        rounds.append({"at": rel(request.get("started_at"), origin), "seconds": dur(request), "outcome": request.get("outcome"),
                       "finish_reason": request.get("finish_reason"), "truncated": request.get("truncated"),
                       "prompt_characters": request.get("prompt_characters"), "content": content, "calls": calls,
                       "decision": decision})
    return rounds


def rel(value, origin):
    return round(value - origin, 2) if isinstance(value, (int, float)) and isinstance(origin, (int, float)) else None


def dur(request):
    start, end = request.get("started_at"), request.get("finished_at")
    return round(end - start, 2) if isinstance(start, (int, float)) and isinstance(end, (int, float)) else None


def classify(case, result, evaluation, metadata, rounds, contract):
    """Ordered findings for one recording: [(layer, detail)]."""
    findings = []
    if case.get("status") != "completed":
        return [("INFRA", case.get("error") or case.get("failure_reason") or "not completed")]
    if case.get("strict_pass") is True:
        if case.get("window_strict_pass") is False:
            findings.append(("WINDOW_LATE", json.dumps(case.get("upstream_window"))))
        return findings
    heard = " ".join(t.get("text", "") for t in result.get("input_transcripts") or [])
    reference = " ".join(turn.get("user", "") for turn in literal(metadata.get("dialogue")) or [] if isinstance(turn, dict))
    events = result.get("controller_events") or []
    clarifications = [e.get("payload") or {} for e in events if e.get("action") == "clarification_request"]
    expected = literal(metadata.get("expected_tool_calls")) or []
    actual = [(c.get("function"), c.get("args") or {}) for c in result.get("actual_tool_calls") or []]
    remaining = list(actual)
    checks = (evaluation.get("strict") or {}).get("checks") or {}
    arg_details = {d.get("function"): d for d in (checks.get("argument_accuracy") or {}).get("details") or []
                   if d.get("passed") is False}
    proposed = [call for r in rounds for call in r["calls"]]
    for call in expected:
        name, want = call.get("function"), call.get("args") or {}
        match = next((c for c in remaining if c[0] == name), None)
        if match is None:
            if any(p[0] == name for p in proposed):
                gate = next((c for c in clarifications if c.get("gate")), None)
                validation = next((c for c in clarifications if c.get("validation")), None)
                if gate:
                    reasons = (gate.get("gate") or {}).get("reasons") or []
                    layer = "PREMATURE_PLAN" if any("correction" in str(r) for r in reasons) else "GATE_BLOCKED"
                    findings.append((layer, f"{name}: {reasons} | said: {gate.get('text')}"))
                elif validation:
                    findings.append(("VALIDATION_BLOCKED", f"{name}: {(validation.get('validation') or {}).get('problems')}"
                                     f" | said: {validation.get('text')}"))
                else:
                    findings.append(("PROPOSED_NOT_DISPATCHED", f"{name} proposed as {[p for p in proposed if p[0] == name][:2]}"))
                continue
            missing_heard = [k for k, v in want.items() if mentioned(v, heard) is False and mentioned(v, reference)]
            if missing_heard:
                findings.append(("ASR_MISSING_VALUE", f"{name}: {', '.join(f'{k}={want[k]!r}' for k in missing_heard)} "
                                 "not in heard text"))
            elif clarifications:
                findings.append(("PLANNER_ASKED", f"{name}: asked {clarifications[0].get('text')!r}"))
            else:
                findings.append(("PLANNER_MISSED_CALL", f"{name}{json.dumps(want)} never proposed"))
            continue
        remaining.remove(match)
        if name not in arg_details:
            continue
        got = match[1]
        declared = contract.get(name) or {}
        for key in sorted(set(want) | set(got)):
            if key in want and key in got and norm_value(want[key]) == norm_value(got[key]):
                if want[key] != got[key]:
                    findings.append(("JUDGE_STRICT", f"{name}.{key}: expected {want[key]!r}, sent {got[key]!r}"))
                continue
            if key in want and key not in got:
                layer = "ARG_NOT_IN_CONTRACT" if declared and key not in declared else "ARG_OMITTED"
                findings.append((layer, f"{name}.{key}: expected {want[key]!r}, not sent"))
            elif key in want:
                layer = ("ASR_VALUE" if mentioned(want[key], heard) is False and mentioned(want[key], reference)
                         else "PLANNER_WRONG_VALUE")
                findings.append((layer, f"{name}.{key}: expected {want[key]!r}, sent {got[key]!r}"))
    for extra in remaining:
        findings.append(("EXTRA_CALL", f"{extra[0]}{json.dumps(extra[1])}"))
    if not findings:
        findings.append(("UNCLASSIFIED", case.get("failure_reason") or ""))
    return findings


def case_markdown(index, case, result, evaluation, metadata, rounds, findings):
    origin = result.get("stream_start_time")
    lines = [f"# case-{index:03d} {case['recording']}",
             f"**{'PASS' if case.get('strict_pass') else 'FAIL'}** (window {case.get('window_strict_pass')}) | "
             f"{metadata.get('domain')} | {metadata.get('difficulty')} | {metadata.get('title')} | "
             f"disfluency: {literal(metadata.get('disfluency_features'))}",
             f"Failure: {case.get('failure_reason') or '-'}", ""]
    if findings:
        lines += ["## Diagnosis"] + [f"- **{layer}**: {detail}" for layer, detail in findings] + [""]
    lines += ["## Reference dialogue (evaluator data; analysis only)"]
    for turn in literal(metadata.get("dialogue")) or []:
        if isinstance(turn, dict):
            lines += [f"> {k}: {v}" for k, v in turn.items()]
    lines += ["", "## Timeline (seconds from stream start)"]
    timeline = []
    for t in result.get("input_transcripts") or []:
        timeline.append((rel(t.get("started_at"), origin), f"HEARD  {t.get('text')!r} (until {rel(t.get('finished_at'), origin)})"))
    for r in rounds:
        timeline.append((r["at"], f"PLAN   {r['outcome']} in {r['seconds']}s finish={r['finish_reason']} "
                                  f"truncated={r['truncated']} chars={r['prompt_characters']}\n         {str(r['content'])[:900]}"))
    for call in result.get("actual_tool_calls") or []:
        timeline.append((rel(call.get("timestamp_start"), origin),
                         f"CALL   {call.get('function')}{json.dumps(call.get('args'))} -> {call.get('outcome')}"))
    for t in result.get("tts_requests") or []:
        timeline.append((rel(t.get("started_at"), origin), f"SAY    {t.get('text')!r}"))
    timeline.sort(key=lambda item: (item[0] is None, item[0] or 0))
    lines += [f"- `{at:>7}` {text}" for at, text in timeline]
    lines += ["", "## Controller events"]
    for e in result.get("controller_events") or []:
        payload = e.get("payload") or {}
        lines.append(f"- {e.get('action')}: {json.dumps(payload)[:400]}")
    lines += ["", "## Expected vs dispatched"]
    lines.append(f"- expected: `{json.dumps(literal(metadata.get('expected_tool_calls')))}`")
    lines.append(f"- dispatched: `{json.dumps([(c.get('function'), c.get('args')) for c in result.get('actual_tool_calls') or []])}`")
    lines += ["", "## Evaluator"]
    strict = evaluation.get("strict") or {}
    for name, check in (strict.get("checks") or {}).items():
        lines.append(f"- {name}: passed={check.get('passed')}")
        for detail in check.get("details") or []:
            lines.append(f"  - {detail.get('function')}: {detail.get('explanation')}")
    quality = evaluation.get("quality") or {}
    lines.append(f"- output transcript judged: {result.get('transcript')!r}")
    lines.append(f"- quality: {json.dumps({k: v for k, v in quality.items() if k not in ('metrics',)})[:600]}")
    if case.get("upstream_window"):
        lines.append(f"- upstream window: {json.dumps(case['upstream_window'])}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run", type=Path)
    parser.add_argument("--assets", type=Path)
    parser.add_argument("--baseline", type=Path, help="earlier run to diff pass/fail against")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    run = args.run.resolve()
    assets = args.assets or Path(json.loads((run / "identity.json").read_text(encoding="utf-8"))["config"]["assets"])
    if not assets.is_absolute():
        assets = (Path(__file__).resolve().parents[1] / assets).resolve()
    out = args.out or run.with_name(run.name + ".dossier")
    out.mkdir(parents=True, exist_ok=True)
    report = load_json(run / "report.json")
    manifest = {r["recording"]: r for r in load_json(run / "dataset-manifest.json")["recordings"]}
    baseline = {c["recording"]: c for c in (load_json(args.baseline / "report.json") or {}).get("cases", [])} if args.baseline else {}
    contract = contract_args(run)
    rows, layers, domains = [], Counter(), Counter()
    for position, case in enumerate(report["cases"]):
        index = case.get("case_index", position)  # screening runs keep the original recording numbers
        case_root = run / f"case-{index:03d}"
        result = load_json(case_root / "inference/result.json", {}) or {}
        evaluation = load_json(case_root / "evaluation.json", {}) or {}
        metadata = load_json((assets / "evaluator-data" / manifest[case["recording"]]["relative_path"]).parent
                             / "metadata.json", {}) or {}
        rounds = planner_rounds(result, result.get("stream_start_time"))
        findings = classify(case, result, evaluation, metadata, rounds, contract)
        (out / f"case-{index:03d}.md").write_text(
            case_markdown(index, case, result, evaluation, metadata, rounds, findings), encoding="utf-8", newline="\n")
        domain = case["recording"].split("_")[0]
        domains[(domain, bool(case.get("strict_pass")))] += 1
        if not case.get("strict_pass"):
            layers[findings[0][0]] += 1
        before = baseline.get(case["recording"], {}).get("strict_pass")
        rows.append({"index": index, "recording": case["recording"], "domain": domain,
                     "difficulty": metadata.get("difficulty"), "strict_pass": case.get("strict_pass"),
                     "window_strict_pass": case.get("window_strict_pass"), "failure_reason": case.get("failure_reason"),
                     "findings": findings, "baseline_strict_pass": before})
    strict = sum(bool(r["strict_pass"]) for r in rows)
    scope = "" if len(rows) == 100 else f" (screening subset of {len(rows)} recordings; not a 100-recording score)"
    lines = [f"# Dossier for {run.name}{scope}", "",
             f"Strict {strict}/{len(rows)}, window {sum(r['window_strict_pass'] is True for r in rows)}, "
             f"infrastructure errors {sum(c.get('status') != 'completed' for c in report['cases'])}. "
             f"Source {load_json(run / 'identity.json', {}).get('commit')}. Judge: {report.get('judge')}.", "",
             "| domain | pass |", "|---|---|"]
    for domain in sorted({d for d, _ in domains}):
        lines.append(f"| {domain} | {domains[(domain, True)]}/{domains[(domain, True)] + domains[(domain, False)]} |")
    lines += ["", "## Failures by primary layer", "", "| layer | count | meaning |", "|---|---|---|"]
    for layer, count in layers.most_common():
        lines.append(f"| {layer} | {count} | {LAYER_HELP.get(layer, '')} |")
    if baseline:
        gained = [r for r in rows if r["strict_pass"] and r["baseline_strict_pass"] is False]
        lost = [r for r in rows if not r["strict_pass"] and r["baseline_strict_pass"] is True]
        lines += ["", f"## Versus baseline {args.baseline.name}: gained {len(gained)}, lost {len(lost)}",
                  "gained: " + ", ".join(f"{r['index']:03d}" for r in gained),
                  "lost: " + ", ".join(f"{r['index']:03d}" for r in lost)]
    lines += ["", "## Every failure", "", "| case | recording | diff. | layer | detail |", "|---|---|---|---|---|"]
    for r in rows:
        if r["strict_pass"]:
            continue
        layer, detail = r["findings"][0]
        more = f" (+{len(r['findings']) - 1} more)" if len(r["findings"]) > 1 else ""
        detail = detail.replace("|", "/")[:160]
        lines.append(f"| [{r['index']:03d}](case-{r['index']:03d}.md) | {r['recording']} | {r['difficulty']} | "
                     f"{layer} | {detail}{more} |")
    (out / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    (out / "dossier.json").write_text(json.dumps({"run": str(run), "rows": rows}, indent=1, default=str),
                                      encoding="utf-8", newline="\n")
    print(f"{out / 'SUMMARY.md'}: strict {strict}/{len(rows)}; layers {dict(layers.most_common())}")


if __name__ == "__main__":
    main()
