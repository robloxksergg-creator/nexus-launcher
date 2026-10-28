# NEXUS Launcher: connectivity and availability plan

Статус: предложение после аудита локальных исходников, 18.10.2026. Реализация не начата. Тесты не запускались. Документ не является разрешением на изменение серверов или выпуск клиента.

## 1. Границы аудита и фактическая архитектура

Клиент: `D:/nexus2/launcher-next`. Доступный серверный исходник: `D:/nexus-work/website_NexusMC`. Его соответствие развёрнутым production/staging версиям не проверялось. Действующие endpoint, БД, credentials и пакеты не опрашивались. Карта ниже относится к прочитанному коду, а не к гарантированному составу EXE у тестеров.

### Карта клиента

Все относительные пути в этой таблице отсчитываются от `D:/nexus2/launcher-next/`.

| Файл | Найденная ответственность | Значение для изменения |
|---|---|---|
| `nexus_launcher/stable_main.py`, `packaging/specs/NexusLauncher.spec` | Stable entrypoint, PySide6 `PlatformLauncher` | Проверять native UI отдельно от tester |
| `nexus_launcher/tester_main.py`, `packaging/specs/NexusTester.spec`, `nexus_launcher/managed_tester_main.py` | Staging/tester beta, отдельные данные, `DesignHost`, bootstrap-сеанс | Не менять stable-конфигурацию через tester; BETA проекта не равен beta-каналу EXE |
| `nexus_launcher/modern_main.py` | Core Launcher: `_play`, `_launch_worker`, `_repair_worker`, `_launch_user_instance_worker`, загрузка/сохранение config, build-access refresh | Основные границы действий и текущие сетевые вызовы |
| `nexus_launcher/nexus_platform/window.py` | Native кнопки, выбор мира, install state, progress/status callbacks, сохранение настроек | Сейчас несколько callbacks независимо меняют надпись/доступность кнопки |
| `nexus_launcher/nexus_platform/next_shell.py` | Shell поверх существующих сервисов | Не создавать второй install engine |
| `nexus_launcher/nexus_platform/design_bridge.py`, `nexus_launcher/nexus_platform/prototype_host.py` | HTML shell, проекция состояния, allowlist UI actions, loopback asset host | UI получает ограниченную проекцию; проверка допуска должна оставаться в сервисе и на сервере |
| `assets/ui2/components.js`, `assets/ui2/launcher.js`, `assets/ui2/screens.js`, `nexus_launcher/nexus_platform/pages.py` | HTML/native отображение действий, состояний, уведомлений | Согласовать обе оболочки; текущий toast не является менеджером сетевых переходов |
| `nexus_launcher/updater.py` | Manifest, install/repair, SHA-256, resume/retries, транзакции, `InstallState`, локальная проверка offline integrity | Сохранить engine и recovery; не подменять его монитором сети |
| `nexus_launcher/launcher_core.py` | Minecraft/JVM/loader downloads и запуск, получение game ticket | Не все сетевые операции проходят через один HTTP-клиент |
| `nexus_launcher/nexus_account.py`, `nexus_launcher/secure_http.py`, `nexus_launcher/launch_identity.py` | Launcher bearer/keyring, build-access, game ticket, HTTPS/origin/redirect policy, identity binding | Развести transport/auth/admission ошибки, сохранить защиту origin и токенов |
| `nexus_launcher/nexus_platform/auth_state.py` | ONLINE/OFFLINE/SERVER_UNAVAILABLE и состояния сессии | Не использовать auth-state как единственный индикатор Internet |
| `nexus_launcher/server_status.py` | Minecraft TCP ping | Отказ игрового порта не доказывает отсутствие Internet |
| `nexus_launcher/projects.py` | Каталог миров, ID, manifest URLs, visibility и пользовательские проекты | Нужны явные official build ID и environment mapping |
| `nexus_launcher/nexus_platform/config.py`, `nexus_launcher/platform_support.py` | Версия config, atomic write/migration, платформенные пути | Только пользовательские предпочтения; не источник административных прав |
| `nexus_launcher/nexus_platform/content.py` | Необязательный presentation feed и локальный cache/assets | Не источник авторизации; fetch имеет побочные записи и не подходит для health probe |
| `nexus_launcher/offline_ui_policy.py` | Специальная политика UI-теста | Не реализация рабочего offline-режима |
| `nexus_launcher/launcher_diagnostics.py` | Ограниченная диагностика операций | Сохранять отсутствие паролей, кодов, токенов, тел ответов и секретных URL |
| `nexus_launcher/admin.py`, `nexus_launcher/security.py`, `nexus_launcher/server_controller.py` | Локальный Control Center, permissions и управление серверами | Не доказательство полномочий менять глобальный статус сайта |
| `nexus_launcher/self_update.py`, `nexus_launcher/startup_portable_backend.py`, `nexus_launcher/startup_bootstrap_main.py` | Отдельные механизмы обновления EXE/bootstrap и package/slots | Availability проекта не должна менять доверие, slots или разрешать исполняемый код |

