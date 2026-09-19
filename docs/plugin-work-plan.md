# Orca Strigov plugin conversion

Status: repository implementation complete; installation/live rollout not run.
This is repository maintenance, not an Orca coordinator assignment. No live
Bureau session or user configuration was modified. Current evidence and limits:
[plugin-validation.md](plugin-validation.md).

## Acceptance

1. One installable plugin contains exactly three discoverable skills: orca-dev,
   orchestration and orca-cli; helpers, references and hooks travel with it.
2. The plugin remains self-contained after the native skills are removed.
   It does not reload their unmodified role/handoff rules through skills get.
3. A single role contract distinguishes a live worker, an established
   coordinator, new implementation, supervised tasks and explicit full handoff.
   Missing Run and short continuation prompts never demote a coordinator.
4. Durable coordinator binding and a synchronous stop guard distinguish pending
   work, a live worker, evidence-backed completion and an actual human blocker.
   Workers and unrelated sessions are not trapped. User interruption wins.
5. Native Orca capabilities, lifecycle authority, ownership and release safety
   remain intact. Version provenance and compatibility limits are documented.
6. Installation/migration does not silently delete native skills, bypass hook
   trust or modify unrelated settings. Plugin paths work without the old skill
   symlink or a stale ORCA_DEV_HOME.
7. Shared positive/negative tests cover routing/continuation, packaging and
   installation isolation. Native PowerShell accompanies runtime changes;
   platform results and missing live evidence are reported explicitly.

## Work

- [x] Bundle and reconcile all native command references.
- [x] Fix the development entrypoint, resume and phase transitions.
- [x] Implement session/continuation guards and native Windows counterpart.
- [x] Update packaging, migration and documentation.
- [x] Run directed tests, integrated regression checks and completion audit.

Do not mark this list complete from intent, static wording checks alone or
historical test results. Record exact commands and results in the final report.
