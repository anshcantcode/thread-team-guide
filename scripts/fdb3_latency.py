"""Local latency diagnostic using unchanged upstream compute_latencies.

Input ASR stays evaluator-side. Epoch clocks are required, never reconstructed
from process start or the first detected signal. Output alignment uses capture
arrival time and therefore includes RTC scheduling/jitter; this is not an
organizer latency result. A local ASR/model is never labeled an official judge.
"""
import argparse
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.fdb3_evaluate import load
from thread_agent.fdb3_evidence import file_hash
from thread_agent.fdb3_judge_transport import NativeJudgeTransport


LATENCY_SCHEMA = {
    "type": "object", "properties": {
        "filler_sentence": {"type": "string"},
        "filler_start_time": {"type": ["number", "null"]},
        "filler_end_time": {"type": ["number", "null"]},
        "key_info_sentence": {"type": "string"},
        "key_info_start_time": {"type": ["number", "null"]},
        "key_info_end_time": {"type": ["number", "null"]}},
    "required": ["filler_sentence", "filler_start_time", "filler_end_time",
                 "key_info_sentence", "key_info_start_time", "key_info_end_time"],
    "additionalProperties": False}


def checkpoint_json(path, value):
    """Replace a durable snapshot; a killed child leaves the preceding snapshot."""
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def number(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"Missing/nonfinite numeric {name}")
    return value


def checked_chunks(chunks, name, *, required=False):
    if not isinstance(chunks, list) or required and not chunks:
        raise ValueError(f"Missing {name} chunks")
    previous = -math.inf
    for chunk in chunks:
        if not isinstance(chunk, dict) or not isinstance(chunk.get("text"), str):
            raise ValueError(f"Malformed {name} chunk")
        stamp = chunk.get("timestamp")
        if not isinstance(stamp, (list, tuple)) or len(stamp) != 2:
            raise ValueError(f"Missing {name} chunk timestamps")
        start, end = (number(t, name + " timestamp") for t in stamp)
        if start < 0 or end < start or start < previous:
            raise ValueError(f"Invalid/unsorted {name} timestamps")
        previous = start
    return chunks


def first_turn_end(chunks):
    """Pinned run_tool_benchmark.py convention: first gap strictly greater than 2s."""
    checked_chunks(chunks, "input ASR", required=True)
    for current, following in zip(chunks, chunks[1:]):
        if following["timestamp"][0] - current["timestamp"][1] > 2.0:
            return current["timestamp"][1]
    return chunks[-1]["timestamp"][1]


def clock_origins(result):
    origin = number(result.get("stream_start_time"), "stream_start_time")
    capture = number(result.get("output_audio_start_time"), "output_audio_start_time")
    if origin <= 0 or capture <= 0:
        raise ValueError("Positive epoch-second stream/capture clocks required")
    return origin, capture


def align_result(result, input_asr):
    if result.get("status") != "completed" or input_asr.get("status") != "completed":
        raise ValueError("Completed inference and evaluator-side input ASR required")
    if not result.get("input_sha256") or input_asr.get("input_sha256") != result["input_sha256"]:
        raise ValueError("Input ASR is not bound to the inference input")
    origin, capture = clock_origins(result)
    aligned = deepcopy(result)
    aligned["user_speech_end_rel"] = first_turn_end(input_asr.get("chunks"))
    chunks = checked_chunks(aligned.get("asr_chunks"), "output ASR")
    for chunk in chunks:
        chunk["timestamp"] = [t + capture - origin for t in chunk["timestamp"]]
    calls = aligned.get("actual_tool_calls")
    if not isinstance(calls, list):
        raise ValueError("Missing actual tool trace")
    previous = -math.inf
    for call in calls:
        if not isinstance(call, dict):
            raise ValueError("Malformed tool trace")
        start = number(call.get("timestamp_start"), "tool timestamp_start")
        if start <= 0 or start < previous:
            raise ValueError("Tool timestamps must be sorted positive epoch seconds")
        previous = start
        end = call.get("timestamp_end")
        if end is not None and number(end, "tool timestamp_end") < start:
            raise ValueError("Tool timestamp_end precedes invocation")
        # Preserve upstream runner's two-decimal normalization of epoch tool clocks.
        for field in ("timestamp_start", "timestamp_end", "timestamp"):
            if call.get(field) is not None:
                call[field] = round(number(call[field], field) - origin, 2)
    return aligned


