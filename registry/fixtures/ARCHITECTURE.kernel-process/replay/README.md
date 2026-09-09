# The golden replay fixture

`journal.jsonl` is a hash-chained kernel journal and `expected.txt` is what
`octo replay --fixture . --verify` prints for it, byte for byte. `octo selftest`
and `brain_doctor`'s `kernel-replay` check both compare against it, so the pair
is the contract for the replay reader.

## The timestamps are load-bearing outside this directory

Every `ts` and `start_ts` in `journal.jsonl` sits in June 2025, years outside any
7-day window. That is not incidental. `scripts/tests/test_deny_coverage.py`
copies this journal into a sandbox `HOME` with a fresh mtime so the doctor's
replay and chain assertions execute on every machine while the deny count it
measures stays 0, which is what makes the WARN branch of `deny_coverage`
reachable at all.

Regenerating the file with the clock of the day is a plausible maintenance
action and it breaks that. Measured: rebuilt with `ts` values an hour old, the
chain still verifies and `octo selftest` is happy, and
`test_the_warn_reaches_the_caller_that_was_dropping_it` goes red, because the
journal's three `deny` lines now land inside the window and the WARN needs an
empty one. Nothing in the failure points back here.

So regenerating this fixture is two steps, not one:

1. Regenerate `journal.jsonl` and `expected.txt` together, and keep the `ts`
   values old. Only the chain has to be internally consistent; the clock does
   not have to be now.
2. Run `python3 -m unittest scripts.tests.test_deny_coverage` before committing.
   A red WARN test means the new timestamps landed inside the window.

The hashes chain line to line, so an edit to any line breaks every line after
it. Regenerate the whole file rather than patching one record by hand.