Legacy `nexus_launcher/main.py` — другая Tkinter-ветка; её нельзя автоматически считать текущим интерфейсом. Какие старые EXE требуется поддерживать, нужно отдельно инвентаризировать.

### Карта серверных компонентов

Все относительные пути здесь отсчитываются от `D:/nexus-work/website_NexusMC/`.

| Файл | Фактическое поведение |
|---|---|
| `db/buildAccess.ts`, `db/auth.ts` | `launcher_build_access`: build ID, `OPEN/MAINTENANCE/CLOSED`, message, updated_by/updated_at. Defaults создаются через INSERT OR IGNORE. Известные build IDs: main, building, pinewood, elderfall |
| `app/api/launcher/build-access/route.ts` | Возвращает builds/mode/message/allowed/updatedAt, no-store. OPEN разрешён, technicalAccess сейчас false. Нет BETA, общей revision и expiry |
| `app/api/admin/launcher-builds/route.ts`, `db/rbac/legacyContainment.ts` | GET/PATCH намеренно отказывают через legacyStaffDenied; работающий административный write API не подтверждён |
| `app/admin/launcher/page.tsx` | UI OPEN/MAINTENANCE/CLOSED; UI не доказывает возможность записи или реальный staff bypass |
| `db/rbac/permissions.ts`, `db/rbac/evaluator.ts` | Серверные permissions/deny; не реализованная политика отказывает. Готовая отдельная permission изменения availability не найдена |
| `db/controlPlane.ts` | Полномочия control-plane для иных операций | 
| `app/api/launcher/modpacks/gearmorph/route.ts`, `app/api/launcher/modpacks/building/route.ts` | Public manifest GET с внешними GitHub references; build-access/допуск не проверяется |
| `app/api/launcher/game-ticket/route.ts` | Проверка аккаунта/профиля/сессии; ticket не привязан к конкретному build и не проверяет его availability |
| `app/api/launcher/auth/login/route.ts`, `db/auth.ts` | Серверная опциональная общая tester-only политика; не per-build BETA entitlement |
| `db/downloadAccess.ts`, `app/api/launcher/download/[file]/route.ts` | Сайт проверяет website session для скачивания launcher artifact | 
| `app/api/launcher/update/route.ts` | Отдельный endpoint обновления launcher | 
| `app/api/v1/operations/status/route.ts` | Статус конкретной creator operation, не глобальная доступность |
| `app/api/v1/tech/overview/route.ts`, `db/serviceTransport.ts` | Staff/service-инструменты, не анонимный health endpoint |

Website session скачивания EXE и launcher bearer — разные контексты. Нельзя автоматически переносить права одного в другой.

## 2. Проблемы, которые план должен устранить

1. `OfflineError` в account client объединяет часть сетевых, DNS, TLS и endpoint ошибок. Ошибка одного сервиса не доказывает отключение Internet.
2. Build-access refresh может сохранить старое состояние без TTL. В ряде клиентских веток отсутствующая запись становится OPEN/allowed; перед запуском пустой build record также не обеспечивает отказ.
3. В `_launch_worker` есть свежая проверка build-access, но `_repair_worker` не имеет эквивалентной проверки. Проверка maintenance из manifest выполняется после `update_if_needed`, то есть не предотвращает уже начатое применение.
4. Серверные public manifests и внешние public URLs не защищают загрузки BETA. Существующий game ticket также не является per-project допуском.
5. Отдельные UI writers progress/status/select_server могут затереть ограничение новой кнопки. Нужна единая проекция эффективного действия.
6. Ping игрового сервера, состояние авторизации, presentation feed и доступность install API — разные сигналы.
7. У tester account origin staging, но default manifest references в каталоге могут вести на production. До реализации требуется явная карта окружений; монитор не должен незаметно смешивать их.
8. Серверный read build-access вызывает ensure/defaults, а проверка launcher session обновляет last_used_at. Такой маршрут нельзя объявить health probe без побочных записей.
9. Локальная `can_launch_offline` доказывает только наличие/целостность файлов. Текущий официальный запуск ещё требует build-access и game ticket; полноценный offline launch не подтверждён.

