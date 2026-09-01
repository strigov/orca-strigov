---
slug: todo-concurrency-csv-import
created: 2026-09-01
status: in-progress
orca_run: run_20196664d76c
phases:
  - id: Ф1
    scope: "Межпроцессная блокировка всех read-modify-write операций todo и стресс-проверка 8×25"
    status: done
    commits: "4fd3316.."
  - id: Ф2
    scope: "CSV-команда import PATH с транзакционной валидацией и слиянием по правилам fixture"
    status: in-progress
verify:
  - "python3 -m pytest -q spikes/fixture/tests"
---

## Goal

Сделать файловое todo-хранилище безопасным для конкурирующих процессов: `add`, `complete` (CLI `done`), `remove` и `edit` должны выполнять весь цикл read-modify-write под одной эксклюзивной `fcntl.flock` на стабильном соседнем lock-файле, при этом `list_items` остаётся неблокирующим читателем, а существующая атомарная запись temp+`os.replace` сохраняется.

Добавить в `spikes/fixture/todo_export.py` команду `import PATH`, которая полностью валидирует UTF-8 CSV до изменения хранилища, затем под тем же lock-слоем сливает строки по `id` строго по `docs/fixture-import-rules.md`, атомарно сохраняет результат и не меняет существующие CLI-контракты todo и CSV-экспорта.

## Acceptance criteria

- Одновременный запуск ровно 8 процессов, каждый из которых выполняет 25 вызовов `add`, завершается без ошибок и оставляет валидный JSON-массив ровно из 200 элементов с уникальными `id`, равными `1..200`.
- `add`, CLI `done`/функция `complete`, `remove` и `edit` удерживают одну эксклюзивную блокировку от чтения до завершения атомарной записи; блокировка освобождается при нормальном возврате, `KeyError` и исключении записи, а `list`/`list_items` не ожидает и не создаёт блокировку.
- `_save_items()` продолжает записывать через temp-файл в каталоге цели, `fsync` и `os.replace`; существующие тесты сохранения старых байтов и удаления temp-файла при сбое проходят без изменения своих ожиданий.
- `python3 todo_export.py import PATH` для валидного CSV обновляет существующие элементы без перестановки, добавляет отсутствующие `id` в конец в порядке CSV, сохраняет неупомянутые элементы, применяет последнюю строку при повторном `id` и печатает результаты в порядке строк CSV.
- Любая договорная ошибка входного CSV возвращает код `2`, оставляет stdout пустым, пишет ровно одну строку stderr с номером первой невалидной строки и сохраняет байты todo-хранилища без изменений; CSV только с корректным заголовком возвращает `0`, ничего не печатает и не переписывает хранилище.
- Существующие команды `todo.py add/list/done/remove/edit`, их аргументы и `repr(dict)`-вывод, а также `todo_export.py [--out PATH] [--open]` и формат экспорта остаются неизменными; полный fixture-набор pytest проходит.

## Non-goals / deferred

- Блокировка чтения `list_items`, snapshot-изоляция нескольких чтений или гарантия того, увидит читатель состояние до либо после конкретного конкурентного коммита.
- Замена `fcntl.flock` на кроссплатформенную библиотеку, поддержка Windows, distributed lock для сетевых хранилищ либо защита от процессов, которые игнорируют advisory lock.
- Удаление lock-файла после операции, очистка «старых» lock-файлов или хранение данных внутри `<хранилище>.lock`.
- Нормализация/`resolve()` пути блокировки, объединение блокировок для разных символьных, жёстких или иных алиасов одного файла.
- Другие форматы импорта, иные заголовки или значения `done`, автоматическое переназначение `id`, частичный импорт валидного префикса либо потоковая запись до окончания валидации.
- Исправление повреждённого JSON, миграция схемы или новая политика для уже существующих дубликатов `id` в вручную изменённом хранилище.
- Изменение `spikes/fixture/README.md`, создание `docs/ARCHI.md`, новые зависимости, упаковка fixture в пакет или рефакторинг существующего CLI за пределами необходимой ветки `import`.

## Global Constraints

