# orca-strigov: repository maintenance

This repository is the orca-strigov plugin: three coordinated skills (orca-dev,
orchestration, orca-cli), worker templates, hooks, POSIX helpers, native
PowerShell helpers and their tests.

## Choose the correct context

An Orca worker follows its live assignment and lifecycle preamble. Do not load
or restart the coordinator protocol merely because the assignment asks for code.
A standalone maintenance session may inspect and edit this repository directly.
When a coordinator user asks for implementation ("реализуй", "запили", "implement",
"build this feature") inside an Orca terminal (ORCA_TERMINAL_HANDLE is set),
automatically load the installed orca-dev skill. Outside Orca only an explicit
$orca-dev invocation activates it. Standalone reviews and dispatched workers
do not activate the coordinator workflow. The repository maintenance exception
above permits direct authorized edits here. Never emulate unavailable Orca receipts.

## Sources of truth

Use skills/orca-dev/roles.md for model identities, efforts, families and allowed
fallbacks; keep those facts out of other runtime instructions. Use
skills/orca-dev/runtime-contracts.md for machine interfaces and report binding.
Use the bundled orchestration references and their upstream.md version record
for CLI lifecycle. Verify actual syntax with the selected CLI's --help and
receipts; do not re-import conflicting stock role/handoff policies at runtime.
Read platform installation notes when changing installation or launch behavior;
read the corresponding contract when changing a runtime helper.

## Change boundaries

Preserve the user's working changes and environment. Do not push, alter global
CLI configuration, disable security controls, install tools or modify production
resources without authorization. Local isolated checks explicitly authorized by
the task may run without asking again for each directed check. Do not assume that
all repository tests are isolated: check their fixture and side-effect contract.

A runtime semantic change requires matching POSIX and native Windows behavior,
shared positive/negative fixtures, and explicit platform results. A Windows or
WSL result is not a macOS result. Do not fabricate PASS or fill missing evidence
with an old report. Preserve immutable report bytes across corrections and fixes.

Report the exact commands run, results, limitations and the changed files.
Do not repeat an unchanged full suite without a named regression hypothesis,
a required independent replay, or a relevant source/environment change.
