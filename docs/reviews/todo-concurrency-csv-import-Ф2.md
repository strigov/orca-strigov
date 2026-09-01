# Review: todo-concurrency-csv-import — Ф2

- **Date**: 2026-09-02
- **Phase scope**: CSV-команда import PATH с транзакционной валидацией и слиянием по правилам fixture
- **Base commit**: f53f106ecd148142d22c0922f6b563b77c503344
- **Rounds**: 2 (primary review 4.1 + control review 4.2)
- **Outcome**: CLEAN

## Findings history

| id | reviewer | finding | decision | final status |
| --- | --- | --- | --- | --- |
| Ф2-F1-D1 | review-primary | Transient ledger не относится к файлам Ф2 и исключается из phase commit. | DEFER | deferred |
| Ф2-F1-D2 | review-primary | Поздний UnicodeDecodeError может сообщать последнюю успешно декодированную физическую строку вместо 1. | DEFER | deferred |
| Ф2-F1-D3 | review-primary | reader.line_num считает физические строки, а не CSV-записи. | DEFER | deferred |
| Ф2-F1-D4 | review-primary | int() принимает расширенные лексические формы id. | DEFER | deferred |
| Ф2-F1-D5 | review-primary | Пустая строка после header отклоняется как запись с неверным числом колонок. | DEFER | deferred |
| Ф2-F1-D6 | review-primary | Stable lock-файл остаётся вне .gitignore; изменение вне Ф2. | DEFER | deferred |
| Ф2-F1-N1 | review-primary | Недостижимый except _CsvImportError: raise. | NIT | deferred |
| Ф2-F1-N2 | review-primary | Повторное использование loop variable item ухудшает читаемость merge. | NIT | deferred |
| Ф2-F1-N3 | review-primary | choices для positional command повторно валидирует уже распознанный import. | NIT | deferred |
| Ф2-F1-N4 | review-primary | Главный --help не упоминает import surface. | NIT | deferred |
| Ф2-F1-N5 | review-primary | Error tests проверяют номер строки substring-ассертом вместо точного stderr. | NIT | deferred |
| F1-B1-Ф2 | review-control | Стандартный csv.reader field-size limit гарантированно отклоняет договорно валидный text длиннее 131072 символов. | ACCEPTED | fixed |
| Ф2-F2-D1 | review-control | csv.field_size_limit является процессно-глобальным состоянием и приватный helper не гарантирует корректность перекрывающихся thread-вызовов; штатный CLI одно-поточный. | DEFER | deferred |

Final primary r2 verdict:

REVIEW_OK
SPEC: OK
QUALITY: OK

Final control r2 verdict:

REVIEW_OK
DEFER:
- `csv.field_size_limit` — процессно-глобальное состояние: перекрывающиеся вызовы `_read_import_rows()` из нескольких потоков могут чередовать сохранение и восстановление лимита и оставить устаревшее значение либо вернуть старый лимит во время ещё идущего разбора. Штатный CLI-путь одно-поточный, helper приватный, поэтому это не нарушает критерии приёмки Ф2 и не блокирует исправление — spikes/fixture/todo_export.py:21

## Deferred

- **Ф2-F1-D1**: Transient ledger не относится к файлам Ф2 и исключается из phase commit.
- **Ф2-F1-D2**: Поздний UnicodeDecodeError может сообщать последнюю успешно декодированную физическую строку вместо 1.
- **Ф2-F1-D3**: reader.line_num считает физические строки, а не CSV-записи.
- **Ф2-F1-D4**: int() принимает расширенные лексические формы id.
- **Ф2-F1-D5**: Пустая строка после header отклоняется как запись с неверным числом колонок.
- **Ф2-F1-D6**: Stable lock-файл остаётся вне .gitignore; изменение вне Ф2.
- **Ф2-F2-D1**: `csv.field_size_limit` — процессно-глобальное состояние: перекрывающиеся вызовы `_read_import_rows()` из нескольких потоков могут чередовать сохранение и восстановление лимита и оставить устаревшее значение либо вернуть старый лимит во время ещё идущего разбора. Штатный CLI-путь одно-поточный, helper приватный, поэтому это не нарушает критерии приёмки Ф2 и не блокирует исправление — spikes/fixture/todo_export.py:21

## Nits (informational)

- **Ф2-F1-N1**: Недостижимый except _CsvImportError: raise.
- **Ф2-F1-N2**: Повторное использование loop variable item ухудшает читаемость merge.
- **Ф2-F1-N3**: choices для positional command повторно валидирует уже распознанный import.
- **Ф2-F1-N4**: Главный --help не упоминает import surface.
- **Ф2-F1-N5**: Error tests проверяют номер строки substring-ассертом вместо точного stderr.
