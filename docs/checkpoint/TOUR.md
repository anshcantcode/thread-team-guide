# THREAD walkthrough

Allow five minutes. Follow [setup](SETUP.md) first. Start in Kitchen to exercise the current controller; the existing Gemini home screen is a separate mode.

## Make a real change

Open `http://127.0.0.1:8768` or Android **Settings → Open Kitchen**. Connect, then type or speak a new request such as **“Add rinse lentils to my checklist.”** Wait for the device receipt and saved row. The local planner proposes, the controller authorizes, and the client performs the write.

This is a suggested tour input, not a hardcoded demo trigger or guaranteed model response. English is the pinned recognizer's language; multilingual recognition is not qualified.

## Read the result and keep it

Ask **“Read my checklist.”** Inspect the returned items and request identity. End the connection, reopen Kitchen, and inspect the checklist. Persistence belongs to this browser profile or Android app data. A new conversation gets fresh authority, not permission inherited from the previous connection.

## Correct a request

Speak a request and correct its item before submission. Observe the words, tool request and receipt. Only the surviving authorized proposal may run. Recognition and planning can vary; inspect receipts rather than treating smooth speech as proof.

An interruption after a device has accepted a write cannot erase that effect. THREAD retains and reconciles its outcome. The app does not claim rollback of an already-committed checklist item.

## Inspect the engineering and evidence

Read [architecture](ARCHITECTURE.md), then inspect `participant/agent.py`, `participant/authorization.py`, `thread_agent/fdb3.py` and `thread_agent/fdb3_client.py`. Independent tests cover stale typed work, token reuse, late outcomes, duplicate device requests and playback receipts.

For the official 12-tool scenario, use the benchmark runner. Kitchen's three real device tools are an extension beyond that mock-tool domain. Benchmark flight/shopping outputs are simulated services.

[Verification](VERIFICATION.md) links archived full runs and current checks. A 61/100 historical local diagnostic is not an official score and is not inherited by changed source. The [submission checklist](SAMSUNG.md) records the remaining qualification and human steps.
