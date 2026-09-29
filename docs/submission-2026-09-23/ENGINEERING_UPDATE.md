# Engineering update — 23 September 2026

The latest complete Samsung-kit diagnostic on `e5b97d3` scored **71.5/100 weighted, with four of nine public cases passing**. It selected the experimental `single_call_reads` audio mode and the documented Gemini 3 temperature default. Five generation requests reached the planning timeout, and one earlier audio request was canceled when new speech arrived. All six had finished uploading before waiting for response headers. Neither the lower request count nor this temperature experiment has established reliable delivery.

An earlier independently reviewed run on `0bf30ee` scored **100/100 with nine passes**, but its later unchanged three-repetition batch did not qualify: **13 passed and four failed before the API limit stopped attempt 18; nine attempts never ran**. There is no complete passing 27-attempt batch. The preceding `d394a46` diagnostic passed five of nine at 76.4 weighted. The current local runtime, `8ee289e`, repairs stale displayed state and suppresses speech from stale completed writes while retaining their true outcomes. It passes 352 offline participant tests and all seven unchanged supplemental late-result probes; that combined candidate has no live result yet. Offline checks and successful Windows/Linux package admission do not override the measured live failures. This checkpoint is prepared for repository review and continuation. It is not a release, deployment or competition submission.

## What the team has changed

The comparison baseline is `8abdf844cd5a72ab803fa1fd4d1bba506b3614e3`.

Old test results belong to the saved version named beside each result. The team
checkpoint combines the current reviewed files; earlier development commits remain
local. A package's recorded hash identifies exactly what was tested.

| Change | What it means for a user |
| --- | --- |
| Actions are tied to the request that authorized them. | A deliberate new request can repeat an earlier action. A camera update or another transcription of the same recording cannot silently repeat it. |
| Read retries retain one logical operation identity. | We can distinguish retrying a lookup from starting a new task. |
| Clarification questions stay open until answered. | A late result cannot bypass an unanswered question and continue an old action. |
| A changed request no longer presents the previous intent and slots as newly understood. | While the new request is unresolved, current-state snapshots show empty active fields. Earlier constraints remain available internally, and the action record still reports real completed effects. Audio-failure clarifications cannot silently make old state current again. |
| Late completed actions remain recorded without producing stale speech. | The record preserves what really happened, while an interrupted result cannot answer or resume the new request. Duplicate notices cannot cause another effect. |
| Result selection checks every requested condition and skips incomplete rows. | A valid later option is not missed because the first row lacks a field. Ambiguous options still require clarification. |
| A small set of complete text flight-booking commands has a bounded local route. | The timed original booking example now confirms the actual successful mock booking in about 4.1 seconds. It uses the returned flight ID. Unsupported wording or additional requirements still go through Gemini. |
| Complete literal text booking goals can begin with a local discovery lookup. | A single-word destination or explicitly quoted multiword destination, plus a supported explicit date, can start a read without a model round trip. Corrections cancel the old read and suppress late results. Broader wording, constraints and unquoted multiword destinations still go to Gemini; actual returned results come before questions about booking details. |
| Returned answers, qualifications and references are preserved. | Important limits in a tool result are not replaced by a document title or shortened away. A mismatched source cannot justify an answer. |
| Default audio handling uses two native passes over all completed clips. | Planning and independent transcription run together. The measured correction case used two requests instead of three and uploaded about 21% fewer bytes than the earlier three-request build. One successful run does not establish a reliable speed improvement. |
| An optional audio mode uses one Gemini request for eligible terminal reads or clarifications. | It keeps those transcripts out of action authorization. Later writes require genuine independent verification of all retained unchecked recordings. Failed interpretation preserves the recording identity so a fresh request can recover. The latest live diagnostic used six generation requests, but its audio planning requests produced no usable response, so native quality and reliable delivery remain unproven. |
| The correction check includes preceding raw audio. | A short correction is interpreted in its actual spoken context. |
| Unverified speech cannot remain in the audio cache after a sibling check fails. | An uncertain or canceled check cannot leave behind a seemingly verified transcript. |
| A bounded speech-format rule tolerates harmless punctuation in terminal flight reads. | Matching words can differ in a final full stop, initial prose capitalization or a permitted discourse comma. The new extension covers explicit corrections within a complete current audio turn. Destination spelling, material words, uncertainty and action authority remain strict; repairs that depend on earlier uncertain history keep the previous stricter rule. |
| One leading “uh” or “um” can be omitted between clear agreeing first-request transcripts. | A separately labeled rule tolerates that single omission on a fresh terminal flight lookup. It preserves original transcript evidence and rejects changed destinations, request words, substitutions and inherited-history omissions. No permission to book is added. |
| A narrow confirmation rule accepts an omitted confirmation phrase. | If the acoustic check clearly hears “I said NAME” and planning returns only that exact name, the same bounded terminal lookup can proceed. The evidence labels word omission separately from punctuation; it grants no permission to book. |
| Image observations distinguish a readable category label from an ambiguous intended target. | The new wording prioritizes a conditional read-only lookup for a clearly recognized category when it can usefully answer the question. Gemini must supply the actual label and call. Uncertain recognition, an explicit different target and an ambiguous requested action still require the appropriate safeguards. |
| Image explanations distinguish ordinary background knowledge from manual evidence. | A general explanation is labeled separately. Actual returned answers and qualifications take precedence, and the returned reference must still match. |
| Successful flight discovery preserves a verified unfinished booking request. | Actual search results are followed by a question about the flight choice and passenger name. Completed speech and interruption events follow the same bounded rules. A lookup never supplies permission to book. |
| Gemini setup and configuration are consistent. | A judge supplies their own API key and can check the package without spending a model request. |
| Gemini 3 requests now use the documented default temperature of 1.0. | The previous forced value was zero. Other model families retain their previous setting. The actual value is recorded for planning and transcription. Offline comparisons found no other request changes; the live diagnostic did not demonstrate a benefit. |
| Packaging uses an explicit file list. | The archive contains the participant and original kit files; credentials, local environments and private evaluation material stay out. |
| Evaluation preserves unsuccessful attempts and identifies the exact package tested. | A good result from an older build cannot be mistaken for proof that the newest build passes. |
| Optional timing diagnostics identify connection, upload and response stages. | We can investigate media timeouts while preserving the actual request bodies and deadlines. Missing or unassociated timings remain explicit; broken capture stops the diagnostic. |
| The independent test runner now supports real audio and images. | It preserves unfinished cases and distinguishes local completion from native model evidence. The 18 prepared stories still need to run against a frozen package. |