- Все изменяющие операции (`add`/`done`/`remove`/`edit`) выполняют read-modify-write под межпроцессной блокировкой — `fcntl.flock` на файле `<хранилище>.lock` рядом с хранилищем.
- Блокировка снимается всегда, включая исключения.
- Чтение (`list`) без блокировки.
- Атомарная запись temp+rename сохраняется.
- Существующие тесты атомарности не должны сломаться.
- Стресс-тест: 8 процессов × 25 `add` одновременно → ровно 200 элементов с уникальными id `1..200` и валидный JSON.
- Команда `import PATH` в `todo_export.py`: импорт CSV (колонки `id,text,done`) в то же хранилище.
- Правила дедупликации и слияния при совпадении id и поведение на невалидной строке — СТРОГО по `docs/fixture-import-rules.md`, не придумывать.
- Тесты межпроцессные, в стиле существующих.
- CLI-контракт `add/list/done/remove/edit` и форматы вывода не менять.
- Это третий smoke-прогон протокола `orca-dev` на fixture-репозитории; работать по протоколу полностью, без сокращений.
- No speculative features or dependencies.

## Files

### Ф1 — блокировка todo-хранилища

- `spikes/fixture/todo.py` — добавить соседний lock-path/context manager и обернуть им полный read-modify-write каждой из четырёх изменяющих функций, не меняя `_save_items()` и CLI.
- `spikes/fixture/tests/test_concurrency.py` — создать детерминированные тесты lock-path, освобождения lock при исключении, отсутствия lock у чтения и стресс-сценария 8 процессов × 25 `add`.
- `spikes/fixture/tests/test_storage.py` — существующий неизменяемый регрессионный набор атомарной temp+rename записи.
- `spikes/fixture/tests/test_cli.py` — существующий неизменяемый межпроцессный набор контрактов `add/list/done/remove/edit`.

### Ф2 — импорт CSV

- `spikes/fixture/todo_export.py` — добавить приватные parse/merge/import helpers и CLI-ветку `import PATH`, используя storage и lock helpers из `todo.py`.
- `spikes/fixture/tests/test_import.py` — создать межпроцессные тесты успешного слияния, повторных `id`, порядка, вывода, header-only no-op и всех классов договорных ошибок без частичной записи.
- `spikes/fixture/tests/test_export.py` — существующий неизменяемый регрессионный набор `--out`, `--open`, stdout и защиты активного хранилища.
- `docs/fixture-import-rules.md` — read-only источник импортного контракта; реализация и тесты его не изменяют.

## Contracts

### Существующее хранилище и форма данных

Текущие интерфейсы `spikes/fixture/todo.py` сохраняются:

```python
_DEFAULT_TODO_FILE: Path = Path(__file__).resolve().with_name("todo.json")

def _storage_path() -> Path: ...
def _load_items(path: Path) -> list[dict]: ...
def _save_items(path: Path, items: list[dict]) -> None: ...
def _next_id(items: list[dict]) -> int: ...

def add(text: str) -> dict: ...
def complete(item_id: int) -> dict: ...
def remove(item_id: int) -> dict: ...
def edit(item_id: int, text: str) -> dict: ...
def list_items(show_done: bool = True) -> list[dict]: ...
def main(argv: list[str] | None = None) -> int: ...
```

Хранилище — UTF-8 JSON без envelope, верхний уровень — список. Каждый элемент имеет ровно следующую форму:

```python
{"id": int, "text": str, "done": bool}
```

Типы проверяются существующим `_load_items()` строго (`type(...) is ...`); отсутствующий, синтаксически/структурно повреждённый или не-UTF-8 файл читается как `[]`. `_next_id()` остаётся `max(existing id, default=0) + 1`. `_save_items()` остаётся lock-agnostic: он сериализует весь список во временный файл в `path.parent`, выполняет `flush()`, `os.fsync()`, закрытие и `os.replace()`, а незаменённый temp удаляет в `finally`. Блокировку нельзя переносить внутрь `_save_items()`, иначе read и вычисление нового состояния останутся вне критической секции и изменится наблюдаемое поведение прямых storage-тестов.

### Планируемый lock-слой

В `todo.py` добавляются приватные интерфейсы:

```python
def _lock_path(storage_path: Path) -> Path: ...

@contextmanager
def _storage_lock(storage_path: Path) -> Iterator[None]: ...
```

`_lock_path(storage_path)` возвращает `storage_path.with_name(storage_path.name + ".lock")`: для `/tmp/todo.json` это ровно `/tmp/todo.json.lock`, в том же каталоге; относительность пути сохраняется, `resolve()` не выполняется.

