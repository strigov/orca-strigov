# Задание: C6 не может подтвердить модель Claude-исполнителя вне свежего Path A

Дата расследования: 2026-09-26. Плагин `orca-strigov` 1.1.0 (репозиторий и кеш
`~/.codex/plugins/cache/personal/orca-strigov/1.1.0` совпадают), Orca 1.4.211,
Claude Code v2.1.282, codex-cli 0.157.0, macOS.

## Кратко

Прогон `run_f27aa24e8f01` (проект Bureau, план `p2-editor-continuation`, фаза Ф1)
остановился на C6 с `UNVERIFIABLE: unknown actual model family`, хотя код
исправлен, gate зелёный, а исполнитель заведомо Claude Opus 5.5.

Сработали две независимые проблемы:

- **A. Свежий Path A для Claude нестабильно доставляет задачу.** Текст задачи
  теряется при старте Claude Code, и ход не начинается.
- **B. У C6 для Claude есть ровно один источник модели: квитанция `worker-start`
  того же Dispatch.** Поэтому оба обходных пути, которые предписывает сам плагин
  (повторное использование терминала и Path B), для Claude непроверяемы по
  построению.

Главная проблема — B: она детерминирована и заблокирует любой цикл исправлений
Claude-исполнителя, даже если A не проявится.

## Материалы

Каталог прогона: `/Volumes/Samsung990/projects-s/Bureau/.superpowers/sdd/p2-editor-continuation/`
(далее `$W`). Журнал координатора (Codex):
`~/.codex/sessions/2026/09/25/rollout-2026-09-25T18-57-08-01a0d86d-2a49-7f12-9832-d5cb9e351eda.jsonl`.

Хронология запусков Claude (время UTC по журналу координатора):

| время | попытка | способ | итог |
|---|---|---|---|
| 12:53 | plan-reviewer | Path A, свежий терминал | задача осталась черновиком в composer; помогло одно `terminal send --enter` |
| 13:12 | Ф1, реализация (`ctx_c035cf6444be`) | Path A, свежий терминал | успех, C6 прошёл (модель из `worker-start`: `opus`) |
| 14:44 | Ф1 fix (`ctx_a5f25bbf2da4`) | Path A, `worker-start --terminal <тот же терминал>` | C6: `missing effective launch model`; с исходной квитанцией: `worker-start identity mismatch` |
| 14:48 | Ф1 fix recovery (`ctx_5d13399ddceb`) | Path A, свежий терминал | `outcome_unknown / turn_start_unobserved`; composer **пуст**, транскрипта нет |
| 14:55 | Ф1 fix retry2 (`ctx_238513ace15f`) | Path A, свежий терминал | то же самое |
| 14:57 | Ф1 fix Path B (`ctx_021d4b1e3eee`) | `terminal create` + `wait-agent-ready` + `dispatch --inject` | работа выполнена; C6: `unknown actual model family` |

Ключевые файлы: `$W/worker-start-phase-f1-*.json`, `$W/worker-show-phase-f1-*.json`,
`$W/protocol-bind-phase-f1-fix-*.txt`, `$W/terminal-create-phase-f1-fix-pathb-r1.json`,
`$W/model-evidence-phase-f1-fix-pathb-r1.json`, `$W/protocol-blocker-phase-f1-fix.json`.

## Проблема A: потеря задачи при свежем Path A для Claude

Факты:

- `worker-start` вернул `ok: true`, `launch.effective.model: "opus"`, но
  `state: outcome_unknown`, `stage: turn_start_unobserved`, `lastError`: «input was
  written and submitted, but claude's turn start could not be verified (up to 30s)».
- `terminal read --screen` через 1–4 минуты: Claude Code запущен
  (`Opus 5.5 with xhigh effort`), в composer только плейсхолдер `Try "..."`.
  Текста задачи нет, поэтому рецепт «retained draft → один Enter» неприменим.
- На plan-reviewer тот же путь оставил текст в composer без отправки (Enter помог).
  Ф1 в 13:12 прошла без вмешательства. Значит, это гонка между вводом, который
  отправляет Orca, и готовностью TUI Claude Code, а не постоянный отказ.
- Для Codex этот класс гонки уже описан в `orca-recipes.md` («Starting MCP
  servers»). Для Claude он не описан.

Гипотеза, которую нужно проверить: Orca отправляет ввод, когда TUI Claude Code
ещё не принимает его. Кандидат на задержку — новый стартовый баннер
«Get to finished work sooner with Opus 5.5…» в v2.1.282. Сама доставка
находится в Orca, вне плагина.

## Проблема B: C6 не принимает модель Claude ни из какого источника, кроме свежего `worker-start`

`bin/lib/protocol_state.py:218`, `actual_model()` (и порт в
`bin/protocol-state.ps1:152–156`) берёт модель только:

