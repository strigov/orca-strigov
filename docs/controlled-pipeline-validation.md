# Controlled pipeline: проверка поставки

Ф5 выполнена относительно `21d544b211333888cf8fc2921dccb2aa6fbccf9b`.
Это запись направленных проверок автора, **не итоговая приёмка репозитория**.
Единственный полный final suite принадлежит независимому gate; его результат
пока pending. Результаты final записываются отдельно в SDD, чтобы отчёт не менял
проверяемый source во время своей проверки.

Workspace этой поставки:
`D:/Projects/orca-strigov/.superpowers/sdd/2026-09-12-orca-dev-controlled-pipeline/`
(ниже `WS`). Source hashes и snapshot: `WS/phase-5-freeze.json` и
`WS/phase5-snapshot.json`; отчёт автора: `WS/phase-5-report.md`.
Контракты интерфейсов и BINDING определены только в
[runtime-contracts.md](../skills/orca-dev/runtime-contracts.md).

| Приёмка | Команда / артефакт | Полученное свидетельство и граница |
|---|---|---|
| A1 — роли/lifecycle | `roles.md`; `WS/execution-observations.md`, принятые отчёты Ф1–Ф4 | Реальные dispatch/reuse/settlement данного Run; не сертификат новых helpers, новые model smoke не запускались |
| A2 — simplicity | Принятые plan-review и `test_protocol_state.py` | Ранее принятая политика и C6; актуальный независимый replay остаётся в final suite |
| A3 — управление процессом | `test_runner.py`; `test_install.py` запускает установленный runner | Полный contention-тест существует только в `test_runner.py`; его replay/ресурсные C4 artifacts запишет final gate |
| A4 — evidence | `test_delivery.py`, ранее принятый `test_verification.py` | Настоящий gate через runner, HEAD/BASE после ошибки, новый запуск после исправления; недоступный tool/deadline не становится PASS |
| A5 — package | `test_delivery.py`, `test_review_package.py` | Настоящий manifest проверяется helper; неполные стороны контракта и чужая artifact identity отвергаются C6 |
| A6 — commit/resume | `test_delivery.py` | Последовательность gate failure → исправление → package/reports → отказ при несуществующем commit → реальный временный commit → resume; основной index/HEAD не меняются |
| A7 — установка | `test_install.py` | Correct/stale/dangling link, обычный каталог, чужой linked parent, Unicode/пробелы/скобки, две worktree, stale Process, read-only check, missing dependency; сохранность реальных settings проверяется каждой фикстурой |

Направленные команды из корня checkout (полные stdout/stderr в указанных каталогах):

```powershell
python -X utf8 -B .superpowers/sdd/2026-09-12-orca-dev-controlled-pipeline/phase5-tests.py <new-log-dir> <absolute-shell> <unittest-name>...
python -X utf8 -B .superpowers/sdd/2026-09-12-orca-dev-controlled-pipeline/phase5-wsl.py test_install test_delivery
python -X utf8 -B C:/Users/strig/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/orca-dev
git --no-optional-locks diff --check
```

`phase5-tests.py` запускает `python -B -m unittest ... -v` из `tests/`;
имена — `test_install`, `test_delivery` или конкретный метод. Shell выбирается
через process-only `ORCA_TEST_SHELL`; `ORCA_DEV_HOME` указывает этот checkout,
`ORCA_TEST_ARTIFACTS` unset. Для native dependency check драйверу задаётся
process-only `PHASE5_NATIVE_PATH_ONLY=1`: дочерний PATH содержит только Git,
а Python для тестов/их явно объявленных команд вызывается абсолютным путём.

| Платформа | Фактические результаты | Логи в WS |
|---|---|---|
| Windows PowerShell 5.1 | 6 различных сценариев покрыты несколькими направленными вызовами; initial install 3/4, после исправления literal-target 1/1; initial delivery 1/2, после исправления CRLF assertion и добавления installed-runner 2/2 за 56.791 s; финальный literal/native replay 1/1 за 17.820 s | `phase5-ps51-install-first`, `phase5-ps51-literal-fix`, `phase5-ps51-delivery`, `phase5-ps51-directed-fixes`, `phase5-ps51-final-native` |
| PowerShell 7 | Initial 4/6 за 81.980 s, затем 3/3 затронутых install-сценария после исправления различия Target в PS7 за 16.552 s; delivery/missing-tool прошли initial | `phase5-ps7-directed`, `phase5-ps7-literal-fix` |
| Ubuntu WSL | 6/6 за 8.722 s; после отключения pathname globbing один affected install replay 1/1 за 0.922 s | `phase5-wsl-b45dbe3d`, `phase5-wsl-09bf2e22` |

