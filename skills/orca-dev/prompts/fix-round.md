# Fix round

Same repository and task as your previous brief. Fix these open items (review findings or failing checks):

<FINDINGS>

Rules:
- Fix every `blocking` item; fix a `minor` one only when it is cheap and inside your task.
- TDD: when an item is a bug, first add a test that reproduces it and see it fail, then fix the code.
- Touch only what the fixes need. Do not commit, stash or reset.
- Never use the `Schedule` timer; wait for tests with one blocking shell call.

Before reporting, run each of these commands and make it pass:

<VERIFY>

When done, report through the Orca worker preamble: worker_done subject `DONE`, body: one line per item, `fixed: {how}` or `not fixed: {reason}`, then the result of each command above. If you cannot fix them, subject `BLOCKED: complexity` or `BLOCKED: requirements` and the reason.
