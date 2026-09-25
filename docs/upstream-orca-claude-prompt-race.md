# Draft upstream report: Claude worker prompt lost on fresh `worker-start`

Status: draft for the Orca maintainers; not sent. Sending needs the owner's approval.

**Versions.** Orca 1.4.211 (macOS), Claude Code 2.1.282.

**Summary.** `orca orchestration worker-start --agent claude --model opus --effort xhigh` on a fresh
terminal returns `ok: true`, `state: outcome_unknown`, `stage: turn_start_unobserved`,
`lastError: "input was written and submitted, but claude's turn start could not be verified (up to 30s)"`
in 3 of 6 attempts. The Claude Code TUI then shows an empty composer (placeholder `Try "…"`), no session
transcript is created, and the Dispatch never starts.

**Reproduction.** A trivial task ("send one `worker_done`"), `worker-start --worktree current --agent claude
--model opus --effort xhigh --timeout-ms 240000`, six sequential attempts. Screen reads (`terminal read
--screen`) 5, 15 and 30 s after launch.

**Evidence.** In one failing attempt the raw preamble text is visible 5 s after launch, printed in the
terminal before the Claude Code banner; by 15 s the TUI is drawn with an empty composer. In the other two
failing attempts the TUI is already drawn at 5 s with an empty composer. Successful attempts show the input
as a paste chip in the composer at 5 s.

**Expected.** The Dispatch input is delivered after the Claude Code TUI accepts input, or the start reports
a definite delivery failure instead of `outcome_unknown`.

**Workaround in use.** `terminal create --command "claude …"`, wait until the rendered screen shows the
Claude Code banner and composer (≈5 s), then `dispatch --inject`: 3 of 3 delivered.

**Related.** `worker-show` returns `projection.provider.model: null` for Claude Dispatches (Path A and Path B)
while it reports the model for Codex. A verifiable effective model for Claude would let supervisors avoid
reading Claude Code session transcripts to establish which model ran.
