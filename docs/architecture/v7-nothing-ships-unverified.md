# v7.0: Nothing Ships Unverified

> The first version whose contract is about what LEAVES the brain, not what lives inside it.

## The problem (verified)

Every major so far hardened the inside: v4 made an unwired rule a corruption, v6 made every fail-closed gate prove it blocks. Neither says anything about the moment that actually costs money: the send. On 2026-09-05 a formal complaint email left the brain asserting that a bank charge "did not correspond to any contracted service". The charge was a purchase the operator had itemized to that same counterpart in chat weeks earlier, and the brain memory held it too. Nobody looked. A correction followed minutes later, and a correction inside a money claim discredits the claims that were right. The gate that now catches that phrase (`COMMS.unsourced-absence`, #257) was written after the fact, which is how every COMMS gate in this brain was born: one incident, one phrase, one Stop hook.

That is the pattern, not the exception. Measured at v6.24.0 with `brain_doctor.py`:

| Surface | Reading | What it means |
|---|---|---|
| Enforcement floor | FORCED 25/31 gateable (81%) | 6 gate-shaped rules run at model discretion under a waiver |
| Detect tier | 14 rules | They report; nothing is stopped |
| Waivers | 6, expiry-tracked | `CODE.dry-run-first`, `FLOW.delegate-gate`, `FLOW.3d-diligent-gate`, `FLOW.enforcement-scripts`, `COMMS.no-pause`, `FLOW.budget-halt` |
| Memory directives | 128/128 REFLEX, "obedience unproven" | Every lesson the brain has learned is injected as text and enforced by nothing |
| Outward-send gates | 6 Stop hooks, each keyed on one phrase class | Post hoc, per incident, blind to the send they did not anticipate |

The honest statement of v6 is: a rule that exists is proven to bite. The honest statement of what v6 does not give is: a send can still leave with zero receipts, as long as no known phrase trips a known gate.

"Code without defects" is not a contract a brain can sign; no gate proves the absence of an unknown class. "Nothing ships unverified" is: every outward action carries machine receipts, and a send without them is impossible, not discouraged.

## The contract

An **outward action** is any tool call whose effect leaves the operator's machine and cannot be recalled: sending mail, sending a chat message, merging a PR, deploying, publishing an artifact, writing to a client system.

An outward action is allowed only when the turn carries a **receipt bundle**:

1. **Seek receipt.** For every claim of fact about the counterpart or the past (an amount, a date, an absence, a category), a lookup ran in this turn: memory seek, chat search, mail search, or the arm expediente. The receipt is the act of looking, never its result.
2. **QA receipt.** For code and for any deliverable above TRIVIAL, an independent verdict on the judgment tier, recorded in the turn, not asserted in prose.
3. **Gate receipt.** Every fail-closed gate that watches this class of action has a green `--selftest` at HEAD, and no waiver covers it.

Missing any one of the three: the action is denied at PreToolUse, with the missing receipt named. `absence-ok`-style hatches stay per line, never per turn.

## The architecture

Four load-bearing pieces, in dependency order.

1. **One send choke point.** A single PreToolUse gate (`g__pre__outward-send.py`) matches every outward tool by name (mail, WhatsApp bridges, `gh pr merge`, deploy CLIs, artifact publish) and reads the turn's receipt ledger. The six Stop-time COMMS gates keep their phrase logic but become *contributors* to the ledger, not independent tripwires: each one writes what it checked, and the choke point refuses when the ledger is empty for a class the send needs. Today the checks fire after the reply is composed and only on the phrase they know; after this they fire before the tool runs and on the absence of evidence.

2. **The receipt ledger.** A per-session file (`.octorato/receipts/<session>.jsonl`, gitignored, same discipline as goal-anchor) appended by hooks, never by prose: PostToolUse on seek tools writes a seek receipt; the QA subagent's verdict is written by the harness, not pasted by the model; `--selftest` runs write gate receipts. The model cannot forge a receipt because the model never writes the file. This is the same agent-proof argument as `OCTO_MERGE_APPROVE`: only the harness path authorizes.

3. **Floor 100%, no grey zone.** The 6 waivers get a decision each: promote to fail-closed with a fixture pair, or demote to PRESENCE and say so in the anchor. The 14 detect-tier rules get the same binary. `brain_doctor` grows one assertion: `gateable && !fail-closed` with no waiver is already a FAIL; v7 removes the waiver escape for rules older than 90 days.

4. **No incident closes without a fixture.** Each incident recorded in memory that names a gate as its mechanism must have a `registry/fixtures/<rule-id>/` pair where the benign fixture is the violation minus one edit (the derivation rule already in memory). The doctor's `corpus-coverage` gains a column: incidents with mechanism / incidents with fixture. The 128 REFLEX directives are triaged by recurrence: any lesson with two or more memories of the same class becomes a gate candidate, and the candidate list prints in the doctor until it is empty or explicitly demoted.

## Phases

| Phase | Output | Doctor assertion added |
|---|---|---|
| 0 | This spec. | none |
| 1 | Receipt ledger + PostToolUse writers for seek tools and selftests. | `receipt-ledger-live`: a seek in a fixture transcript produces a ledger line |
| 2 | `g__pre__outward-send.py`, fail-closed, fixture-proven; the six COMMS Stop gates rewired as ledger contributors. | `outward-send-gate`: a send fixture with an empty ledger is denied |
| 3 | QA receipt: the coworking QA subagent verdict lands in the ledger via the harness path; `qa-merge-gate` reads the ledger instead of only the env. | `qa-receipt-agent-proof`: a ledger line written from the model path is rejected |
| 4 | Waivers and detect tier resolved to a binary; enforcement floor prints 100% FORCED or names each demotion. | `floor-100`: any gateable rule not fail-closed is FAIL, no waiver escape past 90 days |
| 5 | Incident-to-fixture ledger; REFLEX triage list; first three recurrent lessons promoted to gates. | `incident-fixture-coverage`: incident with mechanism and no fixture is FAIL |
| 6 | Cut v7.0.0 with the `Octorato-Major:` trailer. Release notes print the receipt classes and the floor, not the diff. | none |

## Release criterion

v7.0.0 ships when `brain_doctor.py` prints all of:

- Floor: FORCED n/n gateable (100%), waived 0.
- Outward-send gate: fixture-proven, covering every send tool registered in `hooks.json`.
- Incident-fixture coverage: 100% of incidents that name a mechanism.
- REFLEX triage: 0 recurrent lessons without a decision.

Not a claim of zero defects. A claim that zero known defect classes are unwired, and that no send leaves without receipts. The next unknown class will still get through once; v7 guarantees it gets through with a ledger that shows exactly which receipt was missing, and that the gate written for it is proven before the incident closes.

## Decisions recorded

- Target: `octorato` v6.24.0 → v7.0.0. Major, because the contract changes: sends that work today will be denied until they carry receipts.
- The ledger is harness-written, never model-written. A receipt the model can type is not a receipt.
- Waivers are a migration device, not a steady state. v7 is the release that retires them.
- The six existing COMMS gates are not deleted; they become the phrase detectors that feed the one send gate. Harmonization over accretion.
