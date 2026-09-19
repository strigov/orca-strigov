# Orca runtime baseline

Bundled command guidance was obtained from **Orca 1.4.205**, 2026-09-19:

- `orca skills get orchestration` and its seven `--reference references/<name>.md` files.
- `orca skills get orca-cli` and its browser, automations and publishing references.

Upstream: <https://github.com/stablyai/orca/tree/main/skill-guides>.
The included [MIT license](../../THIRD_PARTY_NOTICES.md) covers adapted Orca text.

Our changes replace role classification, narrow full handoff to actual ownership
transfer, preserve whole-objective continuation, honor roles.md launch policy,
distinguish Run-scoped waiting from all-Run C6 ownership checks, and replace
runtime skills-get dependencies with local references. Safety, capability,
settlement, remote execution and release rules are retained.

## Compatibility

Resolve one executable and record `--version` / `status --json` at startup.
1.4.205 is the inspected baseline, not a claim about every future release.
On another version inspect `--help` for each affected operation and use actual
typed receipts. Unsupported capability, ownership or lifecycle semantics are
UNVERIFIABLE; never guess flags, manufacture receipts, switch execution hosts
or restore the stock role classifier. Workers obey their authentic live
preamble even if its exact capability/launcher differs from an example here.

Maintainers may retrieve a newer guide into an isolated comparison workspace,
review its command/lifecycle delta and update this baseline with tests. Running
coordinators must not replace the bundled workflow instructions with that text.
Removing native skill stubs does not remove the Orca CLI or its runtime hooks;
both remain required. Unrelated device, Linear or cloud-environment skills are
optional integrations, not orchestration prerequisites.