The speech-format rule is deliberately narrow. It does not normalize arbitrary speech, infer an earlier uncertain booking goal, or allow a write. The image attestation is Gemini's own claim of recognition; it is not independent proof that the model saw the image correctly.

## Results we can actually support

| Check | Result | Scope |
| --- | --- | --- |
| Latest complete original kit diagnostic, once | **71.5 weighted; 73.8 plain average; 4/9 pass** | Exact `e5b97d3` archive with explicit experimental `single_call_reads` and temperature 1.0, original order and timings. All nine returned; every native generation request ended without a response. This is not repeated qualification. |
| Preceding optional-audio diagnostic | **76.4 weighted; 79.6 plain average; 5/9 pass** | Exact `d394a46` archive and same profile, before the temperature change. One generation request returned. Different service conditions prevent attributing the later score difference to temperature alone. |
| Separate longer service observations | **Neither of two requests returned headers or a response within 15 seconds** | Exact reconstructed `e5b97d3` text and audio bodies on the same 3.5 model, one observation each. Two generation calls, no recorded quota rejection, no observer errors, worker reaped normally. This is diagnostic evidence outside the participant, not a kit result or a reliability estimate. |
| Separate 3.1 model comparison | **Text: HTTP 503; audio: HTTP 200 after 8.23 seconds** | Same two bodies with only the model endpoint changed. The text response reports high demand; the audio response ends normally but arrives after the participant's 4.5-second budget. Neither is a usable timely result. The participant default remains 3.5; no kit result is reassigned. |
| Tiny current-model health observation | **No response headers or body within 15 seconds** | One 224-byte request to the same 3.5 model, asking for a fixed JSON boolean; one generation start, normal process completion, no observed quota rejection or capture error. This is a censored service observation, not a kit result or an identified cause. |
| Fresh Windows/Linux health comparison | **Both timed out without headers or a response within 15 seconds** | Same tiny body, Gemini model and API project, one sequential observation per platform. Two generation requests in total; both owned workers reaped normally. No observed quota rejection or capture error. This does not isolate a platform, network or provider cause. |
| Earlier successful original kit run, once | **100 weighted; 100 plain average; 9/9 pass** | Exact `0bf30ee` archive, default independent audio, original timings, all text/audio/image cases. Independent scoring, case audits and factual review passed. This is an automated public-kit result, not a competition ranking or hidden-test result. |
| Combined participant tests | **352/352 pass** on integrated `8ee289e` | Zero errors, skips, blocked connections or runtime changes. Includes independently reviewed state freshness and stale-speech corrections. The preceding `f03cda9` source passed 351. The measured `e5b97d3` candidate passed 332; `d394a46` passed 330; earlier successful `0bf30ee` passed 293. |
| State-freshness review and compatibility | **Ten fresh review methods and 19 existing independent methods pass** | Separate peer `5e9a284` review exercises queued corrections, late read/write results, synthetic audio fallbacks and the five adjusted legacy fixtures. Existing race/audio suites retain their expectations. The 35 labeled subtests are counted separately from methods; these checks do not measure native completion. |
| Temperature-only source review | **Two new methods independently pass; no blocking finding** | Full planner AST matches the parent after normalizing only the two intended temperature expressions and two evidence assignments; other runtime files match `d394a46`. Owner checks also compare four model/mode cases and 24 mock request starts. This is source and request validation, not live performance evidence. |
| Independent optional-audio checks | **8 methods / 33 labeled subtests pass** on `203027f` | Scripted source, cancellation, authority and deadline controls, plus actual-controller recovery after failed audio and discarded ready replies. A separate reviewer closed the original recovery finding with five focused methods. Peer source and integrated source are recorded separately; neither result measures live recognition. |
| Scripted controller corpus | **2,880 pass** | Controller state and permission coverage. These are not model conversations. |
| Independent interruption/race checks | **11 pass** | Rechecked at `0bf30ee`, using injected decisions and results. |
| Independent booking boundary checks | **9 methods / 49 labeled cases pass** | Bounded local-booking behavior; a separate review also passed eight probes. |
| Independent speech-agreement checks | **13 methods / 64 labeled cases pass** | Pinned filler candidate `42e0702`, integrated in `289e9fd`. Generic formatting and distinct leading-filler omission checks, original transcript hashes, inherited-history boundaries and strict authority limits. Mocked model responses do not establish real recognition quality. |
| Independent confirmation-role checks | **4 methods / 25 labeled cases pass** | Rechecked on exact `0bf30ee`. Changed entities, uncertainty and action authority remain guarded. This does not verify an earlier uncertain goal or establish live recognition quality. |
| New image-contract checks | **81 methods pass** | Constructed and retained observations, source checks and rendering. Text/audio-only request bodies are unchanged by this image change. |
| Independent booking-follow-up review | **Eight targeted probes pass after two reproduced edge cases were fixed** | Completed-text corrections and full requests delivered as interruptions now work. Unfinished or unrelated dialogue, invalid fragment boundaries and older writes do not restore an old goal. |
| Configuration/package checks | **28 focused methods pass on each platform** | Mode resolution, setup consistency and package selection, using Windows and Linux. Counts describe the same controls on each platform, not 56 different checks. |
| Sealed archive installation/admission | **Windows and Linux pass in new empty virtual environments** | Exact `0bf30ee` archive and unchanged documented dependency recipe. All ten runtime dependencies were absent initially; installation and separate offline admission succeeded with no live provider call. Existing OS/Python 3.11.9 were reused. The `d394a46` and `e5b97d3` packages also pass fresh-extraction admission on both platforms in the existing pinned environments; no dependencies or provider calls were needed for those later checks. The new `1a18c97` review archive, containing the combined `8ee289e` runtime, also passes fresh-extraction admission on both platforms with the default independent audio profile and no model calls. It remains unqualified for live delivery. |
| Unseen evaluation stories | **18 prepared, none run** | Six text, six synthetic speech and six original diagrams. They remain withheld from implementation. |
| Full repeated qualification | **Stopped; not qualified** | Same `0bf30ee` package: 13 PASS / 4 FAIL, one unscored quota-stop attempt, nine UNRUN. No complete aggregate. A complete passing batch and another unchanged repeat remain required. |
| Finished demonstration | **4:51 local film completed** | Selected passing `0bf30ee` examples; original input audio/image and exact result text. Recorded replay, mock tools and edited holds are labeled. The later repeat-batch failure is prominent. Visual and automated media checks passed; no subjective listening claim. |

