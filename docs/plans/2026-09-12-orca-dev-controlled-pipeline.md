---
slug: orca-dev-controlled-pipeline
created: 2026-09-12
status: in-progress
protocol_version: 2
plan_base: 16df3ef0f2cbbcdab8e091cb473ab96ffb3577d3
orca_run: run_8930e295fe81
phases:
  - id: Ф1
    base: d522e2656b55f0a67e28b4a1fc2e3689e7cd3de0
    scope: "Согласованная политика ролей, жизненного цикла, простоты плана и поставки"
    status: done
    commits: 'd522e2656b55f0a67e28b4a1fc2e3689e7cd3de0..9f2e95b8a6abb489a02cce1a698c3aa2e07b7934'
    risk: DATA_LOSS
    verify:
      - 'git diff --check'
      - 'python -X utf8 -B C:/Users/strig/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/orca-dev'
      - powershell.exe -NoProfile -Command '$errs = $null; $toks = $null; [void][System.Management.Automation.Language.Parser]::ParseFile((Join-Path (Get-Location).Path "install.ps1"), [ref]$toks, [ref]$errs); if ($errs.Count -gt 0) { $errs | ForEach-Object { [Console]::Error.WriteLine($_) }; exit 1 } else { [Console]::WriteLine("ZERO_ERRORS"); exit 0 }'
  - id: Ф2
    base: 9f2e95b8a6abb489a02cce1a698c3aa2e07b7934
    scope: "Один владелец длительной команды, полные логи, остановка и общая блокировка ресурса"
    status: done
    commits: '9f2e95b8a6abb489a02cce1a698c3aa2e07b7934..d85f09dae366ae5b254290e8613e4fbee883fab0'
    risk: DATA_LOSS
    verify:
      - 'python -B -m unittest discover -s tests -p test_runner.py'
      - 'git diff --check'
  - id: Ф3
    base: d85f09dae366ae5b254290e8613e4fbee883fab0
    scope: "Доказательства проверок для точного снимка и полный манифест пакета ревью"
    status: done
    commits: 'd85f09dae366ae5b254290e8613e4fbee883fab0..a3e4dc854474243cf77de9fbd85e2e4605ff315a'
    risk: REGRESSION
    verify:
      - 'python -B -m unittest discover -s tests -p test_verification.py'
      - 'python -B -m unittest discover -s tests -p test_review_package.py'
      - 'git diff --check'
  - id: Ф4
    base: a3e4dc854474243cf77de9fbd85e2e4605ff315a
    scope: "Детерминированная валидация отчётов, переходов, независимости и возобновления"
    status: done
    commits: 'a3e4dc854474243cf77de9fbd85e2e4605ff315a..21d544b211333888cf8fc2921dccb2aa6fbccf9b'
    risk: REGRESSION
    verify:
      - {"id":"protocol-state","command":"python -B -m unittest discover -s tests -p test_protocol_state.py","checkpoint":"integration","timeout_seconds":175,"hermetic":false,"independent_replay":true}
      - {"id":"diff-check","command":"git diff --check","checkpoint":"integration","timeout_seconds":10,"hermetic":false,"independent_replay":true}
  - id: Ф5
    base: 21d544b211333888cf8fc2921dccb2aa6fbccf9b
    scope: "Безопасная установка, совместимость и ограниченная сквозная приёмка"
    status: done
    commits: '21d544b211333888cf8fc2921dccb2aa6fbccf9b..'
    risk: DATA_LOSS
    verify:
      - {"id":"final-suite","command":"python -B -m unittest discover -s tests -p 'test_*.py' -v -f","checkpoint":"final","timeout_seconds":1050,"environment":["ORCA_TEST_SHELL","ORCA_DEV_HOME","ORCA_TEST_ARTIFACTS",{"tool":"python","version_args":["--version"]}],"hermetic":false,"independent_replay":true}
      - {"id":"skill-validate","command":"python -X utf8 -B C:/Users/strig/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/orca-dev","checkpoint":"integration","timeout_seconds":20,"hermetic":false,"independent_replay":true}
      - {"id":"diff-check","command":"git diff --check","checkpoint":"integration","timeout_seconds":10,"hermetic":false,"independent_replay":true}
verify:
  - {"id":"final-suite","command":"python -B -m unittest discover -s tests -p 'test_*.py' -v -f","checkpoint":"final","timeout_seconds":1050,"environment":["ORCA_TEST_SHELL","ORCA_DEV_HOME","ORCA_TEST_ARTIFACTS",{"tool":"python","version_args":["--version"]}],"hermetic":false,"independent_replay":true}
  - {"id":"skill-validate","command":"python -X utf8 -B C:/Users/strig/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/orca-dev","checkpoint":"integration","timeout_seconds":20,"hermetic":false,"independent_replay":true}
  - {"id":"diff-check","command":"git diff --check","checkpoint":"integration","timeout_seconds":10,"hermetic":false,"independent_replay":true}
---

## Goal

Обновить orca-dev так, чтобы он доводил утверждённый пользовательский сценарий до проверяемой поставки, сохранял контекст автора, ограничивал повторную работу и не принимал неподтверждённый результат. Orca остаётся единственным уровнем делегирования; существующие роли, ledger и циклы ревью сохраняются.

Основание — полная авторизация обновления, завершённая сообщением «Отлично, вполняй», включая предшествующие решения о планировании, назначениях ролей и отдельной проверке простоты. Исследована ветка `codex/orca-dev-controlled-pipeline`, исходный commit `16df3ef0f2cbbcdab8e091cb473ab96ffb3577d3`. Этот SHA — исследовательская точка отсчёта; обязательный `plan_base` координатор записывает отдельно по контракту C2.

## Acceptance criteria

| ID | Пользовательский результат | Поставка / зависимости | Приёмка | Доказательство |
|---|---|---|---|---|
| A1 | Утверждённая политика ролей применяется ко всему циклу плана | Матрица ролей; согласованные skill, recipes и prompts | Начальное планирование и правки используют утверждённый нативный профиль; контекст автора сохраняется; обычное и сложное ревью выбираются явно; bridge включается только явным выбором | Независимое ревью матрицы, проверка maintained-файлов, фактические launch receipts при доступности |
| A2 | План содержит достаточное решение без необоснованной сложности | Шаблоны writer/reviewer и тот же цикл до четырёх раундов | Отдельный `SIMPLICITY`-вердикт; существенное замечание содержит конкретную цену/риск и более простой вариант, сохраняющий необходимые свойства; вкусовая рекомендация не блокирует | Принятый отчёт plan-reviewer и сценарии валидатора формата |
| A3 | Длительная проверка имеет одного владельца и управляемое завершение | Два входа runner, оба verify-gate, существующий workspace | Полные логи, run id, команда/cwd, время/exit status; диагностический сигнал при отсутствии прогресса; отмена/deadline не оставляют управляемых потомков; две worktree сериализуют один объявленный тяжёлый ресурс | Реальные короткие процессы, журналы runner, проверка потомков и интервалов владения lock на обеих платформах |
| A4 | Переиспользование результата не выдаёт чужой или устаревший PASS | Снимок файлов, описанные входы/окружение, машинное evidence | Изменение tracked/untracked файла, команды, входа или значимого окружения исключает reuse; изменение входного снимка во время теста исключает зелёный gate; обязательный независимый replay выполняется | Негативные snapshot/evidence-тесты, счётчик фактических запусков, HEAD/BASE provenance |
| A5 | Рецензент проверяет весь актуальный артефакт независимо от его авторов | Манифест review-package, привязка отчёта, provenance и интеграционные контракты | Пропущенная/устаревшая часть, неизвестный автор или непокрытый контракт не допускают приёмку; смешанное авторство не маскируется свежим контекстом | Манифест, hashes и coverage в отчётах; сценарии смешанного авторства и неизменности настоящего Git index |
| A6 | Возобновление не создаёт второго писателя и не перескакивает через неудачный commit | Компактный state/resume, реальные Orca receipts и Git-факты | Дубликат Delivery не повторяет действие; поздний Dispatch не завершает актуальный; неполный отчёт остаётся unresolved; после skipped/failed commit следующая фаза не начинается | Детерминированные последовательности событий, в том числе сбой между commit и записью resume |
| A7 | Установленная версия работает в ожидаемом сценарии и честно останавливается | Установка из этого checkout, зависимости, документы и ограниченная сквозная проверка | Native Windows и Bash выполняют договорные сценарии; stale link/старое окружение диагностируются; отсутствие обязательной возможности или исчерпание бюджета даёт partial/blocked, а не done | Отчёт поставки со ссылками на логи, среду, проверки и оставшиеся ограничения |

## Non-goals / deferred

