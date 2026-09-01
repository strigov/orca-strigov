# Spike 0 — результаты (2026-09-01)

Среда: Orca 1.4.193, Codex CLI 0.151.0 → **0.152.0** (обновлён в ходе спайка), `agy` 1.1.22, Claude Code (Fable 5 / Opus 5), мост `codex-chatgpt-web` 4.0.5 → 4.0.7 (лаунчер сам обновился в 14:27).
Run: `run_b3ecea3efaa9`. Координатор — этот Claude-терминал (`term_d7eaf96a…`) в worktree `orca-strigov`.

## Сводка

| # | Проверка | Итог | Детали |
|---|---|---|---|
| 1 | Codex-воркер держит 5-минутный блокирующий `check --wait` | **OK** | `probe-long-wait.md`: `5:00.14`, exit 0, harness не убил. Rolling-окна ≤5 мин безопасны; 9-мин окна с координатора тоже прошли (`check --wait 540000` с keepalive-heartbeat). |
| 2 | `--model gpt-5.6-luna --effort max` переопределяет дефолт `chatgpt-web/pro` из `config.toml` | **OK** | `probe-codex-luna.md`: сессия реально `gpt-5.6-luna` / `max`. Orca передаёт `-m … -c model_reasoning_effort=…`. |
| 3 | Pro через мост из Orca-терминала, tool-calls, ход планирования | **FAIL ×2** | Tool-calls прошли (прочитал фикстуру), но через ~4 мин `turn_token … invalid, expired, or revoked`; retry упал до первой команды. План не написан. Фолбэк-пара сработала. |
| 3b | Фолбэк-планировщик Opus max через `worker-start` | **OK** | `probe-opus-plan.md`, 300 строк, 5 фаз, ~4,5 мин; нашёл 3 неочевидные ловушки, прогнав проверки на целевом интерпретаторе. |
| 4 | Antigravity `gemini-3.7-flash-high --effort high` через Orca | **OK через custom argv** | `worker-start --agent antigravity --model …` отвергается: «does not support launch-time model selection». Рабочий путь: `terminal create --command "agy --model gemini-3.7-flash-high --effort high --dangerously-skip-permissions"` → `tui-idle` → `dispatch --inject`. |
| 5 | Claude `--model fable --effort high` через `worker-start` | **OK, но effort ≠ ожидание** | Модель `claude-fable-5`. Маппинг Claude CLI: `low`=10, `high`=**25**, `max`=max (замерено `claude -p`). Для судейских ролей нужен `--effort max`. |
| 6 | Повторный dispatch в тот же терминал сохраняет тред | **OK (Codex и agy)** | Обе «задачи-воспоминания» вернули `MEMORY_OK` с точными путём и handle без чтения файлов. `--terminal <handle>`/повторный `--inject` = `--resume-task`. |

## Блокеры запуска, которые надо снять в install-скрипте

1. **Codex hooks trust.** Orca ставит 8 хуков в `~/.codex/hooks.json`; Codex TUI показывает «Hooks need review» и блокирует ввод → `worker-start` падает с `agent_prompt_blocked` (3 попытки → задача `failed`, circuit-breaker). `orca terminal send` в заблокированный TUI тоже отвергается. Config-ключ `bypass_hook_trust = true` в `config.toml` **не помогает**. Рабочие варианты: (а) один раз нажать «2. Trust all and continue» в Codex-терминале внутри Orca — доверие персистится в `[hooks.state]`; (б) запускать Codex своим argv с `--dangerously-bypass-hook-trust` через `terminal create` + `dispatch --inject`.
2. **Codex update prompt.** «Update available» тоже блокирует ввод — держать Codex обновлённым (`brew upgrade --cask codex`) или гасить промпт.
3. **Antigravity trust folder.** `agy` спрашивает «Do you trust this folder?» → блок. Лечится заранее: путь в `~/.gemini/antigravity-cli/settings.json → trustedWorkspaces` (родительский `/Users/strigov` в списке НЕ покрывает вложенный путь).
4. **Claude Code trust folder.** Аналогичный диалог, при инжекте Claude вышел в shell. Лечится `~/.claude.json → projects[<path>].hasTrustDialogAccepted = true`.
5. **Circuit-breaker.** После 3 неудачных dispatch задача переходит в `failed`; вернуть — `task-update --id … --status ready`.
6. **`runtime_unavailable` на dispatch** случался дважды (Orca закрывал соединение); лечится точным `--retry-request <id>` из ответа — координатор должен уметь это автоматически.

## Наблюдения для дизайна скилла

- `worker-start` даёт полный lifecycle (`worker-release` закрывает терминал, транскрипт архивируется). `dispatch --inject` в свой терминал — unsupervised: `worker-release` = no-op, терминалы закрывать вручную (`terminal close`). Для Codex с `--dangerously-bypass-hook-trust` и для agy это единственный путь до снятия блокеров 1/3 → скилл должен поддерживать оба пути.
- `worker_done` приходит структурированным: `subject` = verdict-токен, `payload.outcome`, `filesModified`, `reportPath`. Парсинг «line 1» больше не нужен.
- Координатор из Claude Code: `check --wait 540000` работает (Bash timeout 600 с), heartbeat-строки `_keepalive` идут в stdout — парсить только последнюю JSON-строку.
- Pro через мост в текущем состоянии ненадёжен (2/2 падений на turn token + 5/10 ночью на DOM). Держать «мощный» режим как opt-in до стабилизации моста; фолбэк Opus max → Sol max работает и даёт сильный план.
- Fable через `worker-start` стартовал нативно (0 блокеров после trust-фикса) — Claude самый «гладкий» агент в Orca.

## Артефакты

`probe-codex-luna.md`, `probe-antigravity.md`, `probe-claude-fable.md`, `probe-long-wait.md`, `probe-opus-plan.md`. Pro-план отсутствует (задача `task_54844d86a827` — `failed`).