The current review archive has SHA-256
`3714ea142cdd3fb8c77ed48d5c085ed056c572f22733e4009653079eb049c1e8`.
It contains 52 files from exact source `1a18c97`: 18 selected source files, 33
preserved kit files and a manifest. All seven runtime files match the tested
`8ee289e` build. Windows and Linux extraction, dependency checks and offline
admission passed using the existing pinned environments; dependencies were not
reinstalled. Configuration-only checks used no model requests. This verifies
package setup and identity, not live model performance. Two private audit
prechecks were corrected and retained; the archive was not rebuilt and admission
was not rerun.

The stale-write correction now passes all seven original supplemental probes unchanged. On `f03cda9`, `stale_revision_then_success` and `cancel_pending_then_success` still failed because the controller spoke about a stale completed write. The earlier internal notice design did not establish an exception to Samsung's stale-result contract. `8ee289e` removes that speech branch after preserving the validated durable outcome. Updated maintained tests require silence while retaining state, authorization, duplicate and continuation checks; a new method covers open user turns and unanswered clarification. Independent review found no blocking issue. The owner also passed 122 focused methods and 11 race methods, and the combined gate then passed 352 methods. The old 5/7 result and the fresh pre-fix reproduction remain saved. Test totals are not a substitute for complete user tasks.