- Новый диспетчер задач, daemon, общий scheduler, mandatory service, dashboard, платформа квот или попытка предсказать стоимость по названию модели.
- Переписывание Orca, его lifecycle API, авторизации или провайдерских CLI; скрытое нативное делегирование внутри worker.
- Fine-grained dependency cache, переносимость evidence между машинами по умолчанию, кэш непроверяемых сетевых/внешних входов, криптографическая аттестация недоверенного исполнителя.
- Автоматическое расширение бюджета, снижение требований безопасности ради простоты, дополнительный независимый цикл simplicity-review.
- Изменение исторических эмпирических отчётов, завершённых планов, `spikes/fixture` или проекта из исходной длительной сессии. Fixture с `fcntl` не является приёмкой native Windows для новых скриптов.
- Массовая миграция старых планов и пользовательской конфигурации, отдельный legacy-upgrader; новые runtime-зависимости Windows на Python, Bash, jq или сторонний YAML-модуль.

## Global Constraints

- Все модельные роли назначает координатор через Orca. Worker не создаёт subagents/workers; ограничение действует и на нативные возможности его CLI.
- Единственный maintained-источник имён/идентификаторов моделей и назначенных им effort — `skills/orca-dev/roles.md`. В остальных протокольных файлах используются роли, параметры-заполнители и ссылки на матрицу. Исторические отчёты сохраняются без изменений.
- Точные пользовательские назначения для правки матрицы берутся из полной авторизации в dispatch Ф1; поздняя фраза согласия сама по себе не заменяет предшествующие решения. При отсутствии этой части задания — `NEEDS_CONTEXT`, без угадывания значений.
- Утверждённое качество начального планирования и каждой правки не понижается автоматически. Экспериментальное control-review и трудный implementer/diagnosis-маршрут выбираются явно с причиной; остальные defaults не меняются попутно.
- Первичная эскалация ревью — раунд 4; `SECURITY`/`DATA_LOSS` требуют немедленной риск-эскалации. Лимиты: plan-review 4, fused-review 4, final-review 2, последовательные gate-fix 2, format-correction 1 на дефектный отчёт.
- Автор сохраняется до принятия и commit плана, implementer — до принятия и commit фазы. Новое содержательное ревью получает свежий контекст; исправление только формата отчёта не является новым раундом ревью.
- Поддерживаются Bash 3.2+ с уже существующей зависимостью python3 и native Windows PowerShell 5.1 / PowerShell 7 с Git. Python разрешён для тестовой оснастки Windows, но не становится зависимостью её рабочих `.ps1` entry points.
- Существующие позиционные вызовы workspace, review-package и verify-gate сохраняются; новые режимы добавляются явно. Legacy-план без нового metadata не получает автоматического разрешения на reuse.
- Семантическая работа Step 2.5 переходит существующему plan-reviewer; координатор проверяет структуру, обязательные поля и идентификаторы контрактов.
- Не более двух рабочих деревьев; один живой writer на дерево. В этом плане `parallel_group` нет: фазы зависят друг от друга и последовательно меняют общие файлы.
- Проверки не меняют пользовательскую конфигурацию. На Windows фоновые helpers скрыты; операции с путями используют literal paths и проверенный каталог владения; cleanup не следует по junction/symlink к чужим данным.
- Бюджет, пропуски, предупреждения и ограничения не меняют значение доказанного результата. Обязательная, но недоступная проверка не считается пройденной.

## Files

Ниже перечислены точные области владения. Один и тот же файл в разных фазах означает последовательное развитие, а не параллельную работу. План/frontmatter и commits ведёт координатор; implementer не редактирует сам этот план без отдельной авторизации.

| Фаза | Файлы | Ответственность |
|---|---|---|
| Ф1 | `skills/orca-dev/roles.md` | Полная согласованная матрица, профили, усилия, substitutions и явные экспериментальные маршруты |
| Ф1 | `skills/orca-dev/SKILL.md`, `skills/orca-dev/orca-recipes.md` | Исправить YAML description навыка; разрешить противоречия, on-demand prompts, lifecycle, reviewer-owned Step 2.5, остановку и commit barrier |
| Ф1 | `skills/orca-dev/prompts/plan-writer-prompt.md`, `skills/orca-dev/prompts/plan-reviewer-prompt.md` | Контекст автора, поставка/зависимости/приёмка/бюджет, simplicity и семантическая проверка |
| Ф1 | `skills/orca-dev/prompts/implementer-prompt.md`, `skills/orca-dev/prompts/frontend-implementer-prompt.md`, `skills/orca-dev/prompts/verification-gate-prompt.md`, `skills/orca-dev/prompts/review-primary-prompt.md`, `skills/orca-dev/prompts/review-control-prompt.md`, `skills/orca-dev/prompts/final-review-prompt.md`, `skills/orca-dev/prompts/diagnosis-prompt.md`, `skills/orca-dev/prompts/synthesize-review-prompt.md`, `skills/orca-dev/prompts/quickfix-prompt.md` | Удалить дубли назначений; согласовать затронутые политики и reporting без создания новых ролей |
| Ф1 | `README.md`, `docs/install-windows.md`, `install.sh`, `install.ps1` | Ролевые описания вместо модельных литералов; bridge как opt-in; в installers только относящиеся к этой политике сообщения/проверки |
| Ф2 | **Create** `bin/run-check`, `bin/lib/run_check.py`, `bin/run-check.ps1` | Один конечный supervisor на команду; Bash-вход использует Python stdlib; Windows реализован нативно |
| Ф2 | `bin/verify-gate`, `bin/verify-gate.ps1` | Запуск HEAD и BASE через runner вместо накопления полного вывода в памяти |
| Ф2 | **Create** `skills/orca-dev/runtime-contracts.md` | Компактный контракт runner; дальнейшие фазы расширяют этот же документ |
| Ф2 | `skills/orca-dev/orca-recipes.md`, `skills/orca-dev/prompts/implementer-prompt.md`, `skills/orca-dev/prompts/frontend-implementer-prompt.md`, `skills/orca-dev/prompts/verification-gate-prompt.md`, `skills/orca-dev/prompts/diagnosis-prompt.md` | Практическое ожидание, владение процессом, диагностика и ограниченные команды |
| Ф2 | **Create** `tests/support.py`, `tests/test_runner.py` | Небольшая stdlib-оснастка временных репозиториев/процессов, общая фикстура двух worktree и реальные runner-тесты |
| Ф3 | **Create** `bin/lib/verification.py`, `bin/lib/verification.ps1` | Общие для entry points своей платформы parsing, snapshot, provenance и проверка evidence |
| Ф3 | `bin/run-check`, `bin/lib/run_check.py`, `bin/run-check.ps1`, `bin/verify-gate`, `bin/verify-gate.ps1` | Машинное evidence, выбор checkpoint и консервативный reuse |
| Ф3 | `bin/review-package`, `bin/review-package.ps1` | Манифест, ограниченные части, полнота и snapshot без изменения реального index |
| Ф3 | `skills/orca-dev/runtime-contracts.md`, `skills/orca-dev/SKILL.md`, `skills/orca-dev/orca-recipes.md` | Контракты C4–C5, действия gate/package и staging перед заморозкой артефакта |
| Ф3 | `skills/orca-dev/prompts/plan-writer-prompt.md`, `skills/orca-dev/prompts/implementer-prompt.md`, `skills/orca-dev/prompts/frontend-implementer-prompt.md`, `skills/orca-dev/prompts/verification-gate-prompt.md`, `skills/orca-dev/prompts/review-primary-prompt.md`, `skills/orca-dev/prompts/review-control-prompt.md`, `skills/orca-dev/prompts/final-review-prompt.md` | Описанные проверки, evidence вместо текстового PASS, полный охват пакета |
| Ф3 | **Create** `tests/test_verification.py`, `tests/test_review_package.py`; Modify `tests/support.py`, `tests/test_runner.py` | Snapshot, legacy gate safeguards, BASE reuse, package и регрессия runner |
| Ф4 | **Create** `bin/protocol-state`, `bin/lib/protocol_state.py`, `bin/protocol-state.ps1` | Проверка одного предлагаемого действия/отчёта и компактный resume, без dispatch/scheduler |
| Ф4 | `skills/orca-dev/SKILL.md`, `skills/orca-dev/roles.md`, `skills/orca-dev/orca-recipes.md`, `skills/orca-dev/runtime-contracts.md` | Применение валидатора, provenance смешанной ветки и commit-gated переходы |
| Ф4 | Все 11 точных `skills/orca-dev/prompts/*-prompt.md`, перечисленные для Ф1 | Ссылка на единственное определение BINDING в runtime-contracts; только роль-специфические поля; корректировка формата одним Dispatch |
| Ф4 | **Create** `tests/test_protocol_state.py`; Modify `tests/support.py` | Ограниченные симуляции Orca/протокола и проверка реальных Git-фактов на fixtures |
| Ф5 | `install.sh`, `install.ps1`, `README.md`, `docs/install-windows.md` | Изоляция установки в тестах, stale links/env, актуальные entry points/зависимости и совместимость форматов |
| Ф5 | `skills/orca-dev/SKILL.md`, `skills/orca-dev/orca-recipes.md` | Только окончательные пути, bootstrap/проверка установки и устранение выявленного дрейфа интеграции |
| Ф5 | **Create** `tests/test_install.py`, `tests/test_delivery.py`, `docs/controlled-pipeline-validation.md`; Modify `tests/support.py` | Приёмка пользовательского сценария и короткий воспроизводимый отчёт |
| Ф5 | Modify `bin/lib/verification.ps1`, `tests/test_verification.py`, `bin/run-check.ps1`, `tests/test_runner.py`; `tests/support.py` из строки выше | Принятые интеграционные исправления: канонический JSON null, конечные пакеты verification CLI, совместимое чтение и атомарная публикация Windows JSON, детерминированные проверки DELETE sharing, временной блокировки и постоянного отказа |

