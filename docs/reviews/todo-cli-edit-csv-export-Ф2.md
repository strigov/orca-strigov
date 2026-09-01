# Review: todo-cli-edit-csv-export — Ф2

- **Date**: 2026-09-01
- **Phase scope**: Отдельный модуль экспорта CSV `spikes/fixture/todo_export.py` с собственным CLI
- **Base commit**: `2843720` (`284372045b54ac1a311836e2d921ed76c7f861e4`)
- **Rounds**: 2 (primary review 4.1 + control review 4.2)
- **Outcome**: CLEAN (clean after round 2)

## Executive Summary

Фаза Ф2 реализует отдельный CLI-модуль `spikes/fixture/todo_export.py` и межпроцессный набор тестов `spikes/fixture/tests/test_export.py` для экспорта задач в формат CSV. Процесс ревью успешно завершён за два раунда:

- **Раунд 1**: `review-primary` выдал `REVIEW_OK` с 4 замечаниями категории NIT (F1-B2..F1-B5). `review-control` зафиксировал блокирующее замечание `DATA_LOSS` (F1-B1): открытие файла назначения `--out` в режиме `"w"` до чтения задач через `todo.list_items()` приводило к усечению и безвозвратной потере активного хранилища `TODO_FILE`, если пути совпадали или были связаны симлинком/хардлинком.
- **Одобренная оператором поправка плана (F1-B1)**: План был обновлён (коммит `8b0e45e`, контракт C6 и Test strategy Ф2), закрепив:
  1. Обязательное чтение элементов хранилища через `todo.list_items(show_done=not ns.open)` **до** любого открытия файла на запись;
  2. Защитную проверку совпадения пути `--out` с активным `TODO_FILE` через `Path.resolve()` и `os.path.samefile()` (при существовании обоих файлов) с использованием единственного разрешённого приватного вызова `todo._storage_path()`;
  3. При совпадении путей: завершение с кодом `2`, вывод ровно одной строки в `sys.stderr` (`todo_export: refusing to overwrite the active storage: <ns.out>`), отсутствие вывода в `stdout` и отказ от любых операций записи;
  4. Добавление обязательного межпроцессного теста на побайтовое сохранение хранилища при совпадении путей.
- **Авторизованная правка и реализация**: Имплементатор выделил вспомогательную функцию `_write_rows()`, перестроил поток выполнения в `main()`, реализовал защитный guard и добавил тест `test_export_out_same_as_storage_refuses_overwrite_and_preserves_bytes`.
- **Раунд 2**: Оба ревьюера (`review-primary` и `review-control`) независимо выполнили полный комплекс статических и динамических проверок (включая межпроцессные probe для абсолютных/относительных путей, симлинков, хардлинков, регистра и отсутствующих файлов) и выставили вердикты **`REVIEW_OK`**, **`SPEC: OK`**, **`QUALITY: OK`**.
- **Результаты тестов и Gate**:
  - `spikes/fixture/tests/test_export.py`: 7 passed
  - `spikes/fixture/tests/test_storage.py spikes/fixture/tests/test_cli.py`: 7 passed (регрессия C3 цела)
  - `spikes/fixture/tests`: 14 passed

## Findings history

| id | reviewer | finding | decision | final status |
| --- | --- | --- | --- | --- |
| F1-B1 | review-control | plan-mandated DATA_LOSS: --out, совпадающий или алиасный активному TODO_FILE, усекает хранилище до чтения. | ACCEPTED (Operator-approved plan amendment) | fixed |
| F1-B2 | review-primary | Falsy-проверка if ns.out для пустого значения --out. | NIT | deferred |
| F1-B3 | review-primary | Мёртвая ветка unlink в тесте отсутствующего хранилища. | NIT | deferred |
| F1-B4 | review-primary | Покрытие lineterminator зависит от единственного --out-теста. | NIT | deferred |
| F1-B5 | review-primary | CSV-строки записываются списками вместо кортежей из текста плана. | NIT | deferred |
| F2-B1 | review-primary | Сообщение защитного отказа может содержать больше одной stderr-строки, если совпадающий путь --out включает перевод строки. | NIT | deferred |
| F2-B2 | review-primary | Тест byte-preservation не фиксирует отсутствие открытия назначения через mtime/inode, хотя контракт требует только побайтовую неизменность. | NIT | deferred |

## Deferred

Следующие замечания признаны неблокирующими (NIT) и зафиксированы для возможной будущей доработки:

1. **F1-B2** (`spikes/fixture/todo_export.py:31`): Использование `if ns.out:` вместо `if ns.out is not None:`. При пустой строке `--out ""` (falsy) CLI выводит CSV в stdout с кодом 0 вместо возбуждения ошибки `FileNotFoundError` при `open("", "w")`.
2. **F1-B3** (`spikes/fixture/tests/test_export.py:125-126`): Избыточный вызов `if storage_path.exists(): storage_path.unlink()`, так как фикстура `tmp_path` всегда гарантирует уникальный чистый каталог.
3. **F1-B4** (`spikes/fixture/tests/test_export.py:33-36`): Регрессия `lineterminator="\n"` в stdout-тестах маскируется декодированием universal newlines в `subprocess.run(text=True)`; строгое соблюдение окончаний строк сейчас проверяется только в тесте записи в файл (`--out`).
4. **F1-B5** (`spikes/fixture/todo_export.py:14,16`): Передача списков `[item["id"], ...]` в `csv.writer` вместо кортежей, указанных в плане (семантически идентично).
5. **F2-B1** (`spikes/fixture/todo_export.py:40`): Путь `--out`, содержащий символ перевода строки `\n` и совпадающий с хранилищем, приведёт к выводу нескольких строк в stderr вместо одной (экзотический граничный случай; решение при необходимости — экранирование `repr(ns.out)`).
6. **F2-B2** (`spikes/fixture/tests/test_export.py:164-177`): Тест byte-preservation проверяет побайтовую идентичность содержимого, но не сравнивает `st_mtime_ns` / `st_ino` для явного подтверждения отсутствия открытия дескриптора на запись (контракт требует только побайтовую сохранность, факт отсутствия открытия проверен вручную).

## Nits (informational)

- В коде соблюдены все ограничения по зависимостям (только стандартная библиотека Python) и границам изменений: файлы `spikes/fixture/todo.py` и существующие тесты Ф1 не модифицировались.
- Вся публичная поверхность модуля ограничена `main` и `write_csv`. Единственное приватное обращение `todo._storage_path()` авторизовано поправкой плана F1-B1 и используется строго для проверки безопасности пути `--out`.

## Open at accept

None. (Outcome: **CLEAN** / clean after round 2, все блокирующие замечания закрыты, обе проверки завершены со статусом `REVIEW_OK`).