Это результаты ограниченного архитектурного аудита, а не завершённый security audit всех путей скачивания.

## 3. Сеть: отдельное состояние и уведомления

Предлагается один launcher-owned connectivity service, общий для native/HTML UI. Он не выполняет установки, не восстанавливает сессию самостоятельно и не вызывает скачивание manifest/images ради проверки сети. Реализация — последующий отдельно разрешённый этап.

Хранить раздельно: подсказку состояния локального подключения; результат проверки конкретного NEXUS origin; результат конкретного API; auth/session state; freshness availability; install transaction state. Добавить generation окружения/аккаунта, чтобы поздний ответ старой сессии не менял новый UI.

| Состояние отображения | Условие и предел вывода | Сообщение |
|---|---|---|
| Нет сети | Подтверждённое отсутствие локального подключения; системный сигнал должен быть проверен на поддерживаемой платформе | «Нет подключения к сети. Проверьте соединение.» |
| NEXUS недоступен | NEXUS probe/операция не отвечает или возвращает service failure; Internet может работать | «Не удаётся связаться с NEXUS. Повторим проверку.» |
| NEXUS доступен | Ожидаемый валидный HTTPS health response | «Связь с NEXUS восстановлена.» только после подтверждённого сбоя |
| Неизвестно / проверяем | Старт, недостаточно свидетельств, неоднозначный DNS/transport failure | «Проверяем соединение…»; не утверждать, что Internet отключён |

Без независимого свидетельства нельзя надёжно различить отсутствие Internet и недоступность одного origin. OS reachability — подсказка, а не гарантия. Qt/native backend и его наличие ещё нужно проверить. Не использовать сторонние ping/HTTPS адреса без отдельного выбора владельца и оценки приватности. TLS/certificate error показывать как ошибку безопасного соединения, без HTTP fallback.

Предлагаемый health endpoint: анонимный маленький GET с фиксированной версией ответа, HTTPS и allowlisted origin, без токенов, DB initialization, session writes, R2 и внешних fetch. Он подтверждает только работоспособность конкретного service path; health=OK не гарантирует исправность auth, БД и CDN. Такого подходящего маршрута в проверенных участках не найдено; endpoint пока только предложение.

Параметры для первоначального согласования: одна проверка одновременно, timeout 5 секунд, ограниченный ответ 4 KiB; healthy interval 60 секунд с jitter ±20%; после ошибки backoff 5/15/30/60/120 секунд. Учитывать ограниченный Retry-After при 429; не создавать новые потоки на каждый timeout. Закрытие окна прекращает планирование. Системный вызов может пережить deadline: это не гарантия жёсткого завершения I/O.

Подтверждать сбой двумя последовательными неуспехами, восстановление двумя успехами с интервалом не менее 3 секунд. Постоянный banner содержит актуальное состояние; toast — один на подтверждённый переход, с cooldown 60 секунд. Начальная недоступность не порождает «соединение потеряно», а повторные ошибки разных ресурсов не создают каскад уведомлений. После cooldown обновлять состояние без воспроизведения очереди старых toast. Звук по умолчанию не добавлять.

401 — проблема сессии; 403 — отказ допуска; 429 — ограничение запросов; 5xx — проблема сервиса; malformed response — protocol failure. Не стирать credentials при transport outage. Результат одного CDN/download не переводит весь launcher в «нет Internet». Сохранение последнего профиля для отображения не даёт права запуска.

## 4. Контракт четырёх режимов

Режим определяет сервер для официального build ID. `UNKNOWN/STALE` — производное состояние клиента, не пятый административный режим. `INSTALL` описывает доступность, а не обязательную надпись: существующий delivery state по-прежнему выбирает «Установить / Обновить / Восстановить / Играть».