def validate_judgment(value, chunks):
    if not isinstance(value, dict) or set(value) != set(LATENCY_SCHEMA["required"]):
        raise ValueError("Malformed latency judgment fields")
    for prefix in ("filler", "key_info"):
        sentence = value[prefix + "_sentence"]
        start, end = value[prefix + "_start_time"], value[prefix + "_end_time"]
        if not isinstance(sentence, str):
            raise ValueError("Malformed latency judgment text")
        if start is None and end is None and not sentence.strip():
            continue
        start, end = number(start, prefix + " start"), number(end, prefix + " end")
        if (not sentence.strip() or end < start
                or not any(math.isclose(start, c["timestamp"][0], abs_tol=1e-5, rel_tol=0) for c in chunks)
                or end > max(c["timestamp"][1] for c in chunks) + 1e-5):
            raise ValueError("Latency judgment is not grounded in aligned ASR timestamps")


def evaluate_latency(upstream, result, input_asr, judge_endpoint=None, judge_identity=None,
                     *, output_asr_identity=None, record_callback=None):
    report = {"status": "infrastructure_error", "mode": "upstream_latency_local_diagnostic",
              "qualification_eligible": False, "paid_requests": 0,
              "judge_enabled": bool(judge_endpoint), "judge_identity": judge_identity,
              "judge_note": "Local declared model, not OpenAI GPT-4o or Samsung's judge.",
              "input_asr_identity": input_asr.get("model_identity"),
              "output_asr_identity": output_asr_identity or result.get("output_asr_identity"),
              "input_asr_evidence": deepcopy(input_asr),
              "judge_requests": [], "native_judge_calls": [], "metrics": None,
              "timing": {"clock": "epoch seconds from one host",
                         "input_origin": "stream_start_time before first input capture",
                         "output_origin": "output_audio_start_time at first received PCM frame",
                         "alignment": "capture arrival; includes RTC scheduling/jitter",
                         "first_turn_rule": "first input ASR gap > 2 seconds; else final chunk end",
                         "tool_rounding_seconds": 0.01, "official_latency": False}}
    client = None
    def checkpoint():
        if record_callback is not None:
            record_callback(report)
    try:
        checkpoint()
        if not report["input_asr_identity"] or not report["output_asr_identity"]:
            raise ValueError("Explicit local input/output ASR identities required")
        aligned = align_result(result, input_asr)
        report["aligned_result"] = aligned
        report["timing"].update(stream_start_time=result["stream_start_time"],
                                output_audio_start_time=result["output_audio_start_time"])
        upstream = Path(upstream)
        report["evaluator_sha256"] = file_hash(upstream / "analyze_tool_latency.py")
        module = load("analyze_tool_latency", upstream)
        if judge_endpoint:
            if not judge_identity:
                raise ValueError("Actual local judge model identity required")
            import httpx
            from openai import OpenAI
            def checked(response):
                entry = {"status_code": response.status_code, "valid": False}
                report["judge_requests"].append(entry)
                try:
                    response.read()
                    body = response.json()
                    content = body["choices"][0]["message"]["content"]
                    entry.update(content=content, usage=body.get("usage"), returned_model=body.get("model"))
                    validate_judgment(json.loads(content), aligned["asr_chunks"])
                    entry["valid"] = True
                finally:
                    checkpoint()
            client = OpenAI(base_url=judge_endpoint, api_key="local-unbilled", max_retries=0,
                http_client=httpx.Client(timeout=90, trust_env=False, event_hooks={"response": [checked]},
                    transport=NativeJudgeTransport(judge_endpoint, report["native_judge_calls"],
                        json_schema=LATENCY_SCHEMA, record_callback=lambda calls: checkpoint())))
        report["metrics"] = module.compute_latencies(aligned, client=client)
        requests, native = report["judge_requests"], report["native_judge_calls"]
        if client and aligned["asr_chunks"] and (len(requests) != 1 or len(native) != 1
                or any(not r["valid"] or r["status_code"] != 200 for r in requests)
                or any(c.get("outcome") != "success" or c.get("inference_requests") != 1 for c in native)
                or "note_task_completion" in report["metrics"] and
                    report["metrics"]["note_task_completion"].startswith("LLM error:")):
            raise ValueError("Latency judge failed; upstream error handling cannot count as complete evidence")
        complete = bool(client and report["metrics"] and all(report["metrics"].get(name) is not None
                        for name in ("first_response_latency_s", "tool_call_latency_s", "task_completion_latency_s")))
        report["status"] = "complete_diagnostic" if complete else "partial_diagnostic"
        if not complete:
            report["incomplete_reason"] = "At least one latency metric is unmeasured; available metrics remain diagnostic only"
    except Exception as exc:
        report.update(infrastructure_error=str(exc), error_type=type(exc).__name__)
    finally:
        if client is not None:
            client.close()
        checkpoint()
    return report