Каждый каталог содержит `test.log` и `command.json` либо WSL `provenance.json` /
`transfer.json`. Проваленные попытки сохранены; повторялись только названные
затронутые сценарии после конкретных исправлений. Ошибка console encoding
первого внешнего драйвера не уничтожила его `test.log`/receipt. Временные
Git/worktree, runner evidence и логи проверяются во время теста и удаляются
обычным teardown; они не объявляются reusable evidence основного checkout.

Ограничения: parent watchdog каждого child — 14 s, проверяемые команды — до 9 s
(отдельный тест deadline — 0.3 s), timeout модуля — 175 s. Новых dispatch — 0,
полных final suites у автора — 0, reuse результатов автора для final — 0.
Тесты runner/deadline проверяют настоящие короткие процессы, а C6 получает
synthetic Orca receipts; это разные виды свидетельств. Версии ОС/shell/CLI,
сводные счётчики вызовов и cleanup observation записаны в отчёте и SDD.

Изолированная WSL-копия переносится через бинарный tar с SHA256 до/после,
без PowerShell text pipeline, mount или WSL config changes. Единственная
объявленная подстановка — неизменённый `bin/sdd-workspace` из LF Git blob BASE;
остальные файлы сохраняют рабочие байты. Предупреждения внешнего WSL PATH про
`D:\Apollo` не являются результатом теста. macOS/Bash 3.2 не запускались;
совместимость shell-конструкций с 3.2 проверена по source, POSIX runtime — Ubuntu.

Установленное состояние перед Ф5: junction и User `ORCA_DEV_HOME` ведут в
`D:/Projects/orca-strigov`, старый Process — в `C:/Users/strig/orca-strigov`,
Machine отсутствует. `WS/pre-phase-5-installation-baseline.json` — наблюдение
координатора; `WS/phase5-installation-after.json` — последующее read-only сравнение.
В текущем worker Process уже указывает D:; это отдельное окружение процесса,
а junction/User/Machine совпадают с baseline. Полное сравнение с Process поэтому
false; persistent-сравнение отдельно записано в `WS/phase5-installation-comparison.json`.
Реальная переустановка не выполнялась. Фикстуры используют существующий
`ORCA_DEV_TEST_HOME`, отдельный файл simulated User environment и сравнение
digest настоящих settings/registry; внешние CLI-проверки в test mode запрещены.
Installer WARN для пробелов остаётся ограничением model CLI routing, хотя
файловые операции и helpers с такими путями проверены.

Для независимого final зарезервированы `WS/phase-5-final-evidence.json` и каталоги
`WS/phase5-final-ps51/`, `WS/phase5-final-ps7/`, `WS/phase5-final-wsl/`.
Их отсутствие означает pending, не PASS. Владелец gate выполняет один
`python -B -m unittest discover -s tests -p 'test_*.py' -v -f` (POSIX: `python3`) на
платформу с лимитом 1050 s (17 минут 30 секунд), максимум один повтор после конкретного исправления.
Записываются источник, shell/environment, реальные exits, duration, counters,
полные логи и cleanup. Недоступная обязательная проверка остаётся BLOCKED;
последующее ревью читает эти результаты и запускает только обоснованный replay.

Поправка общего бюджета Ф5: первая PS5.1 попытка остановлена по deadline 480 с
во время случая 42, до последних 10 verification cases, и остаётся failed
(`WS/final-suite-ps51-1/summary.json`). Пакетирование последнего модуля не
доказывает укладывание всего набора в 480 с. Согласованы 1050 s = 6 × 175 s
как конечная сумма существующих модульных границ при сохранении всех 52
сценариев, child/module limits и числа попыток. Это плановое выделение,
не измеренная длительность или PASS; окончательная приёмка остаётся pending,
исторические directed checks автора сохраняют свой статус.

Последующее исключение для этого Run (`msg_390435d2266d`): после исправления
JSON null PS5.1 full attempt2 прошёл все 52 теста за 617.721 s
(`WS/final-suite-ps51-2/summary.json`), затем PS7 full attempt1 остановлен
на случае 26 за 259.464 s (`WS/final-suite-ps7-1/summary.json`). Конечный
эксперимент PH5-G3 остановлен при первом сбое в третьей паре: native
`ReadAllText(status.json)` получил sharing violation при атомарной замене,
wait вернул 125 и пустой stdout (`WS/phase5-fix2-experiment-ps7/pair-3/`).
Совместимое ReadWrite/Delete sharing введено в native runner и JSON-reader
оснастки; настоящая DELETE-handle регрессия включена в существующий случай,
число тестов остаётся 52. Прежний полный PS5.1 PASS относится к версии
до этой правки общего C3 runner; исходные PS5.1 timeout и PS7 failure сохранены.

