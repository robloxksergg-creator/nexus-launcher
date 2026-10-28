# MODRINTH-MEDIA-FIX-AUDIT — NEXUS v21

Дата: 2026-10-08. Точечное исправление обработки контента, без изменения визуальной системы, Modrinth provider, галереи или launcher engine.

## A. Root cause

Аудит выполнен до изменения renderer; исходный промежуточный отчёт сохранён в `D:/nexus2/markdown-audit/READ-ONLY-AUDIT.md`. Проверялся текущий код v20, а не предположение о версии из описания задачи.

Обычный `[Discord](https://discord.gg/test)` уже распознавался Qt как ссылка. Ошибка находилась в `DescriptionParser.handle_starttag('img')`: внутри HTML `<a><img></a>` обработчик добавлял пустые строки и «Изображение недоступно.» между `[` и `](URL)`. Получался некорректный многострочный Markdown с видимыми скобками и URL вместо понятной кнопки-ссылки.

Дополнительная проверка чистого QTextDocument выявила ещё два случая: Qt Markdown терял адрес ссылки, оборачивающей изображение, а `![](URL)` мог не создавать изображение. Замена фрагмента на loading/failure text также сбрасывала anchor.

Почему Gallery работала: она берёт URL непосредственно из `gallery[]` и не проходит через этот конвертер. В v20 body/gallery/icons уже используют один `mod_media.fetch_media` и один кэш; отдельный HTTP client добавлять не требовалось.

Почему 3D Skin Layers не показывал изображения body: реальные данные API содержат **ноль** `cdn.modrinth.com` URL в описании. Авторские изображения размещены на `tr7zw.github.io` и `raw.githubusercontent.com`. Их блокирование соответствует заданной политике. При этом его единственный gallery image находится на разрешённом CDN и отображается.

Исходные API payload и старый результат конвертации: `D:/nexus2/markdown-audit/3dskinlayers.json`, `3dskinlayers-before.md`, аналогичные файлы для JEI, Antique Atlas и Cobblemon. Источник — существующий CatalogProvider и Project API, без скачивания HTML сайта.

## B. Before

API body → HTMLParser с конвертацией в Markdown → Qt Markdown parse → image fragments → URL policy → общий fetch/cache → безопасный decode → QTextDocument resource.

HTML badge внутри anchor ломался на этапе HTMLParser. Пустой alt и linked-image терялись на этапе Qt Markdown parse. Запрещённые внешние изображения превращались в многочисленные одинаковые fallback paragraphs.

Gallery: API `gallery[]` → featured/order/captions → тот же fetch/cache/decode → GalleryImage/QPixmap. Этот путь исправления не требовал.

## C. After

API body → bounded sanitizer с сохранением literal code → CommonMark tokens, различающие image/link/text/heading/list/code/quote/hr → контролируемый renderer → инертное форматирование QTextDocument.

Renderer выдаёт только проверенные anchor и временные маркеры изображений, **никогда remote img/src**. Маркеры становятся loading text с сохранённым anchor. Разрешённые URL идут в прежний fetch/cache/decode; успешный результат регистрируется как in-memory resource. Qt не загружает его самостоятельно.

Linked external badge становится нормальной текстовой ссылкой Discord/GitHub/Modrinth/CurseForge. Разрешённый linked image сохраняет href в loading, success и failure. Пустой alt не уничтожает image node. Для множества запрещённых декоративных изображений остаются описательные alt labels и одно компактное пояснение.

Изображения внутри quote/list учитывают отступы и поля документа при загрузке и изменении размера окна. Найденный выход изображения Antique Atlas за область чтения на 9 px устранён; это был отступ цитаты, а не ошибка таблицы 3D Skin Layers.

