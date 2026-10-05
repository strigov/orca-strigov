# C5 — complete frozen review package

Part of [runtime-contracts.md](../runtime-contracts.md); load only when the index says so.

## C5 — complete frozen review package

`review-package BASE HEAD [OUTFILE]` and `BASE WORKTREE OUTFILE` retain their
positional interface, full `.diff`, `wrote`/`EMPTY` stdout and exit meanings.
`OUTFILE.manifest.json` adds schema, package id, full BASE/head/mode, snapshot,
complete flag, changed/untracked file statuses, bytes/hash, exclusions, limitations,
parts and coverage. Untracked files are staged only in a temporary index copy;
the real index bytes are checked before/after, including an error path. All Git
exits are checked. Binary patches are retained. Known SDD storage and the exact
output family are excluded only for untracked service data; actual tracked source
and source outside SDD remain included.

A small package uses the original diff as its only part. Larger packages have
`OUTFILE.parts/NNNN.diff`, at most 65536 bytes each; `[start,end)` ranges cover the
entire package exactly once. A long line can cross parts. Oversize/binary input
requires named source inspection and stays uncovered until that check is recorded.
No byte tail, ignored declared input or new file can be discarded for a size cap.

The optional `OUTFILE.provenance.json` carries saved write receipts and the plan's
producer/consumer contracts. Its shape is `{schema_version:1, writes:[], contracts:[], inputs:[]}`
(`inputs` is optional). Each write has `family`, `files`, `receipt_path`,
`receipt_sha256`, `run_id`, `task_id`, `dispatch_id`; saved receipt bytes and all
three IDs must match. Each contract has `id`, `producer` and `consumer` path lists.
The manifest accumulates every recorded family per file, with status
`requires-family-validation`: receipt identity alone does not prove the claimed
family or completeness of the author list. Review/acceptance checks that against
actual launches and role mappings. Absent authorship remains unknown. Preserve all
actual author families per file/unit across fallback and fix waves, using write
Dispatch/launch receipts and file/commit ranges, never coordinator commit trailers.
Unknown authorship does not establish independence. Declared ignored/external
review inputs enter the snapshot and `declared_inputs` manifest with raw hashes
and required source inspection; they are not silently lost because Git ignores
them. Range packages also record both immutable reviewed Git tree identities;
the working snapshot guards the local frozen review context. The diff of a range
package shows only the committed `BASE..HEAD`, so C6 accepts it as a candidate
only when that is all there is: the requested head is the captured and current
HEAD and the worktree/index carry nothing else (plan bookkeeping aside); dirty
or newer source needs a `WORKTREE` package. C6 also requires a package to start
at the step base (the phase base, or `plan_base` for the final review).

Freeze the package for review. Before dispatch and acceptance check the manifest
identity, all part hashes/ranges and current snapshot using the shared helper's
`validate-package MANIFEST` operation (`python3 -B bin/lib/verification.py` or
native `bin/lib/verification.ps1`). Zero verifies artifact integrity, not review
approval. A reviewer reads the manifest and every assigned part in bounded ranges,
then reports package id/hash, snapshot and explicit coverage of parts/files and
both producer and consumer of every contract, including compatibility. Missing,
changed, stale or incompletely covered artifacts require `CANNOT_VERIFY` and a
fresh complete package; ad hoc diffs do not substitute for missing untracked data.

Usually one final reviewer suffices. Mixed authorship can use complementary
reports in the same final round: each unit needs a verdict from a family outside
all its authors. Each reviewer sees whole-branch context. An indivisible unit
without an eligible independent route stays blocked for explicit assignment.
No new role or review loop; the combined final round cap remains 2. Primary/final
review executes only its agreed checkpoint, required risk replay or named new
hypothesis, not an unchanged suite merely because the role/step changed. Warnings
matter when they reveal a material problem or violated requirement, not simply
because stdout is nonempty.