1. из `worker-show … projection.provider.model`;
2. из `launch.effective.model` квитанции `worker-start`, у которой
   `(runId, taskId, dispatchId)` совпадает с наблюдаемым Dispatch.

Факты этого прогона:

- **Orca заполняет `provider.model` только для Codex.** У Codex-Dispatch через
  Path B модель есть (`gpt-5.6-sol`, `gpt-6-astra`). У всех проверенных
  Claude-Dispatch, и через Path A, и через Path B, `provider: {"id":"claude","model":null}`.
  Для Claude остаётся только источник 2.
- **Повторное использование терминала** (`worker-start --task <next> --terminal <h>`)
  прямо предписано `orca-recipes.md` §2 для исправлений исполнителя. Но
  `--model/--effort` с `--terminal` не сочетаются, поэтому в новой квитанции
  `launch.requested/effective` = `null`. Результат C6 — `missing effective launch
  model`. Если подставить исходную квитанцию, получаем `worker-start identity
  mismatch`, потому что другой `dispatchId`. **Для Claude рецепт цикла
  исправлений в текущем виде не может пройти C6.**
- **Path B** даёт квитанцию `terminal create`, где нет ни команды, ни модели
  (только `handle`, `incarnationId`, `worktreeId`…), и квитанцию `dispatch`
  без модели. Результат C6 — `unknown actual model family`.
- `roles.md` → `FAMILY_MODELS` содержит псевдонимы (`opus`, `sonnet`, `fable`)
  и старые полные id (`claude-opus-4-6-thinking`…), но не
  `claude-opus-5-5`. Любой новый источник с полным id модели упадёт на
  `family()` даже после исправления `actual_model()`.

Зачем C6 модель: она определяет семейство автора, а от семейства зависит
независимость ревью (`runtime-contracts.md`: вердикт нужен от семейства вне
авторского). Ослаблять проверку до «поверить координатору на слово» нельзя.
Нужен дополнительный **проверяемый** источник.

## Предлагаемое решение

### B1. Повторное использование терминала: цепочка запусков (обязательно)

Разрешить C6 выводить модель повторно использованного терминала из исходной
квитанции запуска этого же терминала:

- В наблюдение `bind-dispatch` добавить необязательную ссылку
  `observation.origin_start` на квитанцию `worker-start`, которая **создала**
  терминал (path + sha256, как у `start`).
- C6 принимает её, только если выполнено всё:
  - текущая квитанция `worker-start` успешна, её `(runId, taskId, dispatchId)`
    совпадает с наблюдаемым Dispatch, `launch.effective` пуст (режим `--terminal`);
  - `worker.agentTerminalHandle` текущего `worker-show` равен терминалу исходного
    запуска (из исходного `worker-show` / `effects[kind=terminal]`);
  - процесс не перезапускался: `incarnationId` терминала совпадает (если Orca
    его отдаёт; иначе найти равноценное доказательство непрерывности и описать
    его в `runtime-contracts.md`);
  - у исходной квитанции тот же `runId`, `ok: true` и непустой
    `launch.effective.model`; агент тот же (`claude`).
- Модель = `origin_start.launch.effective.model`. Если есть и `provider.model`,
  и origin, и они расходятся, результат `conflicting actual model facts`.
- Задокументировать в `runtime-contracts.md` (C6) и в `orca-recipes.md` §2
  (Reuse): координатор обязан сохранить и передать `origin_start`.

### B2. Path B для Claude: доказательство из транскрипта Claude Code (обязательно)

Независимый от координатора источник — журнал сессии Claude Code
`~/.claude/projects/<slug>/<session-id>.jsonl`. У каждого ответа там есть
`message.model`, а первая пользовательская реплика содержит преамбулу Orca с
`dispatchId`/`taskId`. Именно так модель установил координатор в
`$W/model-evidence-phase-f1-fix-pathb-r1.json` (128 ответов `claude-opus-5-5`).

- Ввести вид доказательства `observation.model_evidence` с полями
  `{kind: "claude-transcript", path, sha256}` и добавить скрипт, который его
  строит (например, `protocol-state claude-model-evidence --dispatch <id>`
  или отдельный `bin/claude-model-evidence` с `.ps1`-портом).
- C6 принимает его, только если выполнено всё:
  - `provider.id == "claude"`, `provider.model` пуст, квитанции `start` нет;
  - файл существует, sha256 совпадает;
  - в транскрипте есть пользовательская запись с преамбулой Orca, где
    `dispatchId` и `taskId` точно совпадают с наблюдаемым Dispatch. Это
    привязка транскрипта к Dispatch;
  - все ответы **после** этой записи имеют ровно одно значение `message.model`,
    непустое. Разные модели → `conflicting actual model facts`;
  - `cwd` всех записей лежит внутри worktree Dispatch. Точного совпадения не
    требовать: агент переходит в подкаталоги (в эталонном транскрипте есть
    `Bureau`, `Bureau/apps/desktop`, `Bureau/.superpowers/...`).