`bin/sdd-workspace`, `bin/sdd-workspace.ps1`, `bin/wait-agent-ready` и `.ps1` изучены и переиспользуются; их изменение для данного решения не требуется. Не создавать второй механизм workspace или готовности worker.

## Contracts

### C1 — роли, автор плана и simplicity

1. В `roles.md` применить **все** утверждённые назначения из полномочного задания: `coordinator`, одинаковый сильный нативный профиль `plan-writer`/`plan-reviser` на всех итерациях, обычный/сложный `plan-reviewer`, effort всей используемой усиленной линии review/diagnosis, оставшиеся активные reasoning/control substitutions, явный bridge opt-in и экспериментальные choices. Сохранить усилия заменяемых активных назначений и остальные defaults. Существующий reasoning-escalation маршрут `implementer` остаётся маршрутом по умолчанию с утверждённой заменой активного назначения и сохранением прежнего effort; отдельный трудный implementer/diagnosis-маршрут выбирается явно с обоснованием и не является ни дополнительной обязательной ступенью каскада, ни автоматической заменой этого default. Общий запрет «низкого» effort у семейства не должен противоречить конкретному пользовательскому выбору. Запрет неразрешённого режима повышенного автоматического делегирования сохраняется.
2. Ревизия возвращается автору плана. Если его агент действительно потерян, создаётся замена того же разрешённого профиля с полным планом, ledger и последним отчётом; потеря контекста фиксируется. `launch.requested` не доказательство `launch.effective`; неизвестный effective-параметр не додумывается.
3. Обычный и сложный план отличаются выбором рецензента, а не снижением качества автора. Сложность определяется до ревью по связанным контрактам, рискам и неопределённости. Эскалация с объяснением допустима; произвольная смена многих defaults — нет.
4. Тот же независимый `plan-reviewer` выполняет requirements/semantic checks и отдельную обязательную секцию `## Simplicity`, с `SIMPLICITY: OK | CHANGES_REQUESTED`. Это единый словарь для плана, будущих prompts и валидатора. Она проверяет неоправданную универсальность, функции «на будущее», дублирование имеющихся средств, лишние компоненты, состояния, фазы, агенты и тесты.
5. Существенный simplicity-blocker содержит `unnecessary_cost_or_risk`, `simpler_alternative`, `preserved_requirements`, ссылки на точные места плана и обычные class/materiality. Предложение не может убирать обязательную корректность, безопасность, воспроизводимость или наблюдаемую приёмку. Предпочтение иной архитектуры без текущей существенной цены — advisory. Общий `APPROVED` невозможен при `SIMPLICITY: CHANGES_REQUESTED`; отдельного цикла или дополнительного рецензента не возникает.

### C2 — lifecycle, база и commit barrier

- При старте читать `orca skills get orchestration` той версией executable, которой выполняется Run. На исследованной машине CLI — `1.4.199`; прочитаны kernel, `references/coordinator-loop.md`, `references/recovery-and-cleanup.md` и справка `terminal wait`. Старые наблюдения `1.4.193` не являются текущей спецификацией.
- `worker-start` с `ready/input_accepted` подтверждает принятие ввода, а не начало работы над заданием. Подтверждение — положительный `turn_started` там, где текущий receipt его поддерживает, либо новая запись provider transcript текущего задания через `worker-read --dispatch`. В этом Run после такого receipt полный текст задания остался черновиком: координатор доказал это через `terminal read --screen`, послал только Enter один раз, затем подтвердил работу transcript-записью. Этот узкий recovery применяется только при подтверждённом сохранённом draft в том же terminal/Dispatch: `orca terminal send --terminal <handle> --enter --json`, без повторного текста и без нового Dispatch. Отсутствие transcript или тишина сами по себе не разрешают повторный Enter/пересылку; после однократной отправки проверяется фактическое начало работы. Использовать существующие инструкции запуска Ф1, не изобретать readiness API и не менять `bin/wait-agent-ready`.
- Реальные `worker_done`/heartbeat/ask берутся из live preamble, с обоими Task/Dispatch IDs. Worker сообщает итог ровно один раз и после него бездействует. Неполный отчёт после принятого settlement исправляется **новым** format-correction Dispatch, а не вторым worker_done старого Dispatch.
- Delivery обрабатывается целиком до ack. Settled terminal получает reuse, retention или release. Требование пользователя сохранить автора/implementer до принятия и commit является явным основанием retention; оно записывается вместе с ожидаемым следующим действием. После завершения этой причины применяется актуальный lifecycle, а не `terminal close` вместо release.
- `unverifiable`, timeout, пустой wait и отсутствие heartbeat не доказывают смерть агента. Для retry/stop необходимы положительные данные текущего execution host и recovery receipt. Состояния `user_takeover`, external/pre-existing terminal, `release_pending` и `release_unknown` сохраняются и обрабатываются по receipt; принудительного close нет. После трёх пустых wait применяется предусмотренная Orca проверка fleet/nextAction, а не бесконечный слепой опрос.
- `plan_base` — полный SHA существующего commit **непосредственно перед первым commit утверждённого плана**. Так его можно записать без самоссылочного commit; финальный diff всегда `plan_base..HEAD` либо `plan_base..WORKTREE` для разрешённой fix-волны. `phase.base` также полный SHA перед началом фазы. HEAD~1 и пересчитанный merge-base не заменяют записанную базу. Для legacy-плана единственный fallback — явно восстановленная и проверенная по истории база; её отсутствие блокирует финальную приёмку.
- Принятое содержимое ещё не равно завершённой фазе: до положительного commit receipt состояние `awaiting_commit`, следующая фаза не стартует. Failed/skipped commit сохраняет этот барьер. После crash commit сверяется с Git, повторный commit по прежнему событию не создаётся. `done` в frontmatter без соответствующего подтверждённого commit не позволяет пропустить фазу.
- Координатор готовит необходимые изменения frontmatter **до** заключительного gate/package для commit, чтобы они входили в принимаемый снимок; подготовленный `done` до commit является намерением, проверяемым через барьер. Любое изменение после gate, включая hook, требует проверки нового снимка и актуализации evidence/package. Не менять tracked metadata незаметно после приёмки.
- Все фазы могут быть committed, но общий plan `done` допустим только после final-review и обязательной проверки поставки. Критерий полного завершения не достигается одним последним фазовым commit.

### C3 — небольшой runner и ресурс

Новые равнозначные entry points: `bin/run-check` и `bin/run-check.ps1`. Минимальные операции: `run SPEC_JSON` (блокирующий запуск), `wait RUN_DIR [WAIT_SECONDS]` (ожидание завершения/нового диагностического состояния), `cancel RUN_DIR OWNER_JSON` (запрос владельца). `run` остаётся владельцем и возвращается только при exit/interruption; no-progress обновляет диагностический status, не завершает `run` и не передаёт владение. При запуске в отдельном command terminal тот же worker может прочитать переход через `wait`; для блокирующего gate диагностика сохраняется на диске и включается в итог после завершения. Нулевой wait даёт текущий снимок статуса; отдельный daemon/status-сервис не нужен.

`SPEC_JSON` — UTF-8 JSON с `schema_version: 1`, уникальным `run_id`, `owner`, `cwd`, `command`, `shell`, `run_dir`, `timeout_seconds`, `cancel_grace_seconds`, `no_progress_seconds`, необязательными `progress_file` и `resource_key`. `owner` — либо `{kind: "orca", orca_run_id, task_id, dispatch_id, terminal_handle}`, либо `{kind: "local", id}` для standalone/test. Capability не сохраняется в specs/logs. JSON как файл сохраняет точный многострочный текст команды, кавычки и Unicode.