## What the latest diagnostic exposed

The `e5b97d3` diagnostic returned all nine cases in 66.253 seconds. It started six generation requests and one embedding request, with no quota rejection, request-cap stop or delivery-observer error. All six generation requests ended without a response: five planning timeouts and one cancellation by new input. The embedding request succeeded but was never used in a tool call. The four passing cases used local planning; they do not establish native model quality. The worker completed and was reaped normally. A successful process exit means the evaluation finished, not that the participant passed.

All seven request bodies finished sending. The six generation requests then waited about 4.0–4.4 seconds for response headers. This evidence does not establish an upload stall or isolate provider computation from network and scheduling time. No acoustic verification request ran, and no native audio observation or joint-read decision was accepted. Body-derived phase records contain temperature 1.0; the transport evidence retains body hashes and sizes, rather than serialized request JSON. Offline body comparisons and pinned source establish the intended change, without pretending the native payload was independently decoded from those hashes.

In the preceding `d394a46` run, the text correction canceled an actual Boston lookup about 2.3 ms after the interruption event. Its replacement plan timed out, so no New York search or final result followed, and the displayed snapshot retained the old destination. The later temperature-only run also failed the revised task. Cancellation correctness, truthful displayed state and completion of the new task are separate requirements. The new `f03cda9` state repair addresses the display defect; it does not supply the missing response.

The latest case scores were 100, 58.2, 100, 100, 53.8, 56.9, 47.7, 100 and 47.7. The experimental mode remains optional; `independent` remains the default. Both failing diagnostics, their exact configurations and their original evidence are retained.

The temperature experiment was motivated by Google's [Gemini 3 guide](https://ai.google.dev/gemini-api/docs/gemini-3#temperature), which identifies 1.0 as the default, and its [newer guidance](https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.5#sampling-parameters-no-longer-recommended), which recommends removing sampling overrides and retaining defaults. It preserved the model, prompts, schemas, raw media, token caps and deadlines. The run did not demonstrate a benefit, and uncontrolled service/network conditions prevent a causal claim about the lower score. Further complete batches remain paused while the separate service-latency investigation continues. Such probes cannot count as kit passes or supply reused answers to evaluation.

