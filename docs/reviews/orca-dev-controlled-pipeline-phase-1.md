# Ревью: orca-dev-controlled-pipeline — Ф1

Дата: 2026-09-12. Область: политика ролей, жизненного цикла, простоты плана и поставки (C1–C2).

BASE: `d522e2656b55f0a67e28b4a1fc2e3689e7cd3de0`. Итог: принят, `REVIEW_OK / SPEC: OK / QUALITY: OK`; открытых блокирующих замечаний нет.

Проверено четыре обычных primary-раунда, затем один дополнительный целевой primary-проход и один полный control. Последний control нашёл восемь материальных противоречий. После их исправления независимый maintenance-review проверил все восемь, текущий пакет целиком (1701 строка, 19 файлов) и границы изменения (4 файла, 132 строки). Исправления написаны представителями Google и OpenAI; заключительный рецензент относится к Anthropic.

Использовано разрешение AGENTS.md на обычные правки самого репозитория. Это отклонение от обычного цикла явно отражено здесь: четыре раунда и дополнительная проверка не выдаются за прохождение неизменённого стандартного лимита. Лимиты распространяемого протокола сохранены; принятия незакрытых блокеров не было.

## История решений

F2-B1/F2-B2 в названиях замечаний второго ревью соответствуют F1-B8/F1-B5; F3-B1 — F1-B11; F4-B1 — F1-B12. Это номера раундов ревью Ф1, а не последующих фаз реализации.