Использован небольшой presentation parser `markdown-it-py==4.0.0` / `mdurl==0.1.2`; модель render rules сверена с [официальной документацией](https://markdown-it-py.readthedocs.io/en/latest/using.html). Authored HTML отключён в parser и дополнительно экранируется renderer. Генерируемое Qt-форматирование не является активной веб-страницей.

## D. Files changed

Все пути относительно `D:/nexus2/launcher-next`:

- `nexus_launcher/nexus_platform/project_content.py`: корректная inline-конвертация HTML images, code protection, загрузка подготовленного содержимого, сохранение anchors и ширина изображений с учётом отступов.
- `nexus_launcher/nexus_platform/markdown_content.py`: CommonMark token renderer и компактные состояния отклонённых изображений.
- `packaging/requirements/requirements-markdown.txt`: фиксированные зависимости parser.
- `tests/test_markdown_content.py`: 35 deterministic Markdown/Qt tests.
- `tests/test_markdown_live.py`: opt-in проверка четырёх реальных проектов и screenshots.
- `nexus_launcher/frozen_content_smoke.py`: offline проверка parser/resource path внутри EXE.
- `nexus_launcher/preview_prototype.py`: opt-in `--content-smoke` в существующем QA-report, без изменений обычного запуска.
- `packaging/specs/NexusPortableContent.spec`: отдельный portable candidate v21.
- `DESIGN.md`, `UX-CONTRACT.md`: контентный контракт и установка parser dependencies.
- `MODRINTH-MEDIA-FIX-AUDIT.md`: этот отчёт.

Не изменены `nexus_launcher/nexus_platform/mod_media.py`, `nexus_launcher/nexus_platform/mod_catalog.py`, CatalogProvider, gallery presentation, visual tokens, CSS/JS, engine/updater/signing/production/Identity/Website/Cloudflare/public release manifests. Хэши всех **56 защищённых файлов** совпадают. Source backup: `D:/nexus2/backups/source-before-markdown-v21`.

## E. Security

Сохранены HTTPS-only и точный allowlist `cdn.modrinth.com`, включая redirects; проверки TLS и hostname не отключались. Форматы PNG/JPEG/WebP/GIF, ≤4 MiB, ≤4096 px; прежние ограничения icons остаются строже — 1 MiB / 2048 px. Socket timeout 5 секунд, bounded reads/decode, ограниченные worker pools, cancellation и stale generation checks остаются прежними.

Никаких file/data/javascript/http ресурсов, произвольных image hosts, script/style/iframe/object/embed/form. Sanitizer удаляет активную разметку, token renderer проверяет links/images и экранирует остаточный HTML. Разбор URL как токена не разрешает его загрузку. Ссылки открываются только при действии пользователя и проходят HTTPS policy. CSP и bridge не расширялись.

Кэш переиспользован без изменений: RAM LRU 16 MiB, 64 URL keys, TTL 300 секунд, validation before get/put, только успешно декодированные bytes. Failed entries не кэшируются, disk cache отсутствует. Cached body/gallery/icon data проходит прежнюю policy.

## F. Markdown

Проверены headings, paragraphs, bold, italic, inline code, fenced/indented code blocks, unordered/ordered lists, quotes, separators, normal links, linked images, empty/nonempty alt, multiple/repeated images, reference links/images, HTTPS autolinks и malformed Markdown. Code samples остаются literal text; они не создают запросов и активных ссылок.

## G. Images and links

| Проект | Реальная icon | Body CDN images | Gallery | Проверенные links |
| --- | --- | ---: | ---: | --- |
| 3D Skin Layers | Да | **0: внешние адреса запрещены** | 1 | Discord, GitHub, Modrinth, CurseForge |
| JEI | Да | 1 | 6 | GitHub и обычные HTTPS anchors |
| Antique Atlas 4 | Да | 6 | 12 | HTTPS anchors сохранены |
| Cobblemon Pokedex Network | Да | 1 | 1 | В текущем API body нет обычных links |

Search icons читают `icon_url` непосредственно из search response. Profile icons используют `icon_url` project payload. Missing icon сохраняет прежнюю заглушку. Loading/failure/empty gallery, featured/order/title/description и stale-response поведение покрыты fixture tests и не переписаны.

У Cobblemon две внешние badge-картинки остаются компактными fallback; разрешённый screenshot работает. Это намеренное соблюдение политики, а не ошибка CDN decode.

## H. Tests

- **Full suite: 474 passed, 4 skipped, 1 failed.** Единственный failure — ранее известный `test_windows_pinning` / WinError 206. Log/XML: `D:/nexus2/markdown-acceptance-final.log`, `markdown-acceptance-final.xml`.
- Сравнение: v19 — 420 passed / 2 skipped / 1 known failure; v20 — 439 / 3 / 1. Добавлены 35 deterministic tests и отдельный opt-in integration. Новых failures не появилось. Два прежних platform/privilege skip и два opt-in live skip.
- Focused Markdown + media/catalog/presentation: **73 passed** (`markdown-focused-final.log`). Повторная проверка новых Markdown tests после последней правки code protection: **35 passed** (`markdown-unit-accepted.log`).
- Реальный Windows integration: **1 passed**, четыре API-проекта, два размера окна 1366×900 / 1000×720 (`markdown-live.log`, `markdown-audit/live-results.json`). Это проверка загрузки и сохранения запретов, **не PASS критерия внешних body images 3D Skin Layers**.
- Ruff: весь настроенный список presentation modules и новые Python files — PASS.
- Pyright: восемь настроенных presentation modules, новый renderer и frozen helper — **0 errors / warnings** (`markdown-typecheck-final.log`).
- DESIGN.md lint — 0 errors / warnings. Static premium auditor сохраняет те же 15 findings, что v19, без новых: heuristic не распознаёт существующие делегированные button actions. Static audit не объявлен PASS; actions проверяются runtime UI tests. Findings совпадают побайтно после JSON normalization.
- JS syntax check неприменим: JS не менялся.
- Frozen EXE: renderer loaded, off-record profile, zero script errors. Дополнительная offline content-проверка подтверждает link, empty-alt image, удаление active HTML, запрет local resource и завершение loading, **0 network calls**. `D:/nexus2/frozen-markdown-v21.json`. Эта synthetic packaging fixture отделена от реальных screenshots.

Покрытие запрошенных 28 случаев:

| Случаи | Deterministic evidence |
| --- | --- |
| 1–3, 12–14 | valid/empty-alt/HTML image nodes, shared URL queue, multiple images |
| 4–7, 20 | forbidden/missing images никогда не попадают в queue/resource provider |
| 8–11 | normal/Discord/GitHub/Modrinth/CurseForge anchors без image requests |
| 15 | malformed Markdown bounded and inert |
| 16–19 | существующие format/bytes/dimensions/corrupt decode tests в tests/test_mod_media.py |
| 21 | stale body/icon/gallery results игнорируются |
| 22–23, 27–28 | existing placeholder/search/detail icon fixture tests |
| 24–26 | gallery loading/success/compact failure/stale/empty tests |

Также проверены реальные mouse-click по ссылке, linked-image anchors после success/failure, code literals, quote-image resize, один notice вместо repeated errors, verified TLS/redirect policy, cache bounds/TTL/retry.

## I. Visual verification

Launcher UI действительно запущен в Windows. Просмотрены реальные Overview/links 3D Skin Layers, Overview/Gallery JEI, Overview/Gallery Antique Atlas, Overview/Gallery Cobblemon и search icons. Все разрешённые media загружены; raw Markdown links не видны и не превращаются в image placeholders. Dark NEXUS shell, header/sidebar/cards и typography tokens сохранены. Горизонтальный overflow отсутствует при двух проверенных размерах.

## J. Screenshots

Все в `D:/nexus2/markdown-audit/screens`:

- `3dskinlayers-overview.png`, `3dskinlayers-links.png`, `3dskinlayers-gallery.png`.
- `jei-overview.png`, `jei-gallery.png`.
- `antique-atlas-4-overview.png`, `antique-atlas-4-gallery.png`.
- `cobblemon-pokedex-network-overview.png`, `cobblemon-pokedex-network-gallery.png`.
- `search-icons.png`.

API data, старый Markdown и read-only audit сохранены рядом. Screenshots проверены визуально, а не только по наличию файла.

## K. Known limitations and delivery

**Критерий «реальные изображения body 3D Skin Layers» не выполнен:** текущий API содержит только внешние image origins. Одновременно выполнить его и запрет arbitrary domains невозможно на этих данных. Allowlist не расширен; CDN gallery не подставлялась вместо authored body images. Для выполнения этого критерия нужны настоящие body URLs на разрешённом CDN либо отдельно изменённое пользователем требование безопасности. Изменение политики в этой задаче не выполнялось.

WinError 206 оставлен отдельной известной проблемой. Oversized/corrupt/external assets закономерно отклоняются. GIF декодируется как still frame. Реальное сетевое состояние может дать retryable failure; ordinary unit tests не зависят от Modrinth.

Portable candidate: `D:/nexus2/deliverables-v21/NEXUS-2.0-Portable-v21/NEXUS-2.0-Portable-v21.exe`. Это локальная сборка, не production release. v20 оставлена на месте. Данные двух сборок перенесены: все шесть файлов совпадают с оригиналами и резервной копией `D:/nexus2/backups/v20-data-before-markdown-v21-20261008`. Оба instance manifest hash совпадают и после запуска v21.

v21 запущена, окно отвечает, заголовок `NEXUS 2.0`, PID 20600. Delivery/hash evidence: `D:/nexus2/markdown-delivery.json`; data evidence: `markdown-data-verification.json`, `markdown-instances-after-launch.json`.