| Режим | UI | Установка, update, repair | Официальный запуск |
|---|---|---|---|
| INSTALL | Обычная кнопка по install state | Только при актуальном допуске и валидных metadata | Требуются действующие аккаунт, профиль и ticket |
| MAINTENANCE | Disabled «Технические работы», безопасный plaintext reason | Не начинать новые действия | По умолчанию не начинать; staff bypass не подразумевается |
| UNAVAILABLE | Disabled «Установка недоступна» | Не начинать новые действия | В этом предложении также запрещён новый официальный запуск; если нужен режим install-only, это отдельное решение владельца |
| BETA | Badge «Бета»; при допуске обычная delivery-кнопка; иначе disabled «Нужен доступ к бета-тесту» | Сервер проверяет активный per-build grant | Сервер проверяет тот же допуск при выдаче project-bound ticket |

Неавторизованному пользователю показывать «Войти» как переход авторизации, но не предоставлять install/download capability. Миру coming_soon и неподдерживаемому build ID не назначать разрешение по умолчанию. Общий запрет не отменяется пользовательским BETA grant.

При неизвестном/просроченном статусе запрещать новые официальные сетевые действия: «Статус проекта не подтверждён. Повторить проверку». Просмотр библиотеки, настроек и диагностики сохраняется. Не обещать offline официальный запуск. Пользовательские локальные проекты не становятся автоматически объектами глобальной политики; нужно явно маркировать official content и проверить библиотечные/import маршруты, не ломая независимые пользовательские сборки.

Кнопка остановки уже работающей игры остаётся доступной. Смена режима/сети не завершает игру и не удаляет данные. При транзакции: не запускать новое скачивание; остановка/пауза допускается только в доказанной безопасной точке существующего engine. Не прерывать atomic apply посередине и не начинать автоматический repair/rollback от connectivity monitor. Переоценивать допуск перед следующим новым действием.

## 5. Авторитетный статус, freshness и совместимость

Предлагаемый источник — существующая серверная модель build-access в D1, эволюционирующая только после отдельного разрешения. Клиентский config, presentation feed, поле tester, manifest maintenance и локальная admin-панель не являются полномочным источником. Для первой реализации — одна запись на официальный build; общий emergency override, если потребуется, имеет приоритет отказа и требует отдельного контракта.

Новый versioned status contract (путь ещё не утверждён): `schemaVersion`, `environment`, `projectId`, `buildId`, `mode`, монотонная `revision`, `issuedAt`, `validUntil`, `reasonCode`, bounded plaintext `message`. Развести публичный статус и персональный admission: последний привязан к текущим session/user, build ID, environment, revision, actions и короткому сроку, возвращается private/no-store. Не передавать bearer или download capability в HTML state.

Предлагаемый TTL — максимум 120 секунд, public cache не более 15 секунд и не за пределами validUntil. Получение привязать к monotonic elapsed time; ограничивать server TTL, отклонять некорректные даты/schema/enum/ID, будущую несовместимую схему, конфликт содержимого одной revision и понижение уже принятой revision в том же scope. После перезапуска кэш — только подпись «последний известный статус», не разрешение. При смене аккаунта admission очищается; старый ответ игнорируется. Изменение локального кэша не может открыть серверные ресурсы.

Кэш и revision не заменяют серверную проверку при каждом выдаваемом праве. При недоступности API не использовать последнюю разрешающую запись бессрочно. По восстановлении сначала загрузить свежий статус/admission; не возобновлять установку автоматически только из-за зелёного индикатора.

Legacy mapping: OPEN соответствует INSTALL, CLOSED — UNAVAILABLE, MAINTENANCE сохраняется. BETA нельзя представить старому клиенту как OPEN: legacy view должен отказывать, а backend должен защищать ресурсы независимо от версии клиента. Сначала серверная защита, затем UI. Проверить все build IDs: backend сейчас не покрывает автоматически любой новый мир из каталога.

Статус availability передаётся по аутентифицированному HTTPS origin и управляет доступом к сервису, а не доверием к коду. Он не отменяет подписи release, hashes, pinned trust или TUF expiry/replay protections. SHA-256 без подписи не доказывает авторство. В прочитанном `assets/bootstrap-release.json` schema=1, channel=beta, feed=null: этот план не включает feed, не меняет stable/beta trust stores и не активирует удалённые обновления bootstrap.