- `run_dir` создаётся эксклюзивно под существующим plan workspace: `checks/<run_id>/`. Повторный `run` с тем же id возвращает существующее состояние либо ошибку несовпадения spec и **не** стартует второй процесс. Запись владельца связывает run с PID и process incarnation/start identity; один PID после переиспользования недостаточен.
- На диске сохраняются `request.json`, полные `stdout.log` и `stderr.log`, атомарный `status.json`, затем `result.json`. Потоки сбрасываются по мере получения, не удерживаются целиком в памяти. Межпоточный порядок не объявляется точным. Краткий вывод содержит пути и ограниченный tail.
- Результат содержит timestamps, duration, исходный exit code либо null при отсутствии подтверждённого exit, причину завершения/ошибки cleanup и состояние полноты логов. Состояния исполнения минимальны: waiting-resource / running / exited / interrupted / unknown; stalled — диагностический признак, не доказательство выхода.
- Stdin дочерней команды закрыт. Сохраняется семантика `bash -c` и child PowerShell для прежних gate-команд, включая настоящий ненулевой native exit и ошибки PowerShell. Успех wrapper не подменяет exit команды.
- POSIX supervisor владеет отдельной process group; Windows supervisor владеет деревом потомков через штатный механизм ОС с проверяемым завершением, например Job Object. Windows helpers не открывают видимые окна. Тайм-аут, cancellation и смерть supervisor не должны оставлять незамеченное живое дерево; если завершение доказать нельзя, result — unknown/interrupted, lock не передаётся как свободный.
- Hard deadline задан явно, включает ожидание ресурса и имеет фиксированную политику: запрос остановки, grace, принудительное завершение **своего** дерева, проверка cleanup и сохранение логов. Legacy-вызов без политики не получает скрытого тайм-аута: null записывается явно; новые дорогие проверки обязаны иметь конечный deadline в плане.
- Значимый прогресс берётся из необязательного файла счётчика/стадии. Если его нет, рост лога — только `output_activity`, существование PID — только liveness, meaningful progress — unknown. По `no_progress_seconds` создаётся один диагностический переход до следующего изменения/решения; живой процесс сам по этому порогу не убивается.
- Опрос ОС/файла внутри supervisor/wait не вызывает модель. Worker ждёт в блокирующей shell-команде; если harness требует отдельного command terminal, он запускает там этот же runner и пользуется поддерживаемым `orca terminal wait --for exit --timeout-ms ...`. Это ожидание терминала, а не произвольного PID. Для диагностического состояния служит `run-check wait`, для worker settlement — `orca orchestration check --wait`. Не придумывать Orca process/event API.
- Только владелец ведёт наблюдение и cancellation. Координатор не читает тот же лог параллельно и получает существенную диагностику/результат от владельца. Heartbeat остаётся по live preamble; ожидание не становится отдельной модельной ролью.
- Один необязательный `resource_key` на команду. Lock хранится в общем локальном temp-каталоге, ключ которого включает canonical Git common dir и объявленное имя ресурса: две worktree этого репозитория видят одну блокировку. Это не новый лимит числа worktree и не очередной scheduler. Сетевые/distributed locks не обещаются. Lock не отбирается по одному возрасту; нужно подтвердить завершение всего принадлежащего run дерева процессов. На POSIX exit PID supervisor, включая его SIGKILL, недостаточен: записанная process group с проверенной identity/pgid может остаться живой. Пока её завершение не доказано, lock остаётся занятым; unknown не означает свободный ресурс. Пути lock/run и cleanup проверяются до удаления; удаляется только собственный объект, не его symlink-target.

### C4 — декларация проверок, snapshot и evidence

1. Старое `verify:` (block/flow list, quoted strings, комментарии, `|`/`>`) продолжает работать. Добавить необязательные `--phase ID` и `--checkpoint directed|integration|final` к обоим gate. При `--phase` берётся соответствующий `phases[].verify`; без этого аргумента действует прежний top-level список. Пустой явно выбранный список не подменяется будущими/чужими проверками.
2. Для новых планов элемент списка может быть **однострочным JSON-объектом, допустимым в YAML**: `{ "id": "unit", "command": "...", "checkpoint": "directed", "timeout_seconds": 120, "no_progress_seconds": 30, "resource_key": null, "inputs": [], "environment": [], "hermetic": false, "independent_replay": false }`. Поля команды соответствуют C3; дополнительные поля имеют документированные defaults. Не вводить полный YAML engine: поддержать существующий поднабор и строго ограниченное расширение; неподдерживаемую структуру отвергать, не исполнять как строку. Для разных shells план хранит явно соответствующие команды, не переводит произвольный shell-код автоматически.
3. `inputs` — явные дополнительные файлы/каталоги за пределами автоматически включаемого репозитория; `environment` — имена значимых переменных и исполняемые инструменты с их identity/version. `hermetic` по умолчанию false. Новая обязательная risk-декларация не выводится из отсутствия поля; повышенный риск может требовать `independent_replay`, который reuse не отменяет.
4. Snapshot ID вычисляется по фактическим байтам **всех tracked рабочих файлов**, включая изменения staged/unstaged, удаления, режимы/тип файла, и всех untracked non-ignored файлов. Ignored входы, если команда ими пользуется, перечисляются в `inputs`. `.git` не сканируется как дерево исходников, но HEAD/релевантные Git-факты сохраняются в provenance. Единственные служебные исключения для артефактов проверки — известный workspace/собственный output; исключения записаны в manifest, а не подразумеваются.
5. Snapshot не строится только по HEAD, времени файла или тексту `git diff`. Учитываются пути, типы/ссылки, содержимое и набор файлов; перечисление Git — NUL-safe, Unicode и пробелы не теряются. Расхождение index/working content, unreadable input, unresolved symlink/submodule или ошибка Git не дают валидного идентификатора по умолчанию. Для неподдержанного случая разрешён честный non-reusable результат/NEEDS_JUDGMENT без реализации универсального файлового sandbox.
6. Runner снимает проверяемые входы до и после выполнения, проверяет стабильность самого захвата и сохраняет mutation witness (содержимое и change metadata/идентичность файлов). Изменение входов во время запуска, в том числе заметный возврат к прежнему содержимому, делает evidence invalid даже при exit 0. Сравнение двух hashes не доказывает отсутствие произвольной временной записи с полным восстановлением metadata: команды/среды с такой возможностью, неизвестным внешним writer или непроверяемой наблюдаемостью **не получают reusable=true**. Не обещать обнаружение произвольного враждебного вмешательства без sandbox.
7. `result.json`/evidence создаётся runner, а не дописывается моделью как PASS. Поля: schema, run id/owner, command+shell+cwd, source snapshot before/after, input/environment fingerprints, tool versions, command exit, duration, log paths/hashes/completeness, mutation/invalidation reason, `reusable`, `origin_run_id` при reuse. Секреты окружения не публикуются; при необходимости хранится digest, и недоступный для сравнения секрет делает reuse невозможным.
8. Reuse — проверка ровно того же snapshot, команды, объявленных входов и значимого окружения, завершённых логов и исходного evidence. Неизвестная герметичность, сеть/время/изменяемая внешняя БД, неизвестный tool identity, повреждённые файлы либо требуемый независимый replay запрещают reuse. Текст отчёта исполнителя не заменяет evidence. Хранение — только существующий plan workspace; без глобального dependency cache и отдельного индекса-сервиса.
9. BASE evidence дополнительно связывается с полным BASE SHA, фактически проверенными файлами, способом подготовки worktree, окружением/linked dependencies и failure signature. Reuse BASE разрешён лишь при совпадении всей provenance. HEAD/evidence нельзя принять за BASE из-за одинаковой строки команды.
10. Сохранить действующие защитные ветви обоих gate: missing tool не является INHERITED; changed paths или различающиеся сигнатуры требуют judgment; zero passes не даёт GATE_OK; shared `.venv`/`node_modules` при изменённых source-файлах делает наследование ненадёжным; непроверяемый BASE не превращает красный HEAD в зелёный. Gate-worker также не может обходить эти ветви чтением кода без исполнимого доказательства.
11. stdout gate сохраняет первые две строки и существующие exit codes 0/1/2/3/4. Полные логи и evidence указываются после summary. Timeout/cancel/mutation/неполный запуск не нормализуются в PASS; неоднозначная проверка уходит в `NEEDS_JUDGMENT`, доказанная регрессия — в `GATE_FAIL`.
12. Независимая проверка проводится в явно выбранных checkpoints: directed после изменения, integration на границе контрактов/merge, final для полной приёмки. Одинаковая команда не повторяется только из-за смены роли. Необходимый риск-replay и конкретная новая гипотеза рецензента сохраняются с причиной запуска.

