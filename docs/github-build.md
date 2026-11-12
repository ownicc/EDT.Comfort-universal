# Сборка в GitHub Actions

Workflow **Build p2 archive** (`.github/workflows/build.yml`) запускается при push в
`master` и вручную через **Actions → Build p2 archive → Run workflow → master**.

Сборка выполняется на Ubuntu 24.04 с JDK 21, Tycho 5 и Maven Wrapper.
Классы плагина компилируются для Java 17. Целевая платформа остаётся Windows x86_64
из `target/tp.target`: она предоставляет Windows SWT API при компиляции.
Один ZIP используется для установки на разных ОС; совместимость отдельных функций
проверяется в EDT каждой ОС. Локальная установка EDT на runner не требуется.

Перед сборкой выполняется `python3 tests/tycho-build/run.py`: три синтетических
бандла, зависимости, ресурсы, Java 17 и упаковка p2. Затем
`python3 scripts/build_tycho.py` собирает исходники Comfort и установочный архив.
Maven и зависимости кэшируются в `.tmp/maven`. Версия Maven и SHA-256 закреплены
в `.mvn/wrapper/maven-wrapper.properties`; версии Actions закреплены коммитами.

После успешной сборки в **Artifacts** доступны:

- `comfort-p2-<commit SHA>`: `tormozit.comfort.zip`, `SHA256SUMS` и `commit.txt`.
- `comfort-build-logs-<commit SHA>`: журналы Maven и синтетической проверки,
  команды запуска и сведения о JDK. Журналы сохраняются также при ошибке сборки.

Архив установки хранится 30 дней, журналы — 14 дней.
Скачайте artifact, распакуйте внешний архив GitHub и выберите **tormozit.comfort.zip**
в EDT: **Справка → Установить новое ПО… → Добавить → Архив…**.

Для повторения сборки локально нужны JDK 21+ и Python 3.9+:

```bash
python3 scripts/build_tycho.py
```

Результат: `build/comfort.site/tormozit.comfort.zip`.
Журналы: `.tmp/tycho-runs/<дата-время>/`.

Сборка не публикует релизы или p2-сайт. Старый `deploy-site.yml`, смешивавший
сборку и публикацию, заменён этим workflow. Существующие ручные `publish.yml`
и `publish-docs.yml` сохраняют прежнее поведение и не используют новый artifact.
Публикацию проверенного artifact следует настраивать отдельной задачей.

Регрессионная проверка `VerifyError` требует полного набора бандлов EDT 2026.2
и запускается отдельно; синтетическая проверка упаковки её не заменяет:

```bash
EDT_BUNDLE_POOL=/путь/к/edt/plugins python3 tests/doc-comment-frames/run.py
```
