# Team plan and demonstration

[Home](../README.md) · [Start here](START_HERE.md) · [What works](WHAT_WORKS.md) · [Setup](RUN.md) · [Code map](CODE_MAP.md)

## What we are trying to prove

Our strongest story is that **the user can change a request while work is running, and the assistant keeps the task and its effects consistent**.

The Android app makes this tangible. Useful cards and widgets show why someone would use it. The controller, traces, and service outcomes explain why the interruption behavior deserves technical attention.

The supplied brochure puts submission on **25 September** and caps a team at **four**. We are four people. Recheck organizer communications for changes and obtain the exact evaluation kit before assuming the provisional adapter matches it.

## Suggested four-person split

These are responsibilities to choose together, not claims about who already built each part.

| Lane | Own the outcome | First useful task |
|---|---|---|
| Core and evaluation | Corrections, pending work, permission, effects, and organizer integration. | Trace one interrupted demo task; compare the provisional interface with the official kit when available. |
| Android and interaction | Voice behavior, task/result screens, Library, widgets, and release stability. | Run a real spoken correction on the S24 and log audio + state behavior. |
| Tools and integrations | Reliable sources, clear coverage, useful result content, Google/Spotify flows. | Verify a weather/sports/search journey with source dates and an explicit failure case. |
| QA and presentation | Reproducible evidence, clear demo, script, deck, and submission completeness. | Build the claim-to-evidence list and rehearse a five-minute demonstration. |

Pair across lanes for changes touching both a tool contract and its native renderer. Keep the effect/permission rules under review whenever a new action can change something.

## Priority order before submission

### 1. Resolve organizer-dependent questions

- Obtain the exact Theme 05 kit, transport schema, model/network rules, and required package/template.
- Run the entry point in the actual required environment. The existing Docker recipe has not been validated on this Windows host.
- Tie the submission, reports, and demonstration to the same final candidate.

### 2. Strengthen the real phone experience

Use the S24 we have. Test spoken corrections during a response, noise-only interruptions, long provider delays, an unavailable provider, leaving/reopening the app, and microphone lifecycle. Separate subjective feel from measured timings.

A short set of well-recorded real conversations is more useful here than another decorative feature. Keep the current result readable while the assistant is active.

### 3. Close one integration completely

Spotify is a clear remaining integration task. Register the Developer app, configure the phone callback, complete consent, and verify playback/repeat on an active Premium device. The current exact phone callback is:

```text
http://127.0.0.1:8767/api/spotify/callback
```

The connection uses a public client ID and PKCE; no client secret is required by this flow. Check the implementation and provider requirements when registering. Do not make working playback part of the demo until an actual account test succeeds.

### 4. Finish the submission story

Use actual team/member/college details when available. Complete the organizer's required forms and disclosure fields accurately. Keep simulated services clearly labelled. Match every technical claim to the correct source revision and evidence scope.

## Five-minute technical demonstration

| Time | Show | Explain |
|---|---|---|
| 0:00–0:30 | Begin a request; correct it before it finishes. | “The assistant needs to update the work when the user changes their mind.” |
| 0:30–1:35 | Fictional flight correction, retained details, and a late obsolete result. | The task changes selectively; old evidence cannot replace the current answer. |
| 1:35–2:25 | Current selection, explicit action request, and the fictional service's outcome record. | Permission belongs to a current action. Inspect the effect, not just the spoken success message. |
| 2:25–3:05 | Unknown/reordered outcome replay. | A missing reply is not proof that nothing happened. Avoid duplicate effects. |
| 3:05–3:45 | A useful Android result, Google tab correction, or personal widget. | The same approach supports daily tasks with visible, actionable results. Complete any real widget pin confirmation. |
| 3:45–4:30 | Reproducible traces and a small evidence table. | Distinguish deterministic controller checks, actual-model tests, and physical-device checks. |
| 4:30–5:00 | Architecture and remaining scope. | Explain the model/controller boundary and the verified submission interface. |

Use the supplied organizer format if it requires a different duration or order. If a segment is prerecorded or simulated, say so on screen. The exact story should survive a live provider failure without pretending a fallback recording is live.

## Product film versus technical proof

The current product film is **43 seconds at 60 fps**, with landscape and portrait compositions. The local application workspace contains:

```text
motion/v2/output/THREAD-Keep-going-landscape.mp4
motion/v2/output/THREAD-Keep-going-vertical.mp4
motion/v2/output/THREAD-Keep-going.srt
```

Ask Ansh for the rendered files; they are large local outputs and are not included in this guide. Use the film to introduce the experience. It is a cinematic composition, not a raw screen recording or a response-latency measurement. Its branded flight details are sample data.

## A useful bug report

```text
Title:
App/source version:
Device and Android version:
Input: typed or spoken
Exact request and correction:
Network/provider conditions:
Expected behavior:
Observed behavior:
Did an action actually occur, or was it only proposed/opened?
Minimal screenshot or redacted error:
Reproduction steps:
```

For a controller bug, include the current request/result IDs and relevant state transition when available. Exclude credentials, private notes, and unrelated device/log content.

## How to explore without losing the plot

1. Pick one user job and one observable improvement.
2. Read the relevant implementation and its existing tests.
3. Make the smallest complete change, including the result/error state.
4. Run the focused checks and exercise the actual affected interface.
5. Record the result and its limits; update the guide if capability status changed.

Do not delete checks to make a result green. Do not report an opened draft as a sent message, a search handoff as successful playback, or a fictional reservation as a real ticket. Those distinctions are part of the product's value.

## Handoff checklist

- [ ] Every teammate can explain the core interruption scenario in their own words.
- [ ] Each teammate has the source or APK needed for their responsibility.
- [ ] The organizer interface and required execution environment are confirmed.
- [ ] Current phone build, source, and evidence are tied together.
- [ ] The live demonstration has been rehearsed with actual speech.
- [ ] Provider failures and simulated services are described honestly.
- [ ] Required team details, forms, deck, video, and disclosure fields are complete.
- [ ] The final package runs from a clean setup under the organizer's rules.