### C5 — пакет ревью и provenance

- Позиционный `review-package BASE HEAD [OUTFILE]` / `BASE WORKTREE OUTFILE`, stdout `wrote ...`/`EMPTY ...` и прежние exit codes сохраняются. Полный `.diff` остаётся совместимым артефактом; дополнительно создаётся `OUTFILE.manifest.json` и, при необходимости, каталог `OUTFILE.parts/`. Малый diff не дублируется множеством файлов.
- Manifest содержит schema, package id, BASE, mode/head, snapshot id, complete flag, полный список changed/untracked файлов и их статусы, количество байтов, parts с hash и точными диапазонами, исключения и ограничения. Генерация проверяет отсутствие изменения snapshot в процессе; ошибка Git или усечение запрещают `complete=true`.
- Начальный предел части — 64 KiB. Части покрывают полный diff без пропусков/перекрытий; допустим byte-range для очень длинной строки/файла. Oversize/binary-артефакт отмечается явно и требует указанной проверки исходного артефакта либо остаётся uncovered. Нельзя молча выкинуть хвост, ignored вход или новый файл ради лимита.
- Сохранить временную копию index для untracked и проверить настоящий index до/после по байтам, в том числе при ошибке. В PowerShell проверять exit каждого Git-вызова: сейчас ряд кодов от `Invoke-GitToFile` отбрасывается. Для non-ASCII/NUL путей не использовать построчное чтение вместо byte-safe перечисления.
- Reviewer читает manifest и все назначенные части в ограниченных диапазонах, может дочитать контекст по названному риску. Отчёт содержит package id/hash, snapshot и coverage всех parts/files/contracts, либо конкретное `CANNOT_VERIFY`. Требование «весь diff одним вызовом» удаляется; отсутствующий package не подменяется неполным ad hoc diff без untracked.
- Артефакт замораживается на время ревью. Validator проверяет его identity при dispatch и принятии отчёта. Изменённое содержимое, неполный coverage и stale package требуют обновлённого артефакта; по ним нельзя approve.
- Авторство берётся из реальных write Dispatch/launch receipts и изменённых файлов/commit ranges, включая fallback и fix-волну. Coordinator Co-Authored-By не является автором реализации. По каждому файлу консервативно накапливаются семейства всех авторов; неизвестное происхождение не считается безопасным.
- Обычно достаточно одного `review-final`. В смешанной ветке используются существующие роли финального ревью с минимально необходимыми независимыми назначениями: каждая единица изменения должна получить verdict от семейства вне её авторов. При раздельных файлах двух семейств допустимы два дополняющих отчёта одного финального раунда; каждый видит контекст всей ветки, но не даёт независимый approve собственной части.
- Coverage включает обе стороны **каждого** межфазного контракта: producer, consumer и их совместимость. Результат нельзя собрать только из отдельных файлов, забыв интеграцию. Если один файл/неделимая единица имеет несколько семейств авторов и в матрице нет независимого допустимого маршрута, результат остаётся `CANNOT_VERIFY`/blocked до явного назначения; свежий контекст не ослабляет family rule. Нового постоянного интеграционного review-loop нет; cap final остаётся 2 для объединённого раунда.

### C6 — минимальный валидатор и resume

Entry points `bin/protocol-state` и `bin/protocol-state.ps1`: `validate INPUT_JSON [RESUME_OUT]`. Вход — один предлагаемый переход, пути плана/ledger/отчёта/manifest/evidence, предыдущий компактный state и свежие сохранённые Orca receipts/Git-факты. Успех выдаёт `VALID`, ошибки — `INVALID`, отсутствие обязательного факта — `UNVERIFIABLE`; коды 0/1/2. Валидация не вызывает модели, не dispatch-ит, не коммитит и не чинит план.

- `RESUME_OUT` при валидном входе записывается атомарно; иначе существующий state не заменяется. Факты и решение отделены от прошедшего времени: файл resume не является источником новой lifecycle-авторизации.
- Минимальный state: schema, plan path/hash, `orca_run`, `plan_base`, текущие phase/base/step, активные task/dispatch/role/worktree и write ownership, round counters, принятые artifact/evidence ids, обработанные Delivery/message ids, открытые ledger ids, provenance/coverage и commit barrier с ожидаемым/подтверждённым SHA. Полные prompts/logs остаются по путям. Не создавать второй журнал событий вместо Orca.
- Общее определение binding-блока записать один раз в `skills/orca-dev/runtime-contracts.md`, секция `Report binding`: одна маркированная JSON-запись после сохранённых verdict-линий, `BINDING: {"schema_version":1,"run_id":"...","task_id":"...","dispatch_id":"...","role":"...","phase":"...","round":1,"artifact_id":"...","snapshot_id":"..."}`. Все role prompts ссылаются на эту секцию по предоставленному в dispatch абсолютному пути и задают только свои обязательные поля/sections, без одиннадцати копий общей схемы. Для плана artifact — hash актуального плана; для review — package; для implementer — текущий snapshot/report artifact. null допустим только в явно описанных неприменимых полях, не вместо неизвестного значения.
- Проверить subject/outcome и line 1 по роли, обязательные `SPEC`/`QUALITY`, `SIMPLICITY` со значениями `OK | CHANGES_REQUESTED`, review finding fields, fix-round evidence, `CANNOT_VERIFY`, plan risk и contract identifiers. Модельные суждения о materiality/overengineering остаются у reviewer; validator проверяет наличие и согласованность полей.
- Missing обязательного поля: один format-correction Dispatch, прежние findings unresolved. Повторный дефект формата — явный blocker протокола; не DEFER и не новый бесконечный review-loop. Исправление формата не даёт права добавить содержательные правки артефакта.
- Проверить принадлежность Task текущему Dispatch/Run, report path/hash и artifact identity. Позднее completion прошлой попытки игнорируется как stale; duplicate Delivery/message обрабатывается идемпотентно без повторных counters/dispatch/commit. Пустой wait и heartbeat не являются completion.
- Перед write-dispatch проверить свежую fleet/dispatch информацию для конкретного дерева. Непроверяемый прежний writer блокирует второго writer. Перед review и commit проверить frozen snapshot/coverage, обязательный replay и отсутствие unresolved findings.
- Семантические Consumes/Produces и соответствие Global Constraints проверяет plan-reviewer. Для координатора новые планы используют стабильные contract IDs; он проверяет, что каждое Consume ссылается на объявленный контракт/раньше произведённый результат. Отсутствие risk в новом плане — INVALID.
- Перед переходом к следующей фазе доказать успешный required commit и соответствие принятому артефакту; учитывать crash до/после commit. Stale state, failed hook и user-requested no-commit сохраняют ожидание. Запуск следующей фазы по подготовленному YAML `done` запрещён.
- Legacy: завершённые планы читаются как исторические, без массовой валидации/переписывания. Активный план без обязательных новых metadata получает `UNVERIFIABLE`; недостающие поля заполняются через существующий author/reviewer-маршрут, после чего применяется обычная валидация. До подтверждения metadata нет reuse или unsafe transitions. Отдельный resume-upgrade-компонент/режим не реализуется. Quickfix сохраняет план-less путь с тем же Task/Dispatch binding и ограничением одного файла; полный план ему не навязывается.

## Test strategy

### Checkpoints и бюджет

Все verify-команды frontmatter этого плана записаны для текущего native Windows-координатора (`python`, Windows-путь к validator). POSIX-эквиваленты с `python3` выполняются в описанной ниже изолированной копии; это тот же checkpoint и тот же бюджет, не дополнительный тестовый цикл. Плановый gate top-level намеренно содержит только уже существующую команду `git diff --check`; будущие тесты записаны в `phases[].verify`. До появления phase-aware gate в Ф3 implementer/gate-worker выполняет эти команды непосредственно по разделу своей фазы, а координатор при необходимости переносит **только текущий** список в top-level `verify`. Проверка одного diff-format не является приёмкой фазы. После Ф3 применяется `--phase`; финальные команды из этого раздела не запускаются раньше создания их файлов.

