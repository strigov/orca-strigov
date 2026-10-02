# C4 — exact inputs and verification evidence

Part of [runtime-contracts.md](../runtime-contracts.md); load only when the index says so.

## C4 — exact inputs and verification evidence

Both gates preserve `PLAN BASE [ROOT]` and accept `--phase ID` and
`--checkpoint directed|integration|final`. No phase selects top-level `verify`;
an explicit phase selects only its own list, including an empty list. Directed
selects directed checks; integration includes directed and integration; final
includes all three. With no checkpoint, all checks in the selected list run.
Legacy block/flow lists, quoted strings, comments and `|`/`>` scalars still work.
Unsupported YAML structures fail parsing; they never become shell commands.

A new list item is a single-line JSON object, also valid YAML:

```json
{"id":"unit","command":"python -B -m unittest","checkpoint":"directed","timeout_seconds":120,"cancel_grace_seconds":2,"no_progress_seconds":30,"resource_key":null,"progress_file":null,"inputs":[],"environment":["LANG",{"tool":"python","version_args":["--version"]}],"hermetic":false,"independent_replay":false}
```

`command` is required. Defaults: id `legacy-N`, checkpoint `directed`, timeout
and no-progress null, grace 2, resource/progress null, inputs/environment empty,
hermetic/replay false. IDs must be unique in the selected list. Commands are
written for the actual shell; there is no translation between Bash/PowerShell.
`inputs` names additional files or recursive directories (absolute, or relative
to cwd), including ignored inputs. `environment` contains variable names and
tool objects with exactly `tool` and `version_args`; tools resolve to an actual
executable, with binary identity and successful bounded version output. Shell
identity is automatic. Variable values are hashed, never published. Unknown
tools, inputs or versions prohibit reusable evidence.

`hermetic:true` is an explicit assertion that all inputs/tools/environment are
declared, there is no concurrent external writer, and the command has no
untracked network/time/database dependency or unobservable temporary mutation.
An absent assertion means false. Do not assert it for an unknown environment.
This is an observability contract, not a sandbox or authentication boundary.
The local owner and single-writer rule still apply. Required independent replay
always executes under the selected verifier's new owner, with a recorded reason;
it cannot be satisfied by the implementer's report or a reused run. A named new
hypothesis likewise forces a physical run. Risk decisions are not inferred from
missing metadata and remain the plan/reviewer's responsibility.

For a C4 runner request add `verification` with normalized `check`, `provenance`
and optional nonempty `repeat_reason`. The check is the object above with all
defaults filled and C3 policy/command identical to the request. Provenance records
`kind` (`HEAD` or `BASE`), full `base_sha`, `preparation` and
`linked_dependencies`. The gates produce this binding themselves. BASE uses the
actual detached worktree, its checked files and shell/environment; shared
dependencies force a new run. Different physical BASE worktrees have different
identity, so the gate conservatively re-executes there. Reuse is available only
when the entire recorded BASE provenance and snapshot really match, never by
matching the command string to a HEAD result.

The runner captures stable before/after snapshots, actual tracked working bytes,
index entries and index digest, file types/modes, deletions and all nonignored
untracked paths, using NUL-safe Git enumeration. Snapshot manifests explicitly
list the known plan workspace exclusion; tracked source is included even there.
The transient plan ledger is ignored through the local `.git/info/exclude` entry
written by `sdd-workspace <plan>`; C6 still reads it by path and hash.
Declared inputs are never excluded. Unresolved links/submodules, unreadable files,
unmerged or unsupported case-colliding paths and Git errors remain unknown.
Content and file-set hashes are accompanied by change metadata and incarnation
witnesses (POSIX inode/ctime, Windows file identity/ChangeTime). A detectable
write and restoration invalidates evidence even when final bytes and mtime match.
Arbitrary hostile writes restoring every observable fact are outside this contract.

`result.json` contains `evidence` with schema, exact request digest, check and
provenance key, source before/after, environment/tools fingerprints, log paths,
sizes/hashes, normalized failure signature, validity, invalidation reasons, `reusable`, `repeat_reason` and
`origin_run_id`. The enclosing C3 record supplies owner, command, timestamps,
duration and actual exit. `result.sha256` seals its exact durable bytes. Mutation
or incomplete evidence yields runner 125, retaining the actual command exit in
JSON. Gate validates request binding, seal and full logs before classification.
The supplied result object must equal the object decoded from those same sealed
bytes. A faithful copy is permitted, but changing its exit or any other field
cannot borrow the original run directory's seal to establish a positive CHECK.
PowerShell decodes both compared objects through its JSON parser so an in-memory
ISO timestamp and PS7's parsed DateTime receive identical canonical formatting.
This representation step happens after the original-byte seal check and retains
comparison of the full result, including the actual exit and evidence bindings.

Reuse searches only `checks/*/result.json` in this plan workspace. Matching
eligible evidence avoids a new command process. A new atomic result binds the
new owner to the physical origin, its result path/hash and original full logs;
the original request/result/logs must remain intact. No reuse chain, global
cache, daemon or dependency inference is introduced. Nonhermetic valid execution
can pass, but cannot be reused. Broken evidence is rerun, never accepted as PASS.
Timeout, mutation and unknown completion go to judgment. Existing missing-tool,
changed-path, failure-signature, shared-dependency and zero-pass safeguards apply
to HEAD/BASE classification. Gate's first two lines and codes 0/1/2/3/4 are stable;
evidence/log paths and repeat/origin reasons follow the summary.
