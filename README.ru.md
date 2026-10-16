<p align="center">
  <a href="./README.md">English</a> · <a href="./README.ru.md">Русский</a>
</p>

<p align="center">
  <img src="./assets/readme/hero-ru.svg" width="100%" alt="orca-strigov: координатор отдаёт код, проверки и ревью отдельным агентам">
</p>

# orca-strigov 2.0

Тонкий плагин для Codex и Claude Code поверх штатной оркестрации [Orca](https://orca.dev). Один скилл `orca-dev` ведёт разработку по SDD через supervised-воркеров Orca: спека → план → TDD-фазы → двойное ревью (Opus, затем Astra) → коммит, с фиксированными пресетами моделей. Без хуков, квитанций и машины состояний: любой кап или сбой заканчивается объявленным фоллбэком или одним вопросом пользователю.

Дизайн и критерии приёмки: [docs/specs/2026-10-14-orca-dev-v2-design.md](docs/specs/2026-10-14-orca-dev-v2-design.md).

## Установка

Нужны Orca 1.4.224+, Python 3.10+ (`python3`; Windows — `py -3`), git и залогиненные `codex`, `claude`, `agy`.

1. Штатные скиллы Orca: `orca skills install --skill orchestration --skill orca-cli --agent codex,claude-code`
2. Плагин: `git clone https://github.com/strigov/orca-strigov.git`
3. Проверки и trust проекта: `python3 orca-strigov/install.py --repo /path/to/project` (Windows: `py -3 orca-strigov\install.py --repo C:\path\to\project`). Пишет только `~/.claude.json` и `~/.gemini/antigravity-cli/settings.json`, ничего не удаляет, перечисляет старые копии.
4. Codex: попросить Codex «Use plugin-creator to install the plugin from /abs/path/orca-strigov into my personal marketplace», затем `codex plugin add orca-strigov@personal`; `codex plugin list` показывает `2.0.0`. Начать новую сессию.
5. Claude Code: `claude --plugin-dir /abs/path/orca-strigov` или `/plugin install orca-strigov@<ваш локальный marketplace>`.

## Запуск

- Codex: `$orca-dev добавь флаг --version`
- Claude Code: `/orca-strigov:orca-dev добавь флаг --version`

Маленькие задачи (не больше 2 файлов кода, без схем, безопасности и публичных API, слияние уже принятых веток) идут быстрым путём: исполнитель → проверки → ревью Opus → ревью Astra → коммит. Остальное: спека (вы отвечаете «ок») → план → фазы → финальное ревью. Чтобы продолжить прерванную работу, назовите план или его slug.

## Роли

| роль | модель |
|---|---|
| спека и план: пишет / правит | claude `opus` `xhigh` / `high` |
| ревью спеки и плана | codex `gpt-6-astra` `xhigh` |
| исполнитель (backend, быстрый путь) | agy `gemini-3.8-flash-high`; фоллбэк codex `gpt-6-luna` `max` |
| исполнитель (`hard: true`) и единственная эскалация | codex `gpt-6.1-sol` `high` |
| исполнитель (frontend) | claude `opus` `high` или `sonnet` `medium` для ≤2 файлов |
| ревью фазы 1 и финальное ревью | claude `opus` `high` |
| ревью фазы 2 | codex `gpt-6-astra` `high` |

Подробности: [roles.md](skills/orca-dev/roles.md). Механика запуска: [launch.md](skills/orca-dev/launch.md).

## Состав

```text
skills/orca-dev/   SKILL.md, roles.md, launch.md, prompts/ (11 брифов)
bin/orca_dev.py    brief, spawn, ready, close
install.py         проверки, trust репозитория, предупреждения о старых копиях
tests/             python3 -m unittest discover tests
```

## Переход с 1.x

Хуков, квитанций, ledger'ов и вендоренных скиллов Orca больше нет. Удалите старые копии, которые перечисляет `install.py`, или ответьте `y` на вопрос координатора при первом запуске.