- Directed: один запуск затронутого test-модуля после содержательной правки; повтор только по изменению/конкретной новой гипотезе/обязательному replay. Не создавать тесты, просто проверяющие перефразировку документации; поведение проверяется реальными процессами, файлами и событиями.
- Integration: Ф2 — runner через оба gate; Ф3 — runner → evidence → gate/package; Ф4 — Delivery → report → frozen artifact → commit/resume; Ф5 — полный минимальный сценарий установки/поставки. Исправление после интеграционного сбоя сначала проверяется направленно.
- Бюджет каждого синтетического child-process — до 15 секунд; один модуль с процессными случаями — до 3 минут на платформу. Assertions привязаны к событию/файлу, не к точному времени до миллисекунды. Только два конкурентных child-run для проверки общего ресурса.
- Полный итоговый набор: `python -B -m unittest discover -s tests -p 'test_*.py' -v -f` на Windows, `python3 -B -m unittest discover -s tests -p 'test_*.py' -v -f` на POSIX. Лимит 17 минут 30 секунд на платформу; один плановый итоговый проход и максимум один повтор после исправления конкретного дефекта. Обязательный независимый replay учитывается в этом бюджете, а не прячется как бесплатный запуск.
- Diagnosis: один сбор ограниченных данных, одна проверяемая гипотеза, одна направленная проверка, до 15 минут на эпизод; затем решение continue по уже имеющемуся бюджету, исправить план или остановиться с partial. Новый эпизод без новой причины/данных не открывается автоматически.
- Нельзя продлевать бюджет потому, что результат «почти готов». После исчерпания не запускать новый тяжёлый check/worker, сохранить артефакт и факты; уже живой процесс обрабатывается по его заранее записанной политике cleanup. Незавершённый сценарий перечисляется как blocker. Ledger/caps ревью продолжают действовать.
- Счётчики минимальны: actual runs, reused runs/origin, independent replays, BASE runs/reuses, repeat reason, duration, diagnostic events и accepted/partial outcomes. Не собирать dashboard, quota, маркетинговый рейтинг или дополнительную телеметрию провайдера.

Поправка Ф5 к общему бюджету: первый PS5.1 full suite остановлен по deadline 480 с во время случая 42, до последних 10 verification cases; эта попытка остаётся failed. Пакетирование только последнего модуля не доказывает укладывание всего набора в 480 с. Принято конечное выделение 1050 с = 6 × 175 с для шести существующих модулей с сохранением всех 52 сценариев и прежних child/module limits. Это верхняя плановая граница, не измеренная длительность или PASS; итоговая приёмка остаётся pending.

Отдельное исключение Ф5 после доказанного PH5-G3 (решение координатора `msg_390435d2266d` для этого Run): `ReadAllText(status.json)` при атомарной Windows-замене дал sharing violation, wait exit 125 и пустой stdout. Исправляются native runner и чтение JSON в тестовой оснастке; регрессия с реальным DELETE-handle остаётся внутри существующего случая, всего 52 теста. PS5.1 full attempt2 прошёл 52/52 за 617.721 с **до** этой правки общего C3 runner и сохраняется как исторический PASS; PS7 full attempt1 остановлен на случае 26 за 259.464 с и остаётся failed, как и первый PS5.1 timeout.

После этой правки координатору явно выделены ровно три оставшихся full run: **один дополнительный PS5.1**, **один ранее оставшийся PS7 actual-fix repeat**, **первый WSL**. Каждый ограничен 1050 с; child watchdog 14 с и module 175 с не меняются. Дополнительный PS5.1 — названное исключение из исходного ограничения повторов этой задачи; общие caps навыка не меняются, иных full repeats это решение не разрешает. Итоговая приёмка остаётся pending до этих проверок; статусы и commits ведёт координатор.

Последующее исключение Ф5 для этого Run (явное решение координатора `msg_3a358e0daa5d`): после исправления чтения PS7 full attempt2 прошёл 52/52 за 490.167 с (`final-suite-ps7-2/summary.json`), затем PS5.1 full attempt3 остановлен на случае 26 за 319.532 с (`final-suite-ps51-3/summary.json`). Сохранённый результат владельца доказал writer-side `Replace` AccessDenied: interrupted, duration 1.7229405 с, cleanup/logs true. Оба результата сохраняются в истории; прежние PS7 и PS5.1 PASS предшествуют новой правке атомарной публикации.

Текущее исправление: `ReplaceFileW` для существующего назначения, перенос без перезаписи для отсутствующего, конечные повторы Win32 5/32 не более 250 мс и не далее остатка бюджета команды. Реальные файловые дескрипторы проверяют временную блокировку, старый/новый полный JSON и постоянный отказ с сохранёнными временными байтами; прежние DELETE-reader/no-progress assertions и все 52 случая сохранены. Направленные проверки автора PS5.1/PS7/WSL завершены; свидетельства — `phase-5-fix-3-report.md` и `phase5-fix3-final-evidence.json` в workspace.

Актуальное оставшееся выделение координатору после этой правки: **PS5.1 full attempt4**, **PS7 full attempt3**, **WSL full attempt1**, ровно по одному запуску, каждый до 1050 с. Это явное отдельное расширение исходных caps данной задачи для обычного сопровождения, а не штатное соблюдение первоначального распределённого лимита и не разрешение дальнейших повторов. Общие caps навыка, child 14 с/module 175 с, число тестов и status/commit metadata не меняются; автор полные наборы не запускает. Итоговая приёмка pending до независимых результатов нового снимка.

Следующее отдельное расширение Ф5 по заданию `task_9a8af66091ba` / `ctx_f9eca34009df` относится только к подтверждённому read race: PS5.1 full attempt4 завершился 25 PASS + FAIL на случае 26, 304.137 с unittest / 306.782 с C3 (`final-suite-ps51-4/summary.json`). Wait вернул 125, пустой stdout и Open sharing violation; владелец независимо завершился exit0 за 4.6118785 с с полным JSON и cleanup/logs true. Этот failed outcome сохраняется вместе с исходным 480-секундным прерыванием, всеми прежними failures и pre-fix PASS.

Исправление ограничено повтором открытия JSON при Win32 32: максимум 250 мс, дополнительно ограничено остатком бюджета wait/run; ACL, отсутствующий файл и ошибка разбора остаются ошибками. Принятая writer-side политика не меняется. Регрессия с реальным несовместимым handle освобождает его после verbose-сигнала первой неудачной попытки чтения, проверяет постоянную блокировку и повреждённый JSON; исходные 52 случая и порядок сохранены. Направленные PS5.1 4/4 и WSL diagnostic 1/1 прошли; PS7 сначала 2 PASS + необъяснённый cancel FAIL125, затем единственный разрешённый affected replay и ранее не выполненная exact-command проверка — 2/2 PASS после добавления записи ответа cancel/owner. Первый cancel failure не объявляется исправленным или опровергнутым; свидетельства и ограничения — `phase-5-fix-4-report.md`, `phase5-fix4-final-evidence.json`.

После финальной фиксации кода и этих двух документов актуально выделены ровно **PS5.1 full attempt5**, **PS7 full attempt3**, **WSL full attempt1**, по одному запуску каждому, каждый до 1050 с. Это названное дальнейшее расширение для данного фактического дефекта в рамках обычного сопровождения репозитория; оно не удостоверяет соблюдение первоначальных caps. Общие распределённые caps, child 14 с/module 175 с, число тестов, frontmatter status и commit ranges сохраняются. Все full runs принадлежат координатору после settlement; автор их не запускает, дальнейшие повторения не выделены, итоговая приёмка pending.

### Платформы и независимость

- Native Windows: обязательны PowerShell 5.1 и доступный PowerShell 7; тестовая оснастка вызывает именно `.ps1` entry points. Test Python работает только как driver/stdlib assertions. Отдельно доказать, что рабочие `.ps1` не требуют Bash/python3/jq.
- POSIX: в установленной Ubuntu WSL найдены `/usr/bin/bash`, `/usr/bin/python3`, `/usr/bin/git`. В исследовании WSL не смогла перевести текущий `D:`-путь; implementation подготавливает маленькую копию нужных scripts/tests в собственном временном каталоге Ubuntu, переносит байты без текстового PowerShell-pipeline и записывает их hashes. Монтирование дисков и пользовательскую WSL-конфигурацию не менять. Альтернатива — уже доступный POSIX-host, явно названный в отчёте.
- Git Bash найден как `C:/Program Files/Git/bin/bash.exe`; `bash` на обычном Windows PATH — WSL launcher. Проверка Git Bash не считается доказательством POSIX process-group cleanup. Bash 3.2 совместимость контролируется отсутствием новых shell-конструкций; если нет настоящего 3.2, этот предел подтверждён анализом, а не выдуманным runtime-прогоном.
- Новых model benchmarks не требуется. Текущий реальный Run используется как источник фактических launch/reuse/settlement receipts. Если этого недостаточно для существенного lifecycle-сценария, допустим один маленький smoke максимум с тремя worker Dispatch и 30 минутами, без нового полного многомодельного конвейера; при отсутствии пригодной среды это явно остаётся ограничением.

### Доставка и свидетельства