| ID | Рецензирование | Содержание / принятое изменение | Решение | Состояние |
|---|---|---|---|---|
| F1-B1 | review-primary | Restore UTF-8 BOM in install.ps1 to preserve Windows PowerShell 5.1 parsing; do not change unrelated installer behavior. Verify PS5.1 ParseFile has zero errors and provide the exact read-only command/output for the gate. | ACCEPTED | fixed |
| F1-B2 | review-primary | Replace every documented ineffective -c multi_agent=false with -c features.multi_agent=false in roles.md and recipes. Record verified codex-cli 0.154.0 behavior without changing user configuration. | ACCEPTED | fixed |
| F1-B3 | review-primary | Remove remaining active model/effort assignments outside roles.md at the exact SKILL/recipes/install.ps1 sites listed by primary review; use role references and model/effort placeholders, preserve historical evidence and legitimate agent CLI identifiers. | ACCEPTED | fixed |
| F1-B4 | review-primary | Remove silence/idle/20-minute retry and cascade triggers from roles.md and SKILL.md. Require positive current execution-host exit/failure/recovery evidence and no live or unverifiable writer before redispatch; respect current Orca nextAction semantics. | ACCEPTED | fixed |
| F1-B5 | review-primary | After explicit Pro initial planning, revisions must use роль по roles.md with announced full handoff, then the approved Claude reviewer by complexity; native author context reused thereafter. Remove automatic planning/revision downgrades anywhere in profiles: all default planning/revisions stay роль по roles.md. Any different legacy profile can be explicit user override only, not an availability fallback. This follows the user's exact preference and narrows the reviewer's suggestion to preserve роль по roles.md as an automatic fallback. | ACCEPTED | fixed |
| F1-B6 | review-primary | Document actual worker-retain with expected next action after accepted settlement, and reference it from author/implementer retention rules. Respect actual ownership and release receipts for adopted/operator-created terminals. Align the auto-commit release clause: never replace a retained/user-taken-over/unproven release result with forced terminal close. Our real author release returned retained/user_requested, so receipt handling is material current evidence. | ACCEPTED | fixed |
| F1-B7 | review-primary | Use result.worker.agentTerminalHandle as the current Orca worker-show handle field, with agent_terminal_handle only as explicitly compatible old-receipt fallback. | ACCEPTED | fixed |
| F1-B8 | review-primary | Replace invalid git diff <plan_base>..WORKTREE with git diff <plan_base> for an uncommitted final fix wave. WORKTREE remains only the review-package argument, not a Git ref. | ACCEPTED | fixed |
| F1-B9 | review-primary | Restore jq in the POSIX README requirements because current installer/recipes depend on it; preserve native Windows requirements. | ACCEPTED | fixed |
| F1-B10 | review-primary | Add required top-level verify with concrete repository commands in the plan-writer YAML example and required metadata explanation; per-phase verify may be shown compatibly. Preserve required risk and budget/delivery contracts. | ACCEPTED | fixed |
| Ф1-R1-D1 | review-primary | None | DEFER | deferred |
| Ф1-R1-D2 | review-primary | None | DEFER | deferred |
| Ф1-R1-D3 | review-primary | None | DEFER | deferred |
| Ф1-R1-D4 | review-primary | None | DEFER | deferred |
| Ф1-R1-D5 | review-primary | None | DEFER | deferred |
| Ф1-R1-D6 | review-primary | None | DEFER | deferred |
| Ф1-R1-D7 | review-primary | None | DEFER | deferred |
| Ф1-R1-D8 | review-primary | None | DEFER | deferred |
| Ф1-R1-D9 | review-primary | None | DEFER | deferred |
| Ф1-R1-N1 | review-primary | None | NIT | deferred |
| Ф1-R1-N2 | review-primary | None | NIT | deferred |
| Ф1-R1-N3 | review-primary | None | NIT | deferred |
| Ф1-R1-N4 | review-primary | None | NIT | deferred |
| Ф1-R1-N5 | review-primary | None | NIT | deferred |
| Ф1-R1-N6 | review-primary | None | NIT | deferred |
| F1-B11 | review-primary | Apply F3-B1 from primary r3: malformed required blocker fields trigger one format-correction dispatch with findings unresolved, then protocol blocker/escalation if still deficient. Replace silent DEFER conversions in SKILL220, review-control98, plan-reviewer109/190 and extend SKILL84 to blocker fields required by their own role. Text-only, no new validator/runtime or review loop. | ACCEPTED | fixed |
| Ф1-R3-D1 | review-primary | None | DEFER | deferred |
| Ф1-R3-N1 | review-primary | None | NIT | deferred |
| Ф1-R3-N2 | review-primary | None | NIT | deferred |
| F1-B12 | review-primary | F4-B1: replace only the union-field parenthesis in SKILL.md220 with (as defined by that role's own prompt). Preserve the one-format-correction/unresolved/escalation rule. Do not enumerate or introduce role fields again; role prompts own their schemas. | ACCEPTED | fixed |
| Ф1-R4-D1 | review-primary | None | DEFER | deferred |
| Ф1-R4-N1 | review-primary | None | NIT | deferred |
| CF1-B01 | review-control | Align every retained-author/Mode B instruction with the Pro first-revision exception: fresh plan-reviser per roles with full announced handoff, then reuse that native reviser. Other profiles reuse actual author. Use role labels outside roles.md. | ACCEPTED | fixed |
| CF1-B02 | review-control | Resume must distinguish prepared phase done from verified commit/range. Without commit evidence recover the recorded unfinished verification/review/commit barrier, not redispatch implementation or advance phase; do not auto-commit without accepted reviews. | ACCEPTED | fixed |
| CF1-B03 | review-control | Keep top-level plan in-progress through last phase commit and final-review/delivery verification; set done only after both are accepted, with coherent final metadata commit guidance and resume discovery. | ACCEPTED | fixed |
| CF1-B04 | review-control | Remove universal forced terminal close for Path B. Use actual settled release receipts; retained/external/user_takeover/pending/unknown/no-op remains recorded and open, never inferred disposable. | ACCEPTED | fixed |
| CF1-B05 | review-control | Readiness timeout is unverifiable, not availability failure. Follow actual execution-host evidence and nextAction; no close/retry/cascade from timeout/idle alone; no duplicate unresolved writer. | ACCEPTED | fixed |
| CF1-B06 | review-control | Guarantee a model-agnostic no-delegation boundary in every self-contained worker spec via one mandatory coordinator-injected block and pre-dispatch check (or actual templates). Every Codex worker must have native multi_agent effectively disabled; use verified custom path when Path A cannot ensure it, without user config edits. | ACCEPTED | fixed |
| CF1-B07 | review-control | Qualify every reviewer availability fallback against actual author families of the reviewed unit. Use only already-allowed independent routes or stop with incomplete acceptance; never same-family fallback, no new models/defaults. | ACCEPTED | fixed |
| CF1-B08 | review-control | Resolve all-three loading contradiction: roles.md and recipes once before dispatch; only the current role prompt on demand. | ACCEPTED | fixed |
| F1-M-D1 | maintenance-review | Mode B: optional explicit paths for latest author/review reports in the handoff template. | DEFER | deferred |
| F1-M-D2 | maintenance-review | Prepare next phase in-progress at its actual start rather than before current phase commit. | DEFER | deferred |
| F1-M-N1 | maintenance-review | Prompt Dispatch introductions could say body rather than complete spec; canonical prefix rule already governs. | NIT | informational |
| F1-M-N2 | maintenance-review | Clarify concluding gate/package terminology; current wording repeats approved plan. | NIT | informational |
| F1-M-N3 | maintenance-review | Independence qualifier in legacy profile fallback is redundant but harmless. | NIT | informational |

## Проверка принятого состояния

- Механический gate: 3/3 — `git diff --check`, проверка структуры скилла, разбор install.ps1 настоящим Windows PowerShell 5.1 с ненулевым кодом при ошибках.
- Пакет: SHA256 `8A65C3948A0B74B96368AF67354ACECD5D3B5FD78E02FADD0D6CC9817F54B76F`, 213281 байт. Независимый рецензент прочитал пакет ограниченными частями и сверил 19/19 blob identities с рабочими файлами.
- Независимо проверены наличие и действие флага отключения native multi-agent, ограничения worker-start и отсутствие команд принудительного закрытия retained/external terminal. Самопроверки исполнителя не выдавались за независимый повтор.
- Поздние CF1-B01…B08 получили статус fixed только после независимого заключения; предыдущий control REVIEW_BLOCKING сохранён в истории.

## Отложенное и ограничения

DEFER и NIT в таблице не входили в дополнительные исправления. Изменения runtime, evidence, manifest, state validator и тестовой изоляции установки относятся к следующим утверждённым фазам и не объявлены готовыми в Ф1. Живые lifecycle-наблюдения — отдельные свидетельства, не сертификация ещё не созданных helpers.

Исходные отчёты этой сессии: `.superpowers/sdd/2026-09-12-orca-dev-controlled-pipeline/phase-1-primary-r1.md` … `phase-1-primary-r4.md`, `phase-1-primary-targeted.md`, `phase-1-control-final.md`, `phase-1-astra-fix-report.md`, `phase-1-maintenance-review.md`. Это локальные служебные артефакты; архив выше сохраняет решения без dispatch capabilities.
