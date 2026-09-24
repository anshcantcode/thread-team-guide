"""Run public Samsung cases through the reviewed agent with experimental routes.

Requires THREAD_GROQ_API_KEY (or GROQ_API_KEY) for Groq, or DASHSCOPE_API_KEY plus DASHSCOPE_BASE_URL
for an Alibaba Singapore compatible-mode /v1 workspace. Pass --env-file to
read credentials without printing them. This does not modify the submission.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import sys
import time

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "theme5_kit" / "participant-kit" / "participant-kit"
sys.path[:0] = [str(ROOT), str(KIT)]

from harness.runner import EvaluationHarness  # noqa: E402
from harness.scorer import score_scenario  # noqa: E402
from participant.agent import ParticipantAgent  # noqa: E402
from participant.planner import Planner, planner_trace  # noqa: E402


class Route(httpx.AsyncBaseTransport):
    def __init__(self, name, key, base_url, max_calls):
        self.name, self.key, self.base_url, self.max_calls = name, key, base_url.rstrip("/"), max_calls
        self.model = "qwen3.8-flash" if name == "alibaba" else "qwen/qwen3.8-27b"
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(4.3, connect=2.0))
        self.api_calls = 0
        self.rate_limited = False
        self.rows = []

    async def aclose(self):
        # Planner closes its client after each case; the route is shared until all cases finish.
        pass

    async def transcribe(self, mime, encoded):
        if self.name != "groq":
            raise ValueError("Alibaba audio route is not configured")
        self.claim_call()
        filename = "clip.wav" if mime == "audio/wav" else "clip.mp3"
        response = await self.client.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"authorization": f"Bearer {self.key}"},
            data={"model": "whisper-large-v3-turbo", "response_format": "verbose_json", "temperature": "0"},
            files={"file": (filename, base64.b64decode(encoded, validate=True), mime)},
        )
        if response.status_code != 200:
            raise RouteStatus(response.status_code, response.headers.get("retry-after"))
        payload = response.json()
        transcript = payload.get("text", "").strip()
        if not transcript:
            raise ValueError("empty transcription")
        segments = payload.get("segments") or []
        uncertain = "[unclear]" in transcript.lower() or any(
            row.get("avg_logprob", 0) < -1 or row.get("no_speech_prob", 0) > .6 for row in segments
        )
        return transcript, uncertain

    def claim_call(self):
        if self.api_calls >= self.max_calls:
            raise RouteStatus(429)
        self.api_calls += 1

    async def handle_async_request(self, request):
        started = time.monotonic()
        phase = "acoustic" if b"Transcribe the actual speech verbatim" in request.content else "plan"
        row = {"phase": phase, "status": "error"}
        try:
            source = json.loads(request.content)
            content, audio, label = [], [], ""
            for part in source["contents"][0]["parts"]:
                if "text" in part:
                    label = part["text"]
                    content.append({"type": "text", "text": label})
                elif "inlineData" in part:
                    media = part["inlineData"]
                    mime, encoded = media["mimeType"], media["data"]
                    if mime.startswith("image/"):
                        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}})
                    elif mime.startswith("audio/"):
                        match = re.search(r"message_index=(\d+)", label)
                        if match is None:
                            raise ValueError("audio source index missing")
                        transcript, uncertain = await self.transcribe(mime, encoded)
                        index = int(match[1])
                        audio.append({"message_index": index, "type": "audio", "transcript": transcript,
                                      "uncertain": uncertain})
                        content.append({"type": "text", "text":
                            f"Audio transcript for message_index={index}: {transcript}\n"
                            "Copy this exact transcript into the audio observation; preserve uncertainty."})
                    else:
                        raise ValueError("unsupported media type")
            if phase == "acoustic" and audio:
                output = json.dumps({"observations": audio}, ensure_ascii=False)
            else:
                system = source["systemInstruction"]["parts"][0]["text"]
                system += "\nReturn one JSON object with every root decision field."
                if audio:
                    system += "\nCopy each supplied audio transcript exactly into its observation."
                body = {"model": self.model,
                        "messages": [{"role": "system", "content": system},
                                     {"role": "user", "content": content}],
                        "response_format": {"type": "json_object"}, "temperature": 0,
                        "max_completion_tokens": source["generationConfig"]["maxOutputTokens"]}
                if self.name == "groq":
                    body["reasoning_effort"] = "none"
                    body["response_format"] = {"type": "json_schema", "json_schema": {
                        "name": "participant_decision", "strict": False,
                        "schema": source["generationConfig"]["responseJsonSchema"]}}
                self.claim_call()
                response = await self.client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"authorization": f"Bearer {self.key}"}, json=body)
                row["limits"] = {header: response.headers[header] for header in (
                    "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens",
                    "x-ratelimit-reset-tokens", "x-ratelimit-remaining-requests") if header in response.headers}
                if response.status_code != 200:
                    raise RouteStatus(response.status_code, response.headers.get("retry-after"))
                payload = response.json()
                row["usage"] = {k: payload.get("usage", {}).get(k) for k in
                    ("prompt_tokens", "completion_tokens", "total_tokens") if k in payload.get("usage", {})}
                choice = payload["choices"][0]
                if choice.get("finish_reason") != "stop":
                    raise ValueError("incomplete chat response")
                output = choice["message"]["content"]
                json.loads(output)
            row["status"] = 200
            return httpx.Response(200, json={"modelVersion": self.model,
                "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": output}]}}]}, request=request)
        except RouteStatus as exc:
            row["status"] = exc.status
            if exc.status == 429:
                self.rate_limited = True
            if exc.retry_after is not None:
                row["retry_after"] = exc.retry_after
            return httpx.Response(exc.status, json={"error": "route request failed"}, request=request)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            row["status"] = type(exc).__name__
            return httpx.Response(502, json={"error": "route conversion failed"}, request=request)
        finally:
            row["elapsed_ms"] = round((time.monotonic() - started) * 1000)
            self.rows.append(row)


class RouteStatus(Exception):
    def __init__(self, status, retry_after=None):
        self.status = status
        self.retry_after = retry_after


def configure(args):
    local = dotenv_values(args.env_file) if args.env_file else {}
    def value(name):
        return os.environ[name] if name in os.environ else local.get(name, "")
    os.environ.update(THREAD_PROVIDER="gemini", PARTICIPANT_PREWARM="0",
                      PARTICIPANT_MEDIA_ROOT=str(KIT), PARTICIPANT_TIMEOUT_SECONDS="4.5",
                      PARTICIPANT_AUDIO_MODE="independent")
    if args.model:
        if args.route != "gemini" or re.fullmatch(r"gemini-[a-zA-Z0-9_.-]{1,100}", args.model) is None:
            raise ValueError("--model accepts an explicit Gemini model with --route gemini")
        os.environ["PARTICIPANT_MODEL"] = args.model
    if args.thinking:
        os.environ["PARTICIPANT_THINKING_LEVEL"] = args.thinking
    if args.route == "gemini":
        key = value("SECRET_GEMINI_API_KEY") or value("THREAD_API_KEY")
        if not key:
            raise ValueError("Gemini key missing")
        os.environ["SECRET_GEMINI_API_KEY"] = key
        return None
    names = ("THREAD_GROQ_API_KEY", "GROQ_API_KEY") if args.route == "groq" else ("DASHSCOPE_API_KEY",)
    keys = {value(name) for name in names} - {None, ""}
    if len(keys) > 1:
        raise ValueError("Conflicting route credentials")
    key = next(iter(keys), "")
    if not key:
        raise ValueError(f"{' or '.join(names)} missing")
    base = value("DASHSCOPE_BASE_URL") if args.route == "alibaba" else "https://api.groq.com/openai/v1"
    if args.route == "alibaba" and not base.endswith("/compatible-mode/v1"):
        raise ValueError("DASHSCOPE_BASE_URL must end in /compatible-mode/v1")
    os.environ["SECRET_GEMINI_API_KEY"] = "transport-intercepted-placeholder"
    os.environ["THREAD_API_KEY"] = "transport-intercepted-placeholder"
    os.environ["PARTICIPANT_IMAGE_EMBEDDING"] = "0"
    return Route(args.route, key, base, args.max_calls)


async def evaluate(args, route):
    paths = sorted((KIT / "scenarios").glob("pub_*.json"))
    if args.cases:
        wanted = set(args.cases)
        paths = [p for p in paths if p.stem in wanted]
        if {p.stem for p in paths} != wanted:
            raise ValueError("case name not found in public scenarios")
    rows = []
    try:
        for path in paths:
            if route and route.rate_limited:
                break
            scenario = json.loads(path.read_text(encoding="utf-8"))
            meta = scenario["metadata"]
            weight = (1.5 if meta["modality"] in ("audio", "visual") else 1) * (
                1.25 if meta["difficulty"] in ("L3", "L4") else 1)
            scores, timings = [], []
            for _ in range(args.reps):
                if route and (route.api_calls >= args.max_calls or route.rate_limited):
                    break
                harness = EvaluationHarness(scenario,
                    lambda iq, oq: ParticipantAgent(iq, oq, planner=Planner(transport=route)),
                    time_scale=args.time_scale, verbose=False)
                try:
                    with planner_trace(lambda record: timings.append({key: record.get(key) for key in
                            ("phase", "status", "elapsed_ms", "finish_reason", "validation_error") if key in record})):
                        trace = await asyncio.wait_for(harness.run(), timeout=args.wall_cap)
                    score = score_scenario(scenario, trace)["total"]
                except asyncio.TimeoutError:
                    score = 0
                scores.append(score)
            if scores:
                row = {"scenario_id": path.stem, "modality": meta["modality"], "weight": weight,
                       "scores": scores, "median": statistics.median(scores), "planner_timings": timings}
                rows.append(row)
                print(f"{path.stem}: {row['median']:.1f} ({', '.join(str(n) for n in scores)})")
    finally:
        if route:
            await route.client.aclose()
    total_weight = sum(row["weight"] for row in rows)
    weighted = sum(row["median"] * row["weight"] for row in rows) / total_weight if total_weight else 0
    complete = len(rows) == len(paths) and all(len(row["scores"]) == args.reps for row in rows)
    complete = complete and not (route and route.rate_limited)
    return {"route": args.route, "model": route.model if route else os.getenv("PARTICIPANT_MODEL", "gemini-3.5-flash-lite"),
            "public_scenarios_only": True, "reps": args.reps, "time_scale": args.time_scale,
            "complete": complete, "rate_limited": bool(route and route.rate_limited),
            "thinking_level": os.getenv("PARTICIPANT_THINKING_LEVEL", "minimal"),
            "image_embedding": os.getenv("PARTICIPANT_IMAGE_EMBEDDING", "1") == "1",
            "audio_mode": os.getenv("PARTICIPANT_AUDIO_MODE", "independent"),
            "planning_timeout_s": 4.5,
            "weighted_score": round(weighted, 1), "scenarios": rows,
            "api_calls": route.api_calls if route else None, "requests": route.rows if route else [],
            "planner_sha256": hashlib.sha256((ROOT / "participant" / "planner.py").read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", choices=("gemini", "groq", "alibaba"), required=True)
    parser.add_argument("--model", help="explicit Gemini model override")
    parser.add_argument("--thinking", choices=("minimal", "low", "medium", "high"))
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--cases", nargs="*", default=[])
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--time-scale", type=float, default=1)
    parser.add_argument("--wall-cap", type=float, default=120)
    parser.add_argument("--max-calls", type=int, default=120)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.reps < 1 or args.max_calls < 1 or args.time_scale <= 0:
        parser.error("reps, max-calls and time-scale must be positive")
    try:
        route = configure(args)
        report = asyncio.run(evaluate(args, route))
    except ValueError as exc:
        parser.error(str(exc))
    print(f"{'Weighted public score' if report['complete'] else 'Partial public score'}: {report['weighted_score']:.1f}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