`docs/controlled-pipeline-validation.md` содержит компактную таблицу A1–A7 → команды/артефакты → результат, версии ОС/CLI/shell, hashes тестируемого source snapshot, важные counters и оставшиеся ограничения. Полные логи/receipts живут в plan workspace, а документ даёт реальные пути. Это инженерная поставка; никаких внешних пользовательских acceptance/deployment-этапов здесь не согласовано. Если они появятся позднее, их критерии/владелец/срок фиксируются отдельно и не выдаются за уже выполненные.

`quick_validate.py` проверяется по указанному доступному пути с PyYAML и UTF-8; на другой машине сначала определяется его фактическое расположение. На исследованном BASE проверка возвращает rc=1 из-за незакавыченного `description` в frontmatter `skills/orca-dev/SKILL.md`. Ф1 явно исправляет это поле, сохраняя ключи `name`/`description`, и должна получить настоящий успешный результат на изменённом HEAD/WORKTREE: это исправленный HEAD-failure, а не `INHERITED`. Сам validator и его требования не меняются; бюджет не увеличивается. Его успех не заменяет behavioral tests и независимое содержательное ревью skill.

## Risks / assumptions

- Наиболее рискованны native process-tree cleanup, symlink/junction safety и освобождение общего lock: поэтому Ф2 и Ф5 имеют `risk: DATA_LOSS`. Неподтверждённое завершение не освобождает ресурс для конкурентного writer.
- Ограниченное расширение YAML должно сохранять все реально поддерживаемые сегодня формы verify. Общего YAML-парсера без зависимости не обещается; ошибочный новый формат должен отказать явно. Новые структуры выбраны как JSON внутри допустимого YAML для минимального детерминированного чтения.
- Snapshot/evidence защищают от ошибочного reuse в доверенном локальном workflow; они не доказывают отсутствие любого враждебного изменения файлов или внешних входов. При сомнении reuse выключен. Пользовательская команда, намеренно переписывающая входы, не получает reusable-зелёный результат по совпадению HEAD.
- Точный snapshot может часто инвалидироваться на документальных/метаданных изменениях. Решение — плановые checkpoints и запись metadata до freeze, а не ослабление identity или dependency cache.
- Известные `.venv`/`node_modules` ссылки в BASE могут исполнять HEAD-код. Существующая осторожная классификация обязательна даже если результат взят из cache.
- CLI lifecycle меняется независимо от текста skill. В текущем receipt встречается `worker.agentTerminalHandle`, а в старых recipes написано snake_case; новый текст использует действительную форму и явно описанный совместимый fallback. Optional unknown fields не становятся доказательством.
- У сохранённого writer/implementer может быть external/user-taken-over terminal. Его нельзя принудительно закрывать для красивого списка ресурсов; состояние и причина retention отражаются в отчёте.
- Семейство reviewers для неделимого смешанного артефакта может оказаться недоступно. В таком случае требуется явное назначение независимого маршрута либо честная неполная приёмка; парой свежих контекстов проблему не скрывать.
- `ORCA_DEV_TEST_HOME` уже есть в `install.ps1`, но сегодня не изолирует запись User ORCA_DEV_HOME. Сначала исправить эту тестовую границу, затем запускать install-mode fixtures; не запускать текущий installer с fake home, полагая реальные settings защищёнными.
- Junction и Process/User ORCA_DEV_HOME в данном worker уже ведут в `D:/Projects/orca-strigov`; повторная установка в настоящий профиль не нужна. Другой уже запущенный Orca может иметь старое окружение; проверка должна различать источник ссылки, User env и Process env.

## Ф1: Согласовать политику и минимальную достаточную поставку

**Files in this phase:** Modify все файлы, перечисленные в строках Ф1 раздела Files. Новых runtime-файлов нет.

**Interfaces:**
- Consumes: ничего из будущих фаз; полная пользовательская авторизация, существующие roles/prompts и C1–C2.
- Produces: C1 (роли/simplicity/delivery) и C2 (lifecycle/base/commit barrier) как применимый протокол; шаблоны новых планов со risk, проверками, бюджетом и contract IDs.

1. Исправить матрицу целиком, включая families/substitutions/cascade/effort cheat-sheet/профили. Обычное планирование не проверяет здоровье bridge ради автоматического выбора. Экспериментальный control-review разрешён только при семейной независимости и явно фиксируемом выборе; трудный маршрут — по обоснованной diagnosis, без обязательного прохождения новой длинной каскадной цепочки.
2. Удалить противоречащие модельные литералы из maintained skill/recipes/prompts/README/install docs/messages; запуск использует параметры роли. Явно исправить YAML frontmatter `skills/orca-dev/SKILL.md`: корректно закавычить `description`, сохранив содержание описания и прежние допустимые ключи `name`/`description`; `quick_validate.py` и правила валидации не изменять. Исторические разделы с фактическими model-runs не переписывать: заменять активные пересказы ссылками на существующие неизменённые отчёты.
3. Перенести semantic Step 2.5 и simplicity в имеющийся reviewer prompt. Исправить в writer-примере пропущенный risk первой фазы; включить outcome → deliverable/dependencies → check → evidence, инженерную готовность и согласованную внешнюю приёмку, checkpoints, finite budgets и partial status.
4. Согласовать раунд эскалации, warning materiality, плановую базу, удержание автора и implementer, исправление report-format вместо DEFER, правила settlement/ack/reuse/retention/release и запрет перехода после failed/skipped commit. В существующих launch instructions различить принятие ввода и подтверждённое начало задания; описать однократный Enter только для доказанного retained draft по C2, без нового readiness API и изменений `bin/wait-agent-ready`. Удалить старый повод retry из одного timeout/тишины. В prompts diagnosis/gate убрать несовместимые с этим лазейки.
5. Prompts загружаются только при назначении соответствующей роли. До появления runner/evidence/validator в следующих фазах действуют описанные ограничения и существующие команды; не вызывать ещё не созданные binaries.

**Independently verifiable acceptance:** A1/A2 и текстовая часть A6/A7. Plan-reviewer проверяет таблицу назначений против полной авторизации, а не против прежних defaults; тот же отчёт содержит Simplicity и семантические контракты. Выполнены проверки frontmatter/whitespace из `phases[].verify`, включая rc=0 неизменённого `quick_validate.py` на исправленном skill; прежний красный BASE не используется для объявления ошибки наследуемой. Independent review отдельно подтверждает отсутствие активных назначений вне roles. Результат уже применим без установки будущих скриптов.

## Ф2: Один управляемый запуск вместо модельного опроса

**Files in this phase:** Create `bin/run-check`, `bin/lib/run_check.py`, `bin/run-check.ps1`, `skills/orca-dev/runtime-contracts.md`, `tests/support.py`, `tests/test_runner.py`; Modify два verify-gate и пять prompt/recipe-файлов из строк Ф2 раздела Files.

**Interfaces:**
- Consumes: C2; существующие workspace и gate exit/summary contract.
- Produces: C3; устойчивые request/status/result/log artifacts, применимые обоими gate без reuse.

1. Реализовать run/wait/cancel и нативное владение process tree. Python — внутренняя реализация Bash entry point; `.ps1` не вызывает Python. Не вводить дополнительную универсальную библиотеку процессов.
2. Добавить потоковые логи, атомарные результаты, диагностику progress и safe cancellation/deadline. При ранней ошибке/потере владельца сохранить состояние; не писать ложный command exit.
3. Добавить одну resource lock на объявленный тяжёлый check, общую для worktree. Проверка двух деревьев не должна сериализовать обычные независимые чтения/правки. Общая фикстура двух worktree находится в `tests/support.py`; resource-contention assertions реализуются в `tests/test_runner.py` и не дублируются в финальном delivery-тесте.
4. Заменить `out=$(bash ...)` и текущий `Run-Command` gate на runner; normalized failure signature и хвосты читать из логов ограниченно. BASE-run использует тот же runner и per-run provenance хотя cache ещё выключен.
5. Уточнить recipes/prompts: никаких Schedule-таймеров и двух наблюдателей одной команды; no-progress → bounded diagnosis, hard deadline → заданный cleanup. Сохранить live preamble obligations.

**Independently verifiable acceptance:** A3. `test_runner.py` запускает настоящие короткие success/failure, одновременный большой stdout/stderr, stdin-read, кавычки/Unicode/cwd с пробелом, no-progress с последующим успешным выходом, cancel/deadline с дочерним и внучатым процессами, повторный run id, stale owner и resource contention двух worktree. Отдельно проверяется, что второй run стартует после освобождения ресурса, а unknown owner не «протухает» автоматически; exit supervisor при живой принадлежащей run POSIX process group не освобождает lock. Оба gate сохраняют прежние строки/коды и используют durable logs. После этой фазы long-command путь поставляется самостоятельно, evidence reuse отсутствует.