## 6. Административные полномочия и BETA enforcement

Нужна отдельная серверная permission управления availability с явной областью project/build и environment. Название capability определить при реализации; существующий `is_admin`, локальная роль, frontend-флаг или наличие экрана не являются grant. Текущий закрытый admin endpoint не открывать до готовности серверной политики.

На mutation: активные account/session, актуальный серверный grant, explicit deny/revocation, валидный build/mode/message, expectedRevision/CAS. Website cookie mutation требует CSRF/Origin защиты; bearer API требует соответствующего scoped контекста. Изменение и audit record с actor, scope, old/new revision и outcome должны быть атомарны. Если нельзя записать аудит — не публиковать изменение. Повтор mutation после неопределённого ответа не делать автоматически: нужны idempotency key и подтверждаемое состояние операции. Условия step-up для открытия доступа согласовать отдельно.

BETA grant проверять сервером не только в build-access, но и при выдаче manifest/install session, archive/file/Ranges capability и нового игрового ticket. Capability должна быть короткоживущей, привязанной к build/artifact/action, без передачи credentials на чужой redirect. Admission отзыв действует при следующей серверной проверке; уже выданный URL имеет ограниченное окно до expiry.

Public GitHub URLs текущих сборок означают, что UI/manifest gate не закрывает прямую загрузку. Для действительно закрытого BETA нужен непубличный artifact origin или серверная доставка с enforceable authorization, включая CDN cache и Range. Это отдельная инфраструктурная задача, сейчас не выполняется. Скачанные ранее байты отозвать нельзя; это контроль предоставления ресурсов, не DRM. Per-build game-ticket enforcement потребует подтверждения совместимости серверного обработчика игры; текущий ticket этого свойства не имеет.

## 7. Настройки и ошибки

В config допустимы только предпочтения уведомлений, например видимость toast; banner и обязательные запреты не отключаются настройкой. Добавление полей требует обратимой миграции существующего config и сохранения незнакомых допустимых полей. Секреты остаются вне JSON. Использовать существующий atomic write, не новый механизм хранения.

Автоматические запросы не должны выполнять restore/login/registration, обновлять роли или создавать запись статуса. Диагностика: operation, environment, безопасный reason code, HTTP category, длительность, transition/revision без credentials, email, паролей, кодов, response body и подписанных URLs. Сообщения сервера показывать plaintext с ограничением длины.

## 8. План тестирования — не выполнялся

Ни один перечисленный ниже тест не запускался в рамках аудита. Имена существующих тестов — точки будущего регрессионного покрытия, не доказательство прохождения.

| Область | Обязательные проверки | Существующие точки покрытия |
|---|---|---|
| Connectivity | Fake clock/transport: старт unknown, hysteresis, cooldown, flapping, one-inflight, backoff, late responses, shutdown, 401/403/429/5xx/DNS/TLS/protocol | `tests/test_auth_state.py`, `tests/test_nexus_account.py`; новые чистые monitor tests |
| UI и действия | Матрица 4 modes × install states × account/admission/freshness; native/HTML одинаковы; progress не открывает запрет; play/repair/retry/library/import boundaries; stop running game доступен | `tests/test_design_action_boundary.py`, `tests/test_global_update.py`, `tests/test_updater_progress_contract.py` |
| Установка/восстановление | Отказ до новых побочных действий; interruption/recovery; Range/retry; смена режима во время download/apply; целостность файлов и отсутствие удаления данных | `tests/test_updater.py`, `tests/test_file_transaction.py`, `tests/test_import_cleanup_security.py` |
| Auth и BETA | Account swap, expired/revoked grant, некорректный build ID, старая revision, ticket scope, transport outage не стирает token, unauthorized direct download | `tests/test_prerelease_admission.py`, `tests/test_registration_handoff.py`, backend `tests/auth-release-security.test.mjs` |
| Сервер/admin | Deny-by-default, CSRF, scope/environment, stale CAS, concurrent writes, revoke-at-mutation, atomic audit failure, idempotency/unknown outcome, legacy BETA deny | Backend `tests/rbac-foundation.test.mjs`, `tests/rbac-legacy-containment.test.mjs`, `tests/rbac-revocation.test.mjs`; новые узкие policy tests |
| Artifacts | Website-vs-launcher auth, direct URLs, CDN cache leakage, Range/redirect, expiry/revoke windows, public origin отказ как закрытой BETA | Backend `tests/launcher-download-access.test.mjs`, `tests/launcher-release.test.mjs`; новые fixture tests |
| Настройки | Старый/повреждённый config, atomic write failure, preferences persist, отсутствие token в config/cache/logs, раздельные beta/stable данные | `tests/test_config_recovery.py`, `tests/test_path_settings.py`, `tests/test_ui_preferences.py`, `tests/test_runtime_settings.py` |
| Обновление EXE/trust | Feed остаётся выключенным; legacy подписи, slots/recovery и v2 trust не зависят от online badge; beta/stable keys не смешиваются | `tests/test_self_update.py`, `tests/test_signed_update.py`, `tests/test_startup_update_flow.py`, `tests/test_startup_portable_backend.py`, `tests/test_beta_update_trust.py`, `tests/test_update_v2_trust.py` |

