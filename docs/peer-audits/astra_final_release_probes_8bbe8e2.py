"""Offline release counterexamples, with controls, for a checkout or frozen package.

Usage: python -B docs/peer-audits/astra_final_release_probes_8bbe8e2.py SOURCE
Uses the adjacent previous-review helper, real validation/controller/media code,
mocked HTTP responses, and synthetic receipts. Never calls a live provider.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import wave

import astra_release_probes as p


def actions(agent):
    return [{"action": row["action"], **row["payload"]} for row in p.drain(agent)]


def apply(agent, calls):
    proposal = p.decision(calls)
    p.Planner._validate(proposal, [], agent.tools)
    agent._apply(proposal)


def direct(text, name, args, schema, quote=None):
    tool = {"kind": "state_modifying", "description": name.replace("_", " ") + ".", "args": schema}
    agent = p.agent_for({name: tool}, text)
    step = {"api_name": name, "args": args,
            "authorization": {"quote": quote or text, "message_index": 0}}
    apply(agent, [step])
    return {"text": text, "tool": tool, "proposal": step,
            "grant": p.authorization_grant(step, tool, [(0, text)]), "actions": actions(agent)}


def object_binding(returned, *, leaf_bindings=False):
    text = "Read the profile for Nia. Then set settings.limit=2 and settings.enabled=true for Nia."
    schema = {"customer": {"type": "string"}, "settings": {"type": "object", "properties": {
        "limit": {"type": "integer"}, "enabled": {"type": "boolean"}}}}
    tools = {"read_profile": {"kind": "read_only", "args": {"customer": {"type": "string"}}},
             "set_settings": {"kind": "state_modifying", "description": "Set settings for a customer.", "args": schema}}
    agent = p.agent_for(tools, text)
    bindings = ({"settings.limit": "settings.limit", "settings.enabled": "settings.enabled"}
                if leaf_bindings else {"settings": "settings"})
    step = {"api_name": "read_profile", "args": {"customer": "Nia"}, "after_result": {
        "api_name": "set_settings", "args": {"customer": "Nia"}, "bindings": bindings,
        "authorization": {"quote": text.split("Then ")[1]}}}
    apply(agent, [step])
    p.event(agent, "tool_result", call_id="call-1", api_name="read_profile", status="success",
            result={"settings": returned})
    return {"text": text, "proposal": step, "returned": returned, "actions": actions(agent)}


def scalar_binding(quote):
    text = "Read the profile for Nia. Then set mode safe for Nia."
    tools = {"read_profile": {"kind": "read_only", "args": {"customer": {"type": "string"}}},
             "set_mode": {"kind": "state_modifying", "description": "Set mode for a customer.",
                          "args": {"customer": {"type": "string"}, "mode": {"type": "string"}}}}
    agent = p.agent_for(tools, text)
    step = {"api_name": "read_profile", "args": {"customer": "Nia"}, "after_result": {
        "api_name": "set_mode", "args": {"customer": "Nia"}, "bindings": {"mode": "mode"},
        "authorization": {"quote": quote}}}
    apply(agent, [step])
    p.event(agent, "tool_result", call_id="call-1", api_name="read_profile", status="success",
            result={"mode": "dangerous"})
    return {"text": text, "proposal": step, "actions": actions(agent)}


async def lost_image(text, *, audio=False, image_status="missing", claim_only=False):
    with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
            "THREAD_API_KEY": "offline-only", "PARTICIPANT_PREWARM": "0",
            "PARTICIPANT_IMAGE_EMBEDDING": "0", "PARTICIPANT_MEDIA_ROOT": folder}, clear=True):
        if image_status == "corrupt":
            (Path(folder) / "lost.png").write_bytes(b"not an image")
        with wave.open(str(Path(folder) / "sample.wav"), "wb") as stream:
            stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            stream.writeframes(b"\0\0" * 1600)
        reply = p.decision(response="An unrelated offline fact.")
        requests = []

        def handle(request):
            body = json.loads(request.content)
            acoustic = body["systemInstruction"]["parts"][0]["text"].startswith("Transcribe the actual")
            requests.append("acoustic" if acoustic else "main")
            return p.completion(json.dumps({"observations": reply["observations"]} if acoustic else reply))

        planner = p.Planner(transport=p.httpx.MockTransport(handle))
        await planner.setup()
        agent = p.agent_for({"manual": {"kind": "read_only", "args": {"query": {"type": "string"}}}}, planner=planner)
        p.event(agent, "video_frame", image_ref="lost.png")
        p.event(agent, "user_speech_chunk", text="Tell me an unrelated fact.", end_of_turn=True)
        agent._apply(await planner.plan(agent._context()))
        if audio:
            p.event(agent, "user_audio_chunk", audio_ref="sample.wav", end_of_turn=True)
        else:
            p.event(agent, "user_speech_chunk", text=text, end_of_turn=True)
        p.drain(agent)
        rows = [{"message_index": 2, "type": "audio", "transcript": text, "uncertain": False}] if audio else []
        template = ("Manual: {records.0.title}." if "LAN" in text else
                    "The printed LAN port is described by {records.0.title}.")
        reply = p.decision([{"api_name": "manual", "args": {"query": "LAN"}, "response_template": template}], rows)
        if claim_only:
            reply = p.decision(observations=rows, response="The port in that picture is labeled LAN.")
        try:
            proposal = await planner.plan(agent._context())
            agent._apply(proposal)
            if agent.operations:
                p.event(agent, "tool_result", call_id="call-1", api_name="manual", status="success",
                        result={"records": [{"title": "LAN connector manual"}]})
            accepted = True
        except p.PlannerError:
            accepted = False
        finally:
            await planner.close()
        return {"text": text, "audio": audio, "image_status": image_status, "claim_only": claim_only,
                "accepted": accepted, "actions": actions(agent), "requests": requests,
                "prepared_media": planner.evidence[-1]["input_media"]}


async def inline_audio(texts, *, disagree=False, uncertain=False):
    with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
            "THREAD_API_KEY": "offline-only", "PARTICIPANT_PREWARM": "0",
            "PARTICIPANT_IMAGE_EMBEDDING": "0", "PARTICIPANT_MEDIA_ROOT": folder}, clear=True):
        for index in range(len(texts)):
            with wave.open(str(Path(folder) / f"{index}.wav"), "wb") as stream:
                stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                stream.writeframes(b"\0\0" * 1600)
        native = []

        def handle(request):
            acoustic = json.loads(request.content)["systemInstruction"]["parts"][0]["text"].startswith("Transcribe the actual")
            rows = [{"message_index": index, "type": "audio", "uncertain": uncertain and acoustic,
                     "transcript": text.replace("Tallinn", "Oslo") if disagree and acoustic else text}
                    for index, text in enumerate(texts)]
            reply = {"observations": rows} if acoustic else p.decision(
                [{"api_name": "flight_search", "args": {"destination": "Bergen"},
                  "response_template": "Option {flights.0.flight_id}."}], rows)
            if not acoustic:
                reply["slots"] = {"destination": "Bergen"}
            native.append(reply)
            return p.completion(json.dumps(reply))

        planner = p.Planner(transport=p.httpx.MockTransport(handle))
        await planner.setup()
        tool = {"kind": "read_only", "description": "Search flights to a destination city on a given date.",
                "args": {"destination": {"type": "string", "required": True,
                                           "description": "Destination city name or airport code."}}}
        agent = p.agent_for({"flight_search": tool}, planner=planner)
        for index in range(len(texts)):
            p.event(agent, "user_audio_chunk", audio_ref=f"{index}.wav", end_of_turn=index == len(texts) - 1)
        p.drain(agent)
        try:
            proposal = await planner.plan(agent._context())
            agent._apply(proposal)
            return {"texts": texts, "disagree": disagree, "uncertain": uncertain,
                    "decision": proposal, "native": native, "actions": actions(agent)}
        finally:
            await planner.close()


async def main():
    with p.offline() as attempts:
        mode_schema = {"mode": {"type": "string", "enum": ["safe", "dangerous"]}, "customer": {"type": "string"}}
        strings = [direct("Set mode safe for Nia and explain dangerous mode.", "set_mode",
                          {"mode": mode, "customer": "Nia"}, mode_schema) for mode in ("safe", "dangerous")]
        for description in ("Recipient name.", "Recipient of the message."):
            for recipient in ("Nia", "Omar"):
                strings.append(direct("Send a message to Nia saying Omar arrived.", "send_message",
                    {"recipient": recipient, "message": "Omar arrived"}, {
                        "recipient": {"type": "string", "description": description}, "message": {"type": "string"}}))
        for description in ("Recipient name.", "Recipient of the message."):
            strings.append(direct("Send a message to Nia saying happy birthday.", "send_message",
                {"recipient": "Omar", "message": "happy birthday"}, {
                    "recipient": {"type": "string", "description": description}, "message": {"type": "string"}}))
        result = {"source": str(p.ROOT), "runtime_sha256": {
                    name: hashlib.sha256((p.ROOT / "participant" / name).read_bytes()).hexdigest()
                    for name in ("agent.py", "authorization.py", "planner.py", "media.py", "schema.py")},
                  "strings": strings,
                  "objects": [object_binding({"limit": limit, "enabled": enabled}, leaf_bindings=leaf)
                              for limit, enabled, leaf in ((2000, False, False), (2000, False, True),
                                                           (2, False, True), (2, True, False))],
                  "bound_strings": [scalar_binding("set mode safe for Nia.")],
                  "lost_images": [await lost_image(text, audio=audio, image_status=status)
                      for text in ("What is the port in that picture?",
                                   "Look up the manual for the port in my last photo.",
                                   "Look up the manual for the LAN port.")
                      for audio in (False, True) for status in ("missing", "corrupt")],
                  "unsupported_visual_answer": await lost_image("What is the port in that picture?", claim_only=True),
                  "inline_audio": [await inline_audio(texts, **options) for texts, options in (
                      (["Search flights to Bergen; actually, make that Tallinn."], {}),
                      (["Search flights to Bergen; actually, make that Tallinn.",
                        "Make that Vilnius; make that Ljubljana."], {}),
                      (["Search flights to Bergen; actually, make that Tallinn."], {"disagree": True}),
                      (["Search flights to Bergen; actually, make that Tallinn."], {"uncertain": True}),
                      (["Search flights to Bergen; actually, make that Tallinn if refundable."], {}))],
                  "external_network_attempts": attempts}
        assert not attempts
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