That smaller investigation has now run. The full text and audio request bodies
were reconstructed offline and independently reproduced with the same hashes and
sizes as the original native requests. Each was sent once to the same model with
a 15-second observation window. Neither returned headers or a complete response.
The two observations consumed two generation requests and produced no usable
answer; their process completed normally after 30.541 seconds. This does not show
that the requests could never complete, or isolate the cause of the delay. It
does show that these two delays were well beyond the participant's budget.

A later comparison used the exact same bodies on supported free Gemini 3.1
Flash-Lite. Its text request returned a complete HTTP 503 error after 1.967
seconds, with the provider reporting high demand. Its audio request returned
HTTP 200 and a normal finish reason after 8.229 seconds. Its proposed read preserved
the corrected destination and passed direct structural checks, but the plan did
not fully follow the booking-goal and result-template instructions. That answer
is neither fully compliant nor evidence of meeting the participant deadline. One request per body cannot rank
the models reliably or explain the earlier 3.5 timeouts. These observations do
not justify changing the participant's default model. The official deadlines, failed
kit results and original source remain unchanged.

A separate tiny request to the current 3.5 model then asked only for a fixed
JSON boolean, with a 64-token output limit and no media, tools or participant
context. Its 224-byte body finished sending about 184 ms after dispatch, but no
response headers or body arrived within the 15-second observation window. The
worker completed and was reaped normally. That result weakens a prompt-size-only
explanation for the earlier delays without proving an outage or a common cause.
A later fresh comparison sent that same tiny body once from Linux and once from
native Windows, using the same model and API project. Both reached their
15-second observation limit without headers or a response body, and both workers
were reaped normally. No quota rejection or capture error was observed. The
Windows diagnostic wrapper differed only in its platform guard and matching
error label; it did not change production code. One sequential pair cannot isolate
platform or service causality. Neither observation earned a new kit pass or
established timely responses. No further provider request is allocated at this
checkpoint.

## What the earlier successful run proves

The ambiguity audio case asks for clarification, accepts the clearly spoken confirmation, searches Boston and reports the actual returned flight at 9,526.7 ms. It had only 673.3 ms left before the original scheduled tail ended. Both native transcripts exactly said “I said Boston.” in this attempt, so neither the formatting rule nor the separate bare-name rule was exercised. It did not infer permission to book from the earlier uncertain request.

The correction audio case exercised all three allowed formatting differences on both clips: initial prose case, a discourse comma and a terminal period. The actual words and final destination agreed. The New York search completed and supplied the final result at 6,129.0 ms, with 1,271.0 ms remaining. After that result, the controller asked which flight and passenger to use for the verified unfinished booking request. Gemini's native plan was search-only; the follow-up belongs to the controller. No booking occurred.

The image case selected the literal HDMI label while keeping the intended target ambiguous. It searched for “HDMI port”, supplied the real current image embedding, and received the laptop manual's page 27, titled “HDMI Output”. The final answer at 5,758.1 ms conditionally explains the ordinary purpose and separately identifies the returned reference; it does not present the title as a retrieved explanatory passage. It had 841.9 ms left before the original scheduled tail ended. Some unused neighboring observations were not independently corroborated, so this success does not validate every visual detail the model described.

The run made ten generation requests and one embedding request. Eight generation requests and the embedding request returned successfully; the two initial planning cancellations were expected from the corrected request and uncertain audio. No timeout, quota rejection or diagnostic-capture failure occurred. Client timing does not isolate provider computation or explain earlier timeouts.

The text cases also passed and used actual returned results. The corrected search still needed a flight choice and passenger name before booking. It interrupted planning before an old tool started, so this particular example does not demonstrate cancellation of an already-running tool. The separate chained-booking example confirmed an actual successful mock-tool result. These are test-environment actions, not commercial reservations.

The preceding `fa0c69f` snapshot scored 86.7 with seven passes; two older snapshots scored 82.8 with six passes. Their media failures differed: formatting disagreement, omitted confirmation words, native image clarification and deadline failures. Every attempt stays in the evidence. Earlier vectors, responses and successes are not carried forward into later runs. The improved outcome is not a controlled estimate of how much each individual change helped.