`_storage_lock()` открывает/создаёт стабильный lock-файл без усечения, берёт `fcntl.flock(fd, fcntl.LOCK_EX)`, выполняет тело context manager и после успешного получения lock обязательно вызывает `fcntl.flock(fd, fcntl.LOCK_UN)` в `finally`; затем дескриптор закрывается. Lock-файл не удаляется. Ошибка получения lock пробрасывается, а исключение из чтения, поиска элемента, `_save_items()` или пользовательского тела не препятствует unlock.

Каждая из `add()`, `complete()`, `remove()` и `edit()` один раз вычисляет `path = _storage_path()`, входит в `_storage_lock(path)` до `_load_items(path)` и выходит только после `_save_items(path, items)` либо исключения. Возвращаемый dict и `KeyError(item_id)` остаются прежними. `list_items()` вызывает только `_load_items(_storage_path())` и фильтрацию: lock-файл не открывается и `flock` не вызывается.

### Существующий todo CLI

- `python3 spikes/fixture/todo.py add TEXT` печатает один `repr(dict)` и `\n`.
- `python3 spikes/fixture/todo.py done ID` вызывает `complete(ID)` и печатает обновлённый dict.
- `python3 spikes/fixture/todo.py remove ID` печатает удалённый dict.
- `python3 spikes/fixture/todo.py edit ID TEXT` печатает обновлённый dict.
- `python3 spikes/fixture/todo.py list [--open]` печатает по одному dict на строку в порядке JSON; `--open` исключает `done=True`.
- Для неизвестного `ID` у `done/remove/edit` сохраняется необработанный `KeyError`, ненулевой код процесса, пустой stdout и отсутствие записи; форматы argparse и успешный код `0` не меняются.

### Существующий CSV export

Сигнатуры `spikes/fixture/todo_export.py` и текущий экспорт остаются:

```python
def _write_rows(stream: TextIO, items: list[dict]) -> None: ...
def write_csv(stream: TextIO, show_done: bool = True) -> None: ...
def main(argv: list[str] | None = None) -> int: ...
```

Поверхность `python3 spikes/fixture/todo_export.py [--out PATH] [--open]` по-прежнему экспортирует заголовок `id,text,done`, значения `True`/`False`, порядок `list_items()`, `\n` как lineterminator и сохраняет текущий отказ перезаписывать активное todo-хранилище. Новая команда не вводит обязательный `export`-подкомандный префикс и не меняет разбор существующих успешных вызовов.

### Планируемые интерфейсы импорта

В `todo_export.py` добавляются приватные интерфейсы:

```python
class _CsvImportError(Exception):
    line_number: int

def _read_import_rows(path: Path) -> list[dict]: ...
def _merge_import_rows(items: list[dict], rows: list[dict]) -> list[dict]: ...
def _import_csv(path: Path) -> list[dict]: ...
```

`_read_import_rows()` открывает `PATH` в режиме чтения с `encoding="utf-8"` и `newline=""`, использует стандартный `csv`-парсер и полностью читает/валидирует файл до обращения к todo-хранилищу. Первая CSV-запись (строка 1) должна состоять ровно из полей `id`, `text`, `done` в этом порядке. Каждая следующая запись должна иметь ровно три поля; `id` преобразуется в `int` и должен быть `>= 1`, `text` сохраняется без преобразования и может быть пустым, `done` принимается только как точная регистрозависимая строка `True` либо `False` и преобразуется в `bool`.

Любая входная ошибка преобразуется во внутренний `_CsvImportError(line_number)`: отсутствующий/нечитаемый путь и отсутствующий/неверный заголовок относятся к строке 1; данные нумеруются начиная со строки 2, и сообщается первая невалидная CSV-запись. Текст ошибки, кроме обязательного однозначного номера, документом не фиксирован.

`_merge_import_rows(items, rows)` применяет уже валидированные строки последовательно и мутирует переданный storage-list:

- при существующем `id` меняются только `text` и `done`, позиция элемента сохраняется;
- при отсутствующем `id` создаётся dict с указанным `id` и дописывается в конец; переназначение запрещено;
- storage-элементы, не встречавшиеся в CSV, остаются без изменений;
- повторный `id` обновляет тот же элемент, поэтому финальное состояние задаёт последняя строка; новый элемент занимает позицию своего первого появления;
- возвращается список shallow-copy snapshots — по одному dict на каждую CSV-строку в исходном порядке, снятому сразу после применения этой строки. Поэтому повторный `id` даёт несколько строк stdout, а последняя из них отражает победившее значение.

