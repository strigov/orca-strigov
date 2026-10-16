# Plan revision

Revise the plan `<PLAN>` that you wrote. Open review findings:

<FINDINGS>

Fix every `blocking` finding; fix a `minor` one when it is cheap. Edit only this file. Keep the frontmatter keys, the phase ids and the `## F{n}: {title}` headings consistent with each other. Do not fill `orca_run` and do not add `implementer`. No commits.

When done, report through the Orca worker preamble: worker_done subject `DONE`, body: one line per finding id, `fixed` or `not fixed: {reason}`. The reviewer reads your reasons in the next round.