## What the repeat run exposed

The unchanged official order groups three repetitions of each scenario. The batch returned 17 scored attempts: 13 passed, while one text correction and three audio attempts failed. Attempt 18 stopped on the confirmed free-tier limit of 15 generation requests per minute. The final nine attempts, including every image repetition, were not run. Independent review reproduced all 17 scores and audits, verified the exact package and retained the partial attempt without inventing a score.

The text failure reached the planner timeout without a usable response. Two audio failures reached the acoustic check deadline with neither native transcript available. The other audio failure had clear responses but one transcript omitted the leading word “Uh”; the current policy rejected that word omission. These are different failure causes. The later quota rejection does not establish why the earlier timeouts occurred.

The audio group started 18 generation requests in 46.920 seconds. Each complete audio turn currently uses two native calls. The whole-batch average hides this short burst, so merely waiting before launching another unchanged batch does not reliably solve the limit. We are staying on the free tier and reviewing a genuine reduction in per-turn requests. Any such change must explicitly account for losing the independent transcript comparison and must earn new evidence.

The distinct leading-filler omission policy and conservative text-discovery route were integrated in `289e9fd`, with 306 combined checks passing at that point. Separate review also exercised actual pending-read cancellation, stale-result suppression, retries, malformed results and the clarification latch. The later `d394a46` and `e5b97d3` diagnostics included those changes and still failed reliable delivery. Neither change is credited retroactively to the successful `0bf30ee` build. The text shortcut deliberately leaves unquoted multiword destinations to Gemini, so it does not remove the recorded public correction's model dependency. A leading-filler fix alone also does not cure slow responses or request limits.

One successful repeated audio confirmation finished with only 173.8 ms left. The request observer retained one unfinished response-close stage while the supervisor completed and reaped the worker; this is incomplete cleanup evidence, not proof of a leaked process. Every failure and limitation stays in the review record.

## What must happen before submission

1. Completed: independent review, all nine unchanged original cases once on `0bf30ee`, and fresh Windows/Linux virtual-environment installation. The current combined `8ee289e` runtime includes independently reviewed state freshness and stale-speech repairs and passes 352 offline checks. It has no live qualification result.
2. Completed: implement and review the optional `single_call_reads` audio profile, repair failed-audio recovery, and package and run two unchanged nine-case diagnostics. Both diagnostics failed delivery. State freshness and stale-result speech repairs are verified locally. The longer 3.5 observations, separate 3.1 comparison and tiny current-model health check did not establish timely delivery. Further unchanged full batches remain paused; use new service evidence before another batch or production model change. Preserve every earlier failure and freeze any changed source and profile anew. The existing `independent` profile remains the default.
3. Run the 18 frozen independent stories with actual media. Their runner supports native media and preserves partial evidence; the stories themselves remain unchanged and unrun.
4. Complete the original public qualification batch and a second passing batch on the identical artifact, with factual review. Externally paced diagnostics may help investigate free-tier reliability but must not be presented as an unchanged official batch.
5. Completed: the local 4:51 evidence film, source/cut manifest and media checks. Its selected passing examples retain the measured package identity and the later repeat-run limitations. Update it only if a newer build earns its own evidence.

Samsung evaluates `participant.agent:ParticipantAgent`. The existing browser and Android applications use a separate runtime; participant repairs do not automatically update those applications. Demonstration footage must identify which runtime it shows. A recorded participant trace proves its recorded actions and timing, not audible playback in the browser.

The historical candidate-009 result was 62.6 weighted over 27 attempts, with 6/27 mandatory and 4/27 full passes. The newer 100-point snapshot has only nine attempts, so the difference is not a controlled reliability comparison. We have stronger evidence for action handling, actual media and setup, but no defensible probability of winning or measured ranking against other teams.

Related reading: [next round plan](NEXT_ROUND_PLAN.md), [readiness report](READINESS_REPORT.md), [competitor comparison](COMPETITOR_COMPARISON.md), [demonstration storyboard](DEMO_STORYBOARD.md), [demonstration evidence checklist](DEMO_EVIDENCE_CHECKLIST.md), and [judge quickstart](../submission/GEMINI_QUICKSTART.md).