## Ф3: Проверять доказательства и весь пакет ревью

**Files in this phase:** Create `bin/lib/verification.py`, `bin/lib/verification.ps1`, `tests/test_verification.py`, `tests/test_review_package.py`; Modify runner, оба gate, оба review-package, `tests/support.py`, `tests/test_runner.py` и точные protocol/prompt-файлы из строк Ф3 раздела Files.

**Interfaces:**
- Consumes: C3 и phase/base из C2.
- Produces: C4 evidence/snapshot/checkpoint и C5 complete package manifest, используемые непосредственно gate/review и будущим валидатором.

1. Вынести только разделяемые parsing/hash/snapshot helpers каждой платформы в указанные internal-файлы. Добавить ограниченную декларацию команд/phase selection, сохранив legacy parser cases и native exit behavior.
2. Runner создаёт evidence до/после запуска. Gate проверяет eligibility и либо использует доказанный результат, либо запускает команду с `repeat_reason`; risk-replay всегда остаётся физическим запуском другого проверяющего.
3. Сохранить все HEAD/BASE safeguards C4; добавить BASE cache только с полным совпадением provenance. Начать с workspace lookup без fine-grained cache, database и отдельной службы.
4. Review-package сохраняет полный diff и временный index, добавляет bounded parts/manifest/coverage, проверяет snapshot до/после и каждый Git exit. Убрать «one read call» из review prompts. Неполное чтение оформляется как unresolved, а не успешное ревью.
5. Impl/gate/review prompts ссылаются на машинные evidence вместо доверия текстовым test summaries. Primary/final выполняют направленные и финальные checkpoints по договору, не повторяют неизменную suite по названию следующего шага. Warnings оцениваются по новой существенной проблеме/нарушенному требованию; чистота stdout сама по себе не блокирует.

**Independently verifiable acceptance:** A4/A5. Тесты доказывают: unchanged reusable run реально не выполняется второй раз; меняются tracked staged/unstaged, untracked, удаление/переименование, ignored declared input, команда, tool/env и BASE — reuse отказывается; input mutation/известный возврат к исходному содержимому и broken log/evidence не дают PASS; non-hermetic result не reuse; independent replay увеличивает actual run count. Проверяются missing tool, zero passes, BASE failure signatures, bad BASE и shared dependency safeguards. Package-тесты проверяют Unicode/пробелы, untracked, большой diff, oversize/binary coverage, stale/missing part, real-index byte equality после успеха и ошибки. Gate/package interoperable на обеих платформах.

## Ф4: Сделать переходы и возобновление проверяемыми

**Files in this phase:** Create `bin/protocol-state`, `bin/lib/protocol_state.py`, `bin/protocol-state.ps1`, `tests/test_protocol_state.py`; Modify `tests/support.py`, SKILL/roles/recipes/runtime-contracts и все 11 точных prompts из строк Ф4 раздела Files.

**Interfaces:**
- Consumes: C1–C5; реальные сохранённые Orca receipts и read-only Git facts.
- Produces: C6 validation/resume и применяемые coordinator barriers; самостоятельный проверяемый результат для одного события/перехода.

1. Реализовать одинаковый контракт validate на обеих платформах. Нормализация берёт подтверждённые поля текущего Orca; unknown/optional fields и external terminal не интерпретируются по старому recipe.
2. Описать общий BINDING record один раз в секции `Report binding` файла `runtime-contracts.md`, сохранив прежние verdict-линии. В role prompts оставить ссылку на общее определение и только роль-специфические обязательные поля/sections; общую схему не копировать. Проверить обязательные поля; format-correction один, содержательное ревью остаётся в прежнем cap.
3. Добавить идемпотентное принятие Delivery, Task/Dispatch/artifact matching, counters, single writer и commit barrier; сохранять компактный resume только после валидного действия. Разрешённые механические вызовы coordinator включают валидатор; semantic plan-read из его обязательств удалён.
4. Собирать фактическое author provenance, включая исправления и fallback. Применить минимальный набор независимых final-review assignments с явным покрытием межфазных контрактов и совместным cap; неизвестное происхождение или недоступный независимый маршрут блокирует approve.
5. Документировать `UNVERIFIABLE` для активного плана с недостающими metadata и их заполнение через существующий author/reviewer-маршрут, без отдельной реализации resume-upgrade; исторические `done` планы не переписывать, существующий quickfix path сохранить. Проверить, что заполнение всех технических полей не завершает невыполненный пользовательский сценарий.

**Independently verifiable acceptance:** A2/A5/A6/A7. Табличные сценарии: late retry completion, duplicate/replayed Delivery, conflicting report binding, missing SPEC/QUALITY/SIMPLICITY/finding field/risk, повторная format-error, превышение каждого cap, heartbeat/empty wait, live/unverifiable writer, accepted retention, release uncertainty, stale package/evidence и неполный coverage. Отдельные Git fixtures проверяют failed/skipped commit, source change by hook, crash after successful commit before resume и повторное событие без повторного commit. Смешанный final-review проверяет каждую сторону контракта; одинаковое семейство плюс свежий контекст не проходит. Ни один fixture не запускает настоящий model worker.

## Ф5: Подтвердить установку и рабочую поставку

**Files in this phase:** Modify `install.sh`, `install.ps1`, `README.md`, `docs/install-windows.md`, `skills/orca-dev/SKILL.md`, `skills/orca-dev/orca-recipes.md`, `tests/support.py`, `bin/lib/verification.ps1`, `tests/test_verification.py`, `bin/run-check.ps1`, `tests/test_runner.py`; Create `tests/test_install.py`, `tests/test_delivery.py`, `docs/controlled-pipeline-validation.md`.

**Interfaces:**
- Consumes: C1–C6, результаты предыдущих фаз и общая фикстура двух worktree из `tests/support.py` (Ф2).
- Produces: проверенную инженерную поставку A1–A7, согласованные install/check instructions и отчёт с настоящими ограничениями.

1. До install-mode тестов завершить изоляцию существующего `ORCA_DEV_TEST_HOME`: test mode не пишет настоящий User environment/registry и не изменяет реальные trust/Orca registration. Переиспользовать этот узкий seam; не добавлять общий config framework. Для Bash аналогичная фикстура не должна переопределять домашнюю переменную в текущем пользовательском shell.
2. Исправить проверку существующего/dangling symlink/junction и несовпадения целевого checkout. Read-only check не исправляет ничего. Install может заменить только подтверждённую stale-ссылку, не обычную папку; старый target и посторонние данные остаются целы. Canonical проверка путей обязательна до удаления/замены.
3. Сравнивать источник skill, User ORCA_DEV_HOME и Process ORCA_DEV_HOME отдельно. Для живого процесса со старой env дать точное указание restart/явного process-level override при worker launch; не менять системную конфигурацию автоматически. Реальный checkout этой поставки — `D:/Projects/orca-strigov`; installer не должен жёстко кодировать его для других пользователей.
4. Обновить список binaries и зависимостей, bridge opt-in, version-matched lifecycle, новые/legacy verify формы и инструкции phase checkpoints. Разделять проверенные платформы и исторические предположения.
5. Выполнить bounded delivery fixtures: небольшой последовательный сценарий с исправлением/commit/resume, затем сквозной путь актуальных packages и integration check на общей фикстуре двух worktree из Ф2. Не дублировать полный resource-contention test в `test_delivery.py`: его единственная реализация остаётся в `test_runner.py`, а в итоговом отчёте сохраняются актуальные ресурсные evidence по C4. Обязательный независимый replay выполняется существующим тестом в заданном бюджете; устаревшие evidence не переиспользуются. Проверить сценарий отсутствующей обязательной зависимости: отчёт остаётся partial/blocked даже при успешных остальных тестах.
6. Выполнить один итоговый набор по платформам в заданном бюджете и frontmatter validation. Использовать receipts данного Run для live route/reuse proof; дополнительный маленький smoke только если он закрывает конкретный неподтверждённый факт. Записать результаты, counters, source identity и ограничения в отчёт поставки.

**Independently verifiable acceptance:** A7 и сквозное подтверждение A1–A6. `test_install.py` охватывает правильную/устаревшую/dangling ссылку, обычную папку, пути с пробелами, stale Process env, read-only check и неизменность внешних файлов/настоящей конфигурации; `test_delivery.py` проверяет завершённый пользовательский путь и честный отказ при обязательном пропуске/исчерпании бюджета. Итоговый документ не называет поставку принятой при отсутствующей native/POSIX проверке или незавершённом сценарии; исключения/поздняя внешняя приёмка могут появиться только по явному отдельному согласованию.