Будущие проверки сначала на синтетических transport/responses и временных данных без реальных game downloads. Сетевые/staging проверки, изменяющие БД, требуют отдельного разрешения. Полный regression также не разрешён данным документом.

## 9. Порядок реализации с отдельными критериями допуска

1. **Подтвердить контракт и область.** Выбрать поддерживаемые EXE/UI, official ID/environment mapping, UNAVAILABLE launch semantics, TTL, BETA grant owner и private artifacts. Критерий: нет неизвестного permissive default и неявного staff bypass.
2. **Чистая модель состояний.** Разделить connectivity/auth/availability/install; определить shared action projection. Критерий: согласованная таблица решений и разрешённые pure unit tests, без изменений transport/production.
3. **Connectivity transport и UI.** Отдельно спроектировать/проверить health route без записей; реализовать ограниченный monitor и уведомления. Критерий: no spam, no UI block, no token leakage, корректные unknown/server/offline состояния. Никакого автоматического install.
4. **Серверная status/admin policy.** Versioned read contract, RBAC mutation, audit/CAS, fail-closed legacy mapping. Критерий: отрицательные policy tests, approved schema/deployment plan; production не изменять автоматически.
5. **Реальный admission.** Закрытая выдача artifacts и project-bound ticket; определить срок capabilities. Критерий: direct-download/Range/cache/account-swap проверки. Пока это не доказано, BETA называется только presentation mode, не защищённой бетой.
6. **Единая граница действий.** Подключить статус ко всем official install/update/repair/launch путям, сохранив engine. Критерий: матрица UI/service/server и recovery scenarios; отсутствие обхода alternate actions.
7. **Настройки и регрессии.** Совместимость config, beta/stable, auth и update trust. Критерий: отдельно разрешённые целевые и затем полный применимый regression, review рисков. Прохождение тестов не является разрешением публикации.

Каждый этап требует отдельного указания владельца; этот план разрешает только аудит и создание документа. Не создавать дублирующий updater, не мигрировать beta в stable и не включать удалённый feed в ходе этих функций.

## 10. Открытые вопросы перед реализацией

- Какая конкретная версия/оболочка находится у пользователей; какие legacy EXE останутся поддерживаемыми?
- Совпадает ли локальный website source с deployed API/schema и фактической tester-only политикой? Проверка среды в данный аудит не входила.
- UNAVAILABLE запрещает новый официальный запуск или только загрузку? Здесь выбран консервативный запрет обоих; требуется решение владельца.
- Кто выдаёт/отзывает BETA grants, нужны ли сроки и отдельные staff исключения? По умолчанию исключений нет.
- Где хранить закрытые BETA artifacts; каков бюджет и допустимая задержка отзыва ранее выданных capabilities?
- Поддерживает ли game server per-build ticket admission? Это не подтверждено.
- Какой OS/Qt reachability backend доступен в целевых сборках? Без него часть «нет сети» остаётся unknown, а не ложным точным диагнозом.
- Требуется ли отдельный global emergency override сверх per-build статуса и step-up для снятия ограничений?

## 11. Выполненная проверка документа

Проверки ограничены новым Markdown: строгий UTF-8, структура таблиц и наличие перечисленных локальных файлов. Python-тесты, AST/compile, приложение, installer, game downloads, API и инфраструктурные операции не запускались. Единственное разрешённое изменение — этот новый документ; существующий код, конфигурации и документы не редактировались.
