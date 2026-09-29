"""Offline quota-observer controls using synthetic responses and MockTransport."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import importlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import httpx

from .quota import QuotaObserver, quota_metadata
from .record import fingerprint, write_json


PRIVATE = "PRIVATE-SENTINEL-project-123-secret-key"
BODY = {"error": {"message": PRIVATE, "project": PRIVATE, "details": [
    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "45.25s", "message": PRIVATE},
    {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
        "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
        "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "quotaValue": "0",
        "quotaDimensions": {"model": "gemini-3.5-flash-lite", "location": "global", "project": PRIVATE},
        "subject": PRIVATE, "description": PRIVATE, "apiKey": PRIVATE,
    }]},
    {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "metadata": {"project": PRIVATE}},
]}}


def synthetic_response():
    return httpx.Response(429, json=BODY, headers={"Retry-After": "46", "X-Project": PRIVATE})


class UnreadStream(httpx.SyncByteStream):
    def __iter__(self):
        raise AssertionError("Observer attempted to consume an unread stream")


async def run_candidate(candidate, enabled):
    planner_module = importlib.import_module("participant.planner")
    embedding_module = importlib.import_module("participant.embedding")
    assert Path(planner_module.__file__).resolve().is_relative_to(candidate)
    assert Path(embedding_module.__file__).resolve().is_relative_to(candidate)
    functions = {getattr(planner_module.Planner, name).__code__: phase for name, phase in (
        ("_decide", "planning"), ("_perceive_audio", "acoustic"), ("_warmup", "warmup"))}
    functions[embedding_module.embed_image.__code__] = "embedding"
    observer = QuotaObserver(functions)
    requests = []

    async def reply(request):
        requests.append(hashlib.sha256(request.method.encode() + str(request.url).encode() + request.content).hexdigest())
        return synthetic_response()

    def profile(frame, event, result):
        if event == "return":
            observer.capture(frame)

    config = {"SECRET_GEMINI_API_KEY": "offline-dummy", "PARTICIPANT_PREWARM": "1",
              "PARTICIPANT_IMAGE_EMBEDDING": "0", "PARTICIPANT_MEDIA_ROOT": str(candidate)}
    with patch.dict(os.environ, config, clear=True):
        planner = planner_module.Planner(transport=httpx.MockTransport(reply))
        old_profile = sys.getprofile()
        if enabled:
            sys.setprofile(profile)
        try:
            await planner.setup()
            context = {"messages": [{"event_type": "user_speech_chunk", "payload": {
                "text": "Explain the available help.", "end_of_turn": True}}],
                "tools": {}, "state": {"intent": "", "slots": {}}, "revision": 1}
            try:
                await planner.plan(context)
                raise AssertionError("Mock HTTP 429 must remain a planner failure")
            except planner_module.PlannerError:
                pass
            source = {"message_index": 0, "mime_type": "audio/mpeg"}
            try:
                await planner._perceive_audio([(source, [])], 1, asyncio.get_running_loop().time())
                raise AssertionError("Mock HTTP 429 must remain an acoustic failure")
            except planner_module.PlannerError:
                pass
            embedded = await embedding_module.embed_image(planner.client, "offline-dummy", {
                "mimeType": "image/png", "data": base64.b64encode(b"synthetic-offline-bytes").decode()})
        finally:
            await planner.close()
            sys.setprofile(old_profile)
    return {"requests": requests, "statuses": [r["status"] for r in planner.evidence],
            "embedding_status": embedded["evidence"]["status"], "rows": observer.rows,
            "errors": observer.errors, "closed": planner.client is None and not planner._pending_tasks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    candidate = args.candidate.resolve()
    if args.out.exists():
        parser.error("Refusing to replace prior evidence")
    before = fingerprint(candidate)
    clean = quota_metadata(synthetic_response())
    encoded = json.dumps(clean)
    checks = {
        "valid_retry_header": clean.get("retry_after") == "46",
        "valid_retry_info": clean.get("retry_info") == [{"retryDelay": "45.25s"}],
        "valid_quota_fields": clean.get("quota_violations") == [{
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "quotaValue": "0",
            "quotaDimensions": {"model": "gemini-3.5-flash-lite", "location": "global"}}],
        "private_fields_absent": PRIVATE not in encoded and all(name not in clean for name in ("message", "body", "apiKey", "project")),
        "non429_ignored": quota_metadata(httpx.Response(200, json=BODY)) is None,
        "malformed_json_omitted": quota_metadata(httpx.Response(429, content=b"not json")) == {"http_status": 429},
        "oversized_body_omitted": quota_metadata(httpx.Response(429, content=b" " * 65537)) == {"http_status": 429},
        "unread_stream_untouched": quota_metadata(httpx.Response(429, stream=UnreadStream())) == {"http_status": 429},
        "invalid_header_omitted": quota_metadata(httpx.Response(429, headers={"Retry-After": PRIVATE})) == {"http_status": 429},
    }
    date = "Mon, 21 Sep 2026 11:00:00 GMT"
    checks["valid_http_date"] = quota_metadata(httpx.Response(429, headers={"Retry-After": date})).get("retry_after") == date
    bad = {"error": {"details": [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": PRIVATE},
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
            "quotaMetric": "projects/" + PRIVATE, "quotaId": "projects/" + PRIVATE,
            "quotaValue": True, "quotaDimensions": {"model": "projects/" + PRIVATE, "location": PRIVATE}}]},
    ]}}
    checks["invalid_allowlisted_values_omitted"] = quota_metadata(httpx.Response(429, json=bad)) == {"http_status": 429}

    def yielding(response):
        yield None
        yield None

    observer = QuotaObserver({yielding.__code__: "planning"})
    generator = yielding(synthetic_response())
    for _ in generator:
        observer.capture(generator.gi_frame)
    checks["coroutine_resume_deduplicated"] = len(observer.rows) == 1 and not observer.errors

    sys.path.insert(0, str(candidate))
    baseline = asyncio.run(run_candidate(candidate, False))
    observed = asyncio.run(run_candidate(candidate, True))
    checks.update({
        "exact_same_four_mock_requests": len(baseline["requests"]) == 4 and baseline["requests"] == observed["requests"],
        "unchanged_failure_results": baseline["statuses"] == observed["statuses"] == [429, 429, 429] and baseline["embedding_status"] == observed["embedding_status"] == "provider_error",
        "all_four_phases_captured": [r["phase"] for r in observed["rows"]] == ["warmup", "planning", "acoustic", "embedding"],
        "request_ids_captured": all(len(r.get("request_id", "")) == 32 for r in observed["rows"] if r["phase"] != "embedding"),
        "observed_metadata_sanitized": PRIVATE not in json.dumps(observed),
        "observer_error_free": not observed["errors"],
        "both_planners_closed": baseline["closed"] and observed["closed"],
        "candidate_unchanged": before == fingerprint(candidate),
    })
    report = {"checks": checks, "passed": all(checks.values()), "external_provider_calls": 0,
              "mock_requests": 8, "candidate": str(candidate), "candidate_sha256": before,
              "acceptance_source_sha256": fingerprint(Path(__file__).resolve().parent),
              "baseline": baseline, "observed": observed}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.out, report)
    print(json.dumps({"passed": report["passed"], "checks": len(checks), "failures": [k for k, v in checks.items() if not v], "external_provider_calls": 0}))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