- Поиск файла: по `cwd` worktree вычислить `<slug>`, перебрать `*.jsonl`,
  изменённые после создания Dispatch, и найти тот, где есть преамбула с этим
  `dispatchId`. Несколько кандидатов или ни одного → `UNVERIFIABLE` с понятной
  причиной.
- Возможное усиление (решить по результатам исследования): запускать
  Path B-терминал Claude с явным `--session-id <uuid>` и хранить uuid в
  материалах прогона, тогда поиск файла становится однозначным.

### B3. Семейство по полному id модели (обязательно)

`family()` должна принимать и полные id Claude. Рекомендация: оставить явный
`FAMILY_MODELS` для псевдонимов и добавить правило префикса
`claude-` → `Anthropic` для id из транскрипта. Иначе каждый выпуск модели будет
ломать C6. Если выберете только явные записи, добавьте `claude-opus-5-5`,
`claude-sonnet-5`, `claude-fable-5-1`, `claude-haiku-4-5-*` и тест, который
падает на неизвестном `claude-*`, с понятным сообщением.

### A. Доставка задачи при свежем Path A (исследовать, затем решить)

1. Воспроизвести: 5–10 раз `worker-start --agent claude --model opus` на
   тривиальной задаче. Фиксировать `stage`, экран через 5/15/30 с, наличие
   транскрипта. Записать в `docs/smoke-runs.md`.
2. Если гонка подтверждается:
   - в `orca-recipes.md` §2 описать случай «composer пуст, транскрипта нет»:
     его нельзя путать с retained draft, а безопасный путь восстановления —
     `worker-stop` → свежий Path B с `wait-agent-ready <h> claude` (он уже
     поддерживает маркер `Claude Code`). Это рабочий путь только после B2;
   - для ролей Claude, где нужна надёжность, рассмотреть Path B по умолчанию
     (как уже сделано для Codex), раз B2 даёт ему проверяемую модель;
   - подготовить краткий отчёт для апстрима Orca (гонка ввода с TUI
     Claude Code v2.1.282; `turn_start_unobserved` при пустом composer).
     Отправку согласовать с пользователем.
3. Проверить, что `wait-agent-ready … claude` не срабатывает раньше времени на
   баннере при ещё не готовом composer. Маркер `Claude Code` появляется в
   первом кадре. Если срабатывает раньше, ждать признак composer (`❯`) плюс
   повторный `tui-idle`.

## Ограничения

- Нельзя ослаблять C6 до принятия модели со слов координатора, из argv, который
  сохранил сам координатор, или из комментариев worktree/сообщений Run.
- Нельзя менять неизменяемые квитанции Orca и уже записанные артефакты прогона.
- Каждое изменение `protocol_state.py` повторить в `bin/protocol-state.ps1`
  (паритет POSIX/PowerShell обязателен по `AGENTS.md`/`runtime-platforms.md`).
- Пользовательскую конфигурацию Claude/Codex не править.

## Критерии приёмки

1. Тесты в `tests/test_protocol_state.py`, положительные и отрицательные:
   - B1: успешная цепочка; другой handle; другой `incarnationId`; другой
     `runId`; пустая модель в origin; конфликт с `provider.model`;
   - B2: успешная привязка; неверный sha256; нет преамбулы с этим `dispatchId`;
     две разные модели после преамбулы; `cwd` вне worktree; несколько кандидатов;
   - B3: `claude-opus-5-5` → `Anthropic`; неизвестный не-Claude id → ошибка.
2. Те же сценарии проходят через `protocol-state.ps1`, если в репозитории
   есть механизм паритетных тестов. Если нет, это явно указано в отчёте.
3. Регрессия на реальных артефактах: для `$W` с новым `model_evidence` по
   транскрипту `f2d51ece-16c4-48ee-ae17-b92662095d86.jsonl` проверка
   `bind-dispatch` Dispatch `ctx_021d4b1e3eee` возвращает `VALID`, семейство
   `Anthropic`. Сами артефакты в `$W` не менять: работать с копией.
4. Обновлены `runtime-contracts.md` (C6: новые источники модели и порядок
   приоритета), `orca-recipes.md` (§2 Reuse, Path B для Claude, случай пустого
   composer), `roles.md` (правило семейства).
5. Отчёт по проблеме A: результаты воспроизведения и принятое решение.

## После исправления: разблокировать прогон Bureau

Для `run_f27aa24e8f01` (фаза Ф1, Dispatch `ctx_021d4b1e3eee`) повторить
`bind-dispatch` с новым `model_evidence`, затем продолжить обычный цикл
`orca-dev`: повторное ревью Ф1 (семейство вне Anthropic), коммит, Ф2. Изменения
Ф1 лежат в индексе ветки `feat/p2-editor` проекта Bureau без коммита. Не
трогать их до повторного ревью.
