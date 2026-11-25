# Fix round

Same repository and task as your previous brief. Fix these open items (review findings or failing checks):

<FINDINGS>

Rules:
- Fix every `blocking` item; fix a `minor` one only when it is cheap and inside your task.
- TDD: when an item is a bug, first add a test that reproduces it and see it fail, then fix the code. If the test passes without a fix, the item is false: keep the test, change no code, report `not fixed: not reproduced`.
- Prefer the simplest fix. Where an item would need new machinery for a rare case, refuse that case with a clear error instead and say so in the `fixed:` line.
- Touch only what the fixes need. Do not commit, stash or reset.
- Never use the `Schedule` timer; wait for tests with one blocking shell call.
- Before you report, stop every process you started (servers, watchers, app instances) and delete the temporary copies you made (app copies, build folders); name both in the report.

Before reporting, run each of these commands and make it pass:

<VERIFY>

When done, report through the Orca worker preamble: worker_done subject `DONE`, body: one line per item, `fixed: {how}` or `not fixed: {reason}`, then the result of each command above. If you cannot fix them, subject `BLOCKED: complexity` or `BLOCKED: requirements` and the reason.

Outcome: `--outcome failed` only with a `BLOCKED` subject, when you could not do the job; every other report, `FINDINGS` and `not fixed` lines included, uses `--outcome succeeded`.