def transcribe_input(audio, model_path, *, record_callback=None):
    """Explicit local ASR invocation, evaluator-side after inference has exited."""
    started, cpu = time.time(), time.process_time()
    record = {"status": "infrastructure_error", "model_identity": {"implementation": "local faster-whisper",
              "model_path": str(model_path), "vad_filter": True, "official_asr": False},
              "timestamp_basis": "input audio seconds", "requests": [], "chunks": [], "paid_requests": 0}
    def checkpoint():
        record.update(started_at=started, cpu_seconds=time.process_time() - cpu,
                      request_count=len(record['requests']))
        if record_callback is not None:
            record_callback(record)
    try:
        checkpoint()
        record["input_sha256"] = file_hash(audio)
        record["model_identity"]["asset_hashes"] = {
            str(p.relative_to(model_path)): file_hash(p) for p in Path(model_path).rglob("*") if p.is_file()}
        from thread_agent.fdb3_voice import WhisperSTT
        recognizer = WhisperSTT(model_path)
        request = {"started_at": time.time(), "outcome": "pending"}
        record["requests"].append(request)
        checkpoint()
        try:
            record["text"], record["chunks"] = recognizer.transcribe(str(audio), filter_silence=True)
            checked_chunks(record["chunks"], "input ASR", required=True)
            request["outcome"] = "success"
            record["status"] = "completed"
        except Exception as exc:
            request.update(outcome="error", error_type=type(exc).__name__)
            raise
        finally:
            request["finished_at"] = time.time()
            checkpoint()
    except Exception as exc:
        record.update(error_type=type(exc).__name__, error=str(exc))
    record.update(started_at=started, finished_at=time.time(), cpu_seconds=time.process_time() - cpu,
                  request_count=len(record["requests"]))
    checkpoint()
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True, type=Path, help="Pinned v3 directory")
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--input-asr", type=Path, help="Existing evaluator-side input ASR evidence JSON")
    parser.add_argument("--input-audio", type=Path)
    parser.add_argument("--whisper", type=Path, help="Explicitly run local whole-input ASR using these existing assets")
    parser.add_argument("--output-asr-identity", required=True)
    parser.add_argument("--judge-endpoint")
    parser.add_argument("--judge-identity")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists(): parser.error("Fresh output required")
    if bool(args.input_asr) == bool(args.whisper) or args.whisper and not args.input_audio:
        parser.error("Supply --input-asr OR --input-audio with --whisper")
    result = json.loads(args.result.read_text(encoding="utf-8"))
    # Old recordings lacking these clocks cannot be repaired by running ASR now.
    # Reject before an explicitly requested, potentially expensive local decode.
    try:
        clock_origins(result)
    except ValueError as exc:
        report = {"status": "infrastructure_error", "infrastructure_error": str(exc),
                  "qualification_eligible": False, "judge_requests": [], "native_judge_calls": [],
                  "input_asr_requests": 0, "inference_sha256": file_hash(args.result)}
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
        return 1
    inference_hash = file_hash(args.result)
    def asr_checkpoint(record):
        checkpoint_json(args.output.with_suffix('.input-asr.json'), record)
        checkpoint_json(args.output, {'status': 'infrastructure_error', 'phase': 'input_asr',
            'qualification_eligible': False, 'input_asr_evidence': record,
            'inference_sha256': inference_hash, 'judge_requests': [], 'native_judge_calls': []})
    input_asr = (json.loads(args.input_asr.read_text(encoding="utf-8")) if args.input_asr
                 else transcribe_input(args.input_audio, args.whisper, record_callback=asr_checkpoint))
    asr_checkpoint(input_asr)
    def evaluation_checkpoint(report):
        report['inference_sha256'] = inference_hash
        if args.input_asr: report['input_asr_sha256'] = file_hash(args.input_asr)
        checkpoint_json(args.output, report)
    report = evaluate_latency(args.upstream, result, input_asr, args.judge_endpoint, args.judge_identity,
                              output_asr_identity=args.output_asr_identity, record_callback=evaluation_checkpoint)
    evaluation_checkpoint(report)
    print(json.dumps({"status": report["status"], "metrics": report["metrics"], "qualification_eligible": False}))
    return 0 if report["status"] == "complete_diagnostic" else 1


if __name__ == "__main__":
    raise SystemExit(main())