Для уже существующих дубликатов `id` в вручную изменённом корректном JSON используется первое совпадение, как сейчас делают `complete/remove/edit`; отдельная дедупликация существующего хранилища не вводится.

`_import_csv(path)` сначала получает полный список из `_read_import_rows()`. Для файла только с заголовком он сразу возвращает `[]`, не вызывает `_save_items()` и не переписывает хранилище. Для непустого импорта он вычисляет `storage_path = todo._storage_path()`, входит в `todo._storage_lock(storage_path)`, внутри lock вызывает `todo._load_items(storage_path)`, `_merge_import_rows(...)` и ровно один `todo._save_items(storage_path, items)`, затем возвращает snapshots после успешного save. Логика JSON-сериализации и lock не дублируется в `todo_export.py`.

### CLI `import PATH`

- Новая поверхность: `python3 spikes/fixture/todo_export.py import PATH`; экспортные `--out`/`--open` к этой команде не относятся.
- При успехе `main()` печатает каждый snapshot через обычный `print(item)`, то есть ровно один `repr(dict)\n` на CSV-строку, и возвращает `0`.
- CSV только с заголовком даёт код `0`, пустые stdout/stderr и побайтово неизменное хранилище.
- При `_CsvImportError` `main()` ничего не печатает в stdout, пишет ровно одну строку stderr с `line_number` и возвращает `2`; todo-хранилище не читалось для ошибки валидации и остаётся побайтово неизменным.
- Печать начинается только после успешной атомарной записи. Исключения самого storage-слоя сохраняют его текущее поведение и не маскируются под ошибку CSV.

## Test strategy

### Ф1

- Создать `test_concurrency.py`, используя `tmp_path`, `monkeypatch`, `subprocess.Popen`, `sys.executable`, общий `TODO_FILE` и абсолютный путь/`sys.path` к fixture по образцу существующих `_run_cli()`/`_run_export()` helpers.
- Проверить `_lock_path(tmp_path / "todo.json") == tmp_path / "todo.json.lock"`; lock-файл создаётся рядом, не удаляется и не заменяет storage-файл.
- Подменить `todo.fcntl.flock` записывающим spy, выбросить исключение из тела `_storage_lock()` и проверить последовательность `LOCK_EX`, затем `LOCK_UN`; отдельным сценарием вызвать изменяющую операцию при сбое `_save_items()` и доказать, что другой процесс после исключения немедленно получает `LOCK_EX | LOCK_NB` на том же lock-файле.
- Параметризованно доказать, что `add`, `complete`, `remove` и `edit` выполняют load/save внутри активного `_storage_lock`, включая `KeyError` без save; для `list_items` подмена lock helper на исключение не должна срабатывать.
- Стресс-тест стартует ровно 8 долгоживущих Python-процессов. Каждый ждёт общий start-gate, затем в своём процессе 25 раз вызывает `todo.add()` с уникальным текстом; родитель открывает gate только после запуска всех восьми и ожидает каждый процесс с конечным timeout. После завершения тест делает `json.loads`, проверяет list-форму и строгую форму каждого элемента, `len == 200`, множество и отсортированный список `id == 1..200`, отсутствие повторов и 200 уникальных текстов.
- Не изменять `test_storage.py` и `test_cli.py`; их прохождение является регрессией атомарности и CLI. Цикл фазы: `python3 -m pytest -q spikes/fixture/tests/test_storage.py spikes/fixture/tests/test_cli.py spikes/fixture/tests/test_concurrency.py`, затем `python3 -m pytest -q spikes/fixture/tests`.

### Ф2

