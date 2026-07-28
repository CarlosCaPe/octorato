---
name: verify-root-cause-before-claiming
description: "Antes de decirle a alguien la CAUSA de una falla, verificala contra el dato, no contra el sintoma. Una causa plausible sin comprobar dana mas la confianza que decir 'la confirmo en un momento'. Dispara al escribir 'fallo porque' o 'se debe a'."
metadata:
  type: feedback
---

# verify-root-cause-before-claiming

**Why:** In one session I drafted a client message explaining a permission-denied
failure as "the grant landed after your run, so it wasn't there yet". The operator
asked "are we sure?" before sending. Checking the grant history showed the grant had
existed 12 minutes BEFORE the run. The real cause was different (UNLOGGED staging
tables get recreated by each schema apply, dropping their grants). My causal claim was
plausible, confident, and wrong. Had it shipped, the stakeholder would have retried on
a false premise and lost trust when it failed again.

**The trap:** verifying the SYMPTOM (the grant is applied now, the build is green, the
row count is N) and then asserting a CAUSE (it failed because of timing) that you never
checked against the data. The symptom is real; the causal story is a guess wearing the
symptom's credibility.

## How to apply

Before any outward-facing "it failed because X" / "the reason is Y":

1. **Separate what you verified from what you inferred.** "The grant is applied" is
   verified. "It wasn't applied at run time" is an inference. Only the first earns a
   flat claim.
2. **Pull the timeline / the history that the cause depends on.** If the claim is about
   timing, get the actual timestamps of both events. If it's about a missing object,
   confirm the object was missing AT the moment of failure, not just now.
3. **Try to falsify your own cause once.** Ask "what would make this explanation
   wrong?" and check that specific thing. Here it was "did the grant already exist
   before the run?" — one query would have caught it.
4. **If you cannot verify the cause, say so.** "The fix is applied; the exact root cause
   I'm still confirming" is honest and costs far less trust than a confident wrong
   story. Ship the verified part, hedge the unverified part explicitly.
5. **Welcome the "are we sure?" check.** When the operator or a reviewer pauses you
   before an outward-facing claim, that is the cheapest possible catch. Treat it as a
   gift, re-verify, do not defend the draft.

## Companion skills

- `investigate-before-asking` — investigate before escalating; this is its outward-facing twin (investigate before *claiming*).
- `source-citation-tagging` — every fact references where it came from; a cause with no source is a guess.
- `incident-capture` — when the verified root cause is itself worth recording.
