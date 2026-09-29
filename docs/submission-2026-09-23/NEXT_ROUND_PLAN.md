# Where we pick up

**The next priority is reliable completion of the original kit on one frozen
package.** The current controller and setup checks are strong enough to support
that work. They do not substitute for a model response arriving on time.

Start with [the short handoff](TEAM_HANDOFF.md) and
[the detailed evidence](ENGINEERING_UPDATE.md). Source IDs in those reports
refer to saved local validation snapshots. The current review branch contains
the combined source, tests and setup tools.

## 1. Establish usable model responses

The latest tiny request timed out on both Linux and native Windows. The next
specific diagnostic should compare a minimal direct request, with observation
instrumentation removed, against the observed request path. Keep the same model,
API project, exact body and request settings, and use a bounded sequential plan.
This checks the request client and instrumentation as possible contributors.
Do not assume the provider or operating system is the cause. Changes in service
conditions between attempts still limit causal conclusions.

The delivery owner records the response, timing, errors and exact configuration.
A health response is a reason to try the real task; it is not a public-kit pass.
After a usable result, check representative real text and audio requests before
spending the larger qualification batch.

If responses still exceed the task budget, investigate one specific cause or
configuration change at a time. Preserve the unsuccessful observation. A timeout
before response headers does not, by itself, identify provider computation,
network trouble or an exhausted quota. A Windows/Linux comparison can expose a
useful difference, but one pair cannot prove a platform cause.

Keep model calls with one owner so concurrent experiments do not compete for the
same request allowance. Keep the agreed free tier. Stop on an API quota rejection;
changing keys within the same project does not create more quota.

**Done when:** there is concrete evidence that the selected configuration can
return usable answers with enough time left for the full participant task.

## 2. Test the current package, then repeat it

Use the saved review archive or rebuild using the
[package instructions](../submission/README.md). Record the exact archive hash,
audio mode, model and runtime. The current archive's seven runtime files match
the build that passed 352 offline participant methods.

First run all nine original public cases once as a diagnostic, with their original
inputs, order, deadlines and scoring. Inspect actual answers and tool effects alongside the automatic
score. Fix a reproduced failure in a separate change, run the relevant local
checks, and freeze a new package before claiming a new result.

Our qualification gate is the full original batch: all nine cases across three
repetitions, **27 attempts**, followed by a **second passing 27-attempt batch** on
the identical artifact and configuration. The second batch is our repeatability
check. The earlier nine-pass snapshot failed its later repetitions; two good
nine-case snapshots would not satisfy this gate. Keep complete, failed,
interrupted and unrun attempts visible.

The grouped repetition batch previously exceeded the free project's request
limit during its audio cases. Waiting before a batch does not remove a burst
inside it. A paced diagnostic can help investigate this, but it must be labeled
separately from an unchanged official batch. Do not extend an individual case's
deadline or present saved model output as a fresh result.

**Done when:** both full 27-attempt batches pass and have been independently
reviewed. If the service or quota prevents completion,
record that as a remaining qualification blocker.

## 3. Run the independent stories

The independent evaluation owner has eighteen frozen stories: six text, six
speech and six image cases. Their expectations should stay out of implementation
work before the first run. Use actual media and the same frozen participant.

Review wrong entities, unsafe or duplicate actions, stale answers, invented
references, unnecessary clarification and missed deadlines. Thousands of
scripted controller checks cover useful boundaries, but cannot establish native
model accuracy on these stories or Samsung's undisclosed tests.

**Done when:** all eighteen have actual results and a factual review, with every
failure explained. Cases examined while debugging become regression cases;
do not keep describing them as unseen evidence.

## 4. Make the demonstration match the evidence

Keep the existing 4:51 film as a clearly labeled replay of the older successful
package. Once the current package earns new results, update the selected examples
and the report together. Show an interruption, the corrected task, the actual
returned result and any clarification needed before an action.

The browser and Android applications use a separate runtime. Test that runtime
before claiming a live application demonstration; a participant trace alone
does not establish browser or phone behavior.

**Done when:** the package, report and demonstration identify the same verified
behavior and explain any remaining limits in plain English.

## Keep the work focused

The delivery owner handles model measurements and official runs. The independent
evaluation owner reviews stories and factual outcomes. The controller owner fixes
reproduced state or action defects. The setup owner checks changed packages, and
the demonstration owner updates the film after new evidence exists.

Continue competitive research when it identifies a concrete capability or test
worth investigating. Public repository claims alone cannot establish which team
is ahead. More features, more test counts or more documentation will not resolve
the current delivery blocker by themselves.

## Get the saved team checkpoint

From an existing clone, these commands fetch the review branch and make a
separate checkout. They leave the current working directory's edits in place.
Choose a different checkout directory if that path already exists.

```sh
git fetch https://github.com/anshcantcode/thread-team-guide.git review/submission-checkpoint-2026-09-23
git worktree add --detach ../thread-submission-review FETCH_HEAD
```

Start with the [judge setup instructions](../submission/GEMINI_QUICKSTART.md).
Keep your API key local. Configuration and offline setup checks are separate from
provider calls; do not begin a new live batch without a recorded package and a
bounded request plan.