- Создать `test_import.py` с subprocess-helper, повторяющим существующий стиль: `TODO_FILE` указывает в `tmp_path`, cwd равен каталогу storage, запускается `sys.executable` с абсолютным `todo_export.py`, stdout/stderr захватываются как text.
- Один сквозной успешный сценарий засевает элементы до, между и после импортируемых `id`, а CSV содержит обновление существующего `id`, два новых `id` и повтор существующего/нового `id`. Проверить точный stdout по каждой строке, «последняя строка побеждает», неизменные позиции существующих элементов, порядок новых по первому появлению, сохранение неупомянутых элементов и валидный итоговый JSON.
- Отдельно проверить пустой `text` и CSV quoting для запятой/кавычек, не вводя собственного CSV-диалекта.
- Для CSV только с заголовком проверить код `0`, пустые stdout/stderr и побайтовую неизменность заранее форматированного storage; при отсутствующем storage он не должен создаваться.
- Параметризовать договорные ошибки: отсутствующий путь, нечитаемый путь (надёжный `IsADirectoryError`), пустой файл/неверный заголовок, неверное число колонок, нецелый `id`, `id < 1`, значение `done` вне `True/False`, а также валидная ранняя строка перед поздней невалидной. Для каждого случая проверить код `2`, пустой stdout, одну строку stderr с ожидаемым номером первой ошибки и исходные storage bytes без изменений.
- Детерминированным direct-helper тестом подменить `todo._storage_lock`, `_load_items` и `_save_items`, чтобы подтвердить: непустой `_import_csv()` вызывает load/merge/save только внутри общего lock; header-only вызов не входит в lock и не вызывает save.
- Не изменять `test_export.py`; целевой цикл: `python3 -m pytest -q spikes/fixture/tests/test_export.py spikes/fixture/tests/test_import.py`, затем `python3 -m pytest -q spikes/fixture/tests`.

## Risks / unknowns / assumptions

- `fcntl.flock` доступен в проверенном POSIX-окружении, но отсутствует на Windows; это прямое следствие обязательного механизма, а не переносимая абстракция.
- `flock` advisory: корректность гарантируется только для `todo.py` и `todo_export.py`, которые используют общий `<хранилище>.lock`. Разные строковые алиасы одного storage могут породить разные lock-файлы; нормализация пути не запрошена.
- Lock-файл остаётся на диске намеренно. Удаление после unlock создало бы гонку, при которой процессы могли бы блокировать разные inode одного имени.
- `list_items()` без lock может вернуть предыдущий либо следующий целостный snapshot относительно конкурентной записи. Частичный JSON не наблюдается благодаря сохранённому temp+`os.replace`, но linearizable read контракт не заявлен.
- Фраза правил о stdout «для каждого добавленного или обновлённого элемента в порядке строк CSV» трактуется буквально как одна строка вывода на каждую data-row, включая повторный `id`; чтобы поздняя мутация не изменила ранний вывод, возвращаются snapshots. Финальное storage-состояние при этом всегда задаёт последняя строка.
- Для отсутствующего/нечитаемого `PATH` правила объединяют ошибку файла с ошибками CSV и требуют номер строки; план фиксирует строку 1 как первую ожидаемую строку заголовка. Иной текст stderr не фиксируется.
- Правила не задают поведение для уже существующих дубликатов `id`; принимается действующий first-match контракт `complete/remove/edit`, без очистки либо ошибки.
- `docs/ARCHI.md` в репозитории отсутствует, поэтому архитектурная документация не входит в фазы. `docs/fixture-import-rules.md` разрешён из корня репозитория и является единственным источником merge/error semantics.
- Базовое окружение проверено: Python `3.10.11`, pytest `9.0.3`, `python3 -m pytest -q spikes/fixture/tests` — `18 passed`. Конфигурации lint/typecheck/build в репозитории нет, поэтому frontmatter `verify` содержит единственный воспроизводимый полный pytest-прогон.
- Фазы намеренно последовательны: хотя их write-наборы не пересекаются, Ф2 обязана потреблять `_storage_lock()` из Ф1 и не должна самостоятельно реализовывать lock/serialization; условие `parallel_group` не выполнено.

## Ф1: Межпроцессная блокировка todo-операций

**Files in this phase:**
- Create: `spikes/fixture/tests/test_concurrency.py` — lock-unit tests и межпроцессный stress harness.
- Modify: `spikes/fixture/todo.py` — `_lock_path`, `_storage_lock` и критические секции четырёх мутаций.
- Test: `spikes/fixture/tests/test_concurrency.py`, `spikes/fixture/tests/test_storage.py`, `spikes/fixture/tests/test_cli.py`.