Координатор явно выделил ровно **один дополнительный PS5.1 full run**,
**ранее оставшийся PS7 actual-fix repeat** и **первый WSL full run**,
каждый до 1050 s. Дополнительный PS5.1 — отдельное исключение из исходного
лимита повторов этой задачи; общие caps навыка и child 14 s/module 175 s сохранены,
других full repeats это решение не разрешает. Окончательная приёмка pending;
исторические PASS и directed checks не заменяют эти оставшиеся проверки.

Последующее явное расширение для этого Run (`msg_3a358e0daa5d`) сохраняет
историю предыдущего выделения: PS7 full attempt2 — 52/52 PASS за 490.167 s
(`WS/final-suite-ps7-2/summary.json`), PS5.1 full attempt3 — failure на случае 26
за 319.532 s (`WS/final-suite-ps51-3/summary.json`). Сохранённый owner result
подтвердил writer-side Replace AccessDenied: interrupted, 1.7229405 s,
cleanup/logs true. Эти полные PASS и прежний PS5.1 PASS предшествуют новой
производственной правке и не подтверждают текущий снимок.

Правка публикации использует ReplaceFileW для существующего назначения,
перенос без перезаписи для отсутствующего и максимум 250 ms повторов Win32 5/32,
ограниченных остатком бюджета команды. Реальные handles проверяют временную
блокировку, старый/новый полный JSON и постоянный отказ с сохранением temp;
DELETE-reader/no-progress assertions и 52 исходных случая сохранены.
Направленные результаты: PS5.1 4/4 и после правки получения тестового handle
1/1; PS7 первоначально 1 PASS + 1 fixture ERROR, после исправления 3/3;
WSL 4/4. Полные команды, исходные неуспехи, hashes и cleanup —
`WS/phase-5-fix-3-report.md`, `WS/phase5-fix3-final-evidence.json`.

Актуальное конечное выделение координатору: **PS5.1 full attempt4**,
**PS7 full attempt3**, **WSL full attempt1**, ровно по одному, каждый до 1050 s.
Это явное отдельное расширение исходных caps данной задачи для обычного
сопровождения, а не штатное соблюдение первоначального распределённого лимита.
Общие caps навыка, child 14 s/module 175 s, status/commit metadata и число
тестов не меняются; иных native full repeats не выделено, автор полных наборов
не запускает. Все прошлые исходы сохраняются; итоговая приёмка нового снимка
остаётся pending.

Дальнейшее отдельное расширение Ф5 (`task_9a8af66091ba` / `ctx_f9eca34009df`):
PS5.1 full attempt4 — 25 PASS + FAIL на случае 26, 304.137 s unittest,
306.782 s C3, exit1/evidence.valid/cleanup/logs true
(`WS/final-suite-ps51-4/summary.json`, source snapshot
`4c6000d28c4791d3890d841455445addffbb8521209575db23ec00e96f2c0250`).
Wait вернул 125 с пустым stdout и Open sharing violation при уже совместимом
ReadWrite/Delete sharing; owner завершился exit0 за 4.6118785 s с полным JSON
и cleanup/logs true. Это сохранённый failure, прежние 480 interruption,
остальные failures и pre-fix PASS также остаются в истории.

Read-Json повторяет только открытие при Win32 32, до 250 ms и не далее остатка
бюджета wait/run. ACL, missing-file и parse errors остаются ошибками;
принятая writer correction не меняется. Реальный handle освобождается после
verbose-сигнала первого неудачного открытия; постоянная блокировка и плохой
JSON возвращают 125, прежние writer/DELETE-reader/no-progress assertions сохранены.
Авторские directed: PS5.1 4/4 PASS, WSL diagnostic 1/1 PASS; PS7 первоначально
2 PASS + cancel FAIL125, после добавления записи ответа cancel/owner —
разрешённый affected replay и ранее не выполненная exact-command проверка 2/2 PASS.
Причина первого cancel 125 остаётся неизвестной и не объявляется исправленной.
Подробности, команды, hashes и cleanup: `WS/phase-5-fix-4-report.md`,
`WS/phase5-fix4-final-evidence.json`; 52 исходных случая и порядок сохранены.

После окончательного freeze координатору остаются ровно **PS5.1 full attempt5**,
**PS7 full attempt3**, **WSL full attempt1**, по одному, каждый до 1050 s.
Это именованное дальнейшее расширение для фактического read race в рамках
обычного сопровождения, без заявления о соблюдении исходных caps.
Общие распределённые caps, child 14 s/module 175 s, frontmatter statuses/commit
ranges и число тестов сохранены. Full runs выполняет только координатор
после settlement; дополнительных повторений не выделено. Итоговая приёмка
нового снимка остаётся pending.