**Interfaces:**
- Consumes: `_storage_path() -> Path`; `_load_items(path: Path) -> list[dict]`; `_save_items(path: Path, items: list[dict]) -> None`; `_next_id(items: list[dict]) -> int`; `add(text: str) -> dict`; `complete(item_id: int) -> dict`; `remove(item_id: int) -> dict`; `edit(item_id: int, text: str) -> dict`; `list_items(show_done: bool = True) -> list[dict]`; JSON-форма `{"id": int, "text": str, "done": bool}`.
- Produces: `_lock_path(storage_path: Path) -> Path`; `_storage_lock(storage_path: Path) -> Iterator[None]`; те же публичные сигнатуры `add/complete/remove/edit/list_items` с locking semantics из `## Contracts` и без изменения return/exception/CLI contracts.

1. Добавить только стандартные `fcntl`, context-manager и typing/collections imports, необходимые двум приватным helpers; сторонних зависимостей и платформенного fallback не вводить.
2. Реализовать `_lock_path()` без `resolve()` и `_storage_lock()` на отдельном стабильном `<storage>.lock`, с `LOCK_EX` до `yield` и явным `LOCK_UN` в `finally` после успешного acquire.
3. Обернуть в одну критическую секцию каждую последовательность `_load_items` → поиск/изменение → `_save_items` в `add`, `complete`, `remove`, `edit`. Не брать lock только вокруг `_save_items` и не создавать вложенные lock-acquire.
4. Оставить `_save_items()` и `list_items()` функционально неизменными; unknown-id `KeyError` должен выходить через context-manager и освобождать lock без записи.
5. Создать детерминированные lock-тесты и stress harness по разделу `Test strategy`; subprocess-worker должен импортировать реальный `todo.py`, а не переimplementировать выдачу ID или запись.
6. Выполнить фазовый и полный pytest-циклы. Фаза готова к отдельному коммиту только при 200/200 stress-результате, зелёных старых тестах атомарности/CLI и отсутствии изменений файлов Ф2.

## Ф2: Команда `import PATH` и слияние CSV

**Files in this phase:**
- Create: `spikes/fixture/tests/test_import.py` — subprocess import contract и direct-helper wiring tests.
- Modify: `spikes/fixture/todo_export.py` — CSV validation/merge helpers и CLI `import PATH`.
- Test: `spikes/fixture/tests/test_import.py`, `spikes/fixture/tests/test_export.py`, `spikes/fixture/tests/test_concurrency.py`.
- Read-only: `docs/fixture-import-rules.md` — frozen import rules.

**Interfaces:**
- Consumes: `todo._storage_path() -> Path`; `todo._storage_lock(storage_path: Path) -> Iterator[None]`; `todo._load_items(path: Path) -> list[dict]`; `todo._save_items(path: Path, items: list[dict]) -> None`; `todo.list_items(show_done: bool = True) -> list[dict]`; `_write_rows(stream: TextIO, items: list[dict]) -> None`; `write_csv(stream: TextIO, show_done: bool = True) -> None`; `main(argv: list[str] | None = None) -> int`; правила `docs/fixture-import-rules.md`.
- Produces: `_CsvImportError` с `line_number: int`; `_read_import_rows(path: Path) -> list[dict]`; `_merge_import_rows(items: list[dict], rows: list[dict]) -> list[dict]`; `_import_csv(path: Path) -> list[dict]`; CLI `todo_export.py import PATH` с кодами/выводом из `## Contracts`; существующие export signatures и surface без изменений.

1. Добавить приватную ошибку с номером строки и parser `_read_import_rows()`, который открывает UTF-8 CSV, проверяет точный header и все data rows до любого чтения/изменения todo storage.
2. Реализовать `_merge_import_rows()` строго по документу: update in place без перестановки, append только для нового `id`, untouched rows preserve, last duplicate wins, snapshots сохраняют CSV-порядок вывода.
3. Реализовать `_import_csv()` как validate-first, затем один lock/read/merge/atomic-save transaction через helpers Ф1; header-only CSV вернуть как no-op без save. Не копировать JSON/temp/`os.replace`/`flock` код в `todo_export.py`.
4. Расширить `main()` отдельной поверхностью `import PATH`, сохранив старый export parser и его успешные вызовы. Ошибки CSV преобразовать только в договорный код `2`/одну stderr-строку; печатать snapshots лишь после успешного save.
5. Создать межпроцессные и wiring-тесты из `Test strategy`, включая точный порядок stdout для повторных `id` и byte-for-byte rollback для первой невалидной строки после валидного префикса.
6. Выполнить фазовый и полный pytest-циклы. Фаза готова к отдельному коммиту только при зелёных import, export, concurrency и всех ранее существовавших fixture-тестах.
