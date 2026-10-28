# NEXUS Desktop — проект контракта установки

Дата: 2026-10-17, Asia/Bishkek. Версия документа: draft 2 — решения после review.

Статус: **DESIGN DIRECTIONS AGREED / OPEN DESIGN QUESTIONS**. Перечисленные в §10.1 направления согласованы владельцем только для проектирования, не реализованы и не приняты как работающий продукт. Остальные варианты остаются предложениями. NEXUS Desktop Phase 1 не объявляется завершённой автоматически.
Это проектирование установки, не реализация Setup и не продолжение реализации Trust Phase 2/Phase 3.
Ни один предложенный каталог, receipt, ярлык, registry key или механизм удаления этим документом не создаётся.

Документ размещён в существующем месте проектной документации — корне `launcher-next`, рядом с `UX-CONTRACT.md`, `DESIGN.md`, `MIGRATION.md`. Новая структура документации не создаётся.

## 1. Объект, доказательства и текущее поведение

Объект: `D:/nexus2/startup-updater-20261016/private-package/NEXUS-Bootstrap-beta2/NEXUS.exe` и полный `NEXUS-Bootstrap-beta2-PRIVATE.zip` в родительском audit-каталоге. EXE не запускался. Исходники, существующий бинарник и будущая stable-сборка — разные объекты: изменения исходников не означают пересборку beta2.

Следующие строки — **факты чтения исходников/конфигураций**, а тесты в таблице — доказательство существования проверок, не заявление об их выполнении в этом этапе.

| ID | Подтверждённое поведение | Источник / тест |
| --- | --- | --- |
| F01 | Legacy Setup устанавливает только `NexusLauncher.exe`, требует абсолютный каталог, проверяет SHA-256, сохраняет `previous.exe` в собственной операции. Полного onedir installer нет в этом entrypoint. | [nexus_launcher/installer_main.py](D:/nexus2/launcher-next/nexus_launcher/installer_main.py), [tests/test_installer.py](D:/nexus2/launcher-next/tests/test_installer.py) |
| F02 | Старый build script создаёт onefile tester и Setup с вложенным EXE/JSON. | [nexus_launcher/build_tester_release.py](D:/nexus2/launcher-next/nexus_launcher/build_tester_release.py), [packaging/specs/NexusTester.spec](D:/nexus2/launcher-next/packaging/specs/NexusTester.spec) |
| F03 | Новый bootstrap — PyInstaller onedir с `NEXUS.exe` и `_internal`; initial ZIP/envelope добавляются отдельной сборочной операцией. | [packaging/specs/NexusStartupBootstrap.spec](D:/nexus2/launcher-next/packaging/specs/NexusStartupBootstrap.spec), [assemble_bundle.py](D:/nexus2/startup-updater-20261016/assemble_bundle.py), packaged `READ-ME.txt` |
| F04 | Bootstrap entrypoint принудительно tester/staging, принимает beta policy, использует `%LOCALAPPDATA%/NEXUS Tester/managed-beta`, Windows/x64. Это не stable entrypoint. | [nexus_launcher/startup_bootstrap_main.py](D:/nexus2/launcher-next/nexus_launcher/startup_bootstrap_main.py) |
| F05 | В beta2 packaged `assets/bootstrap-release.json` находится `feed:null`. Текущий entrypoint при нём проверяет установленный слот и не обращается за обновлением. | packaged policy и `nexus_launcher/startup_bootstrap_main.py:Backend.check` |
| F06 | Первое provision создаёт подписанный слот, `initial-provision.json`, `highest-package.json`, `active.json`; не усыновляет legacy-каталог и не пересоздаёт потерянный pointer при имеющейся истории. | [nexus_launcher/bootstrap_installation.py](D:/nexus2/launcher-next/nexus_launcher/bootstrap_installation.py), [tests/test_bootstrap_installation.py](D:/nexus2/launcher-next/tests/test_bootstrap_installation.py) |
| F07 | Inventory ограничивает ZIP, пути, число/размер файлов; `_internal` обязателен, пользовательские data запрещены. Слот содержит `files`, `envelope.json`, `journal.json`. | [nexus_launcher/portable_package.py](D:/nexus2/launcher-next/nexus_launcher/portable_package.py), [tests/test_portable_package.py](D:/nexus2/launcher-next/tests/test_portable_package.py) |
| F08 | Переходы используют существующий journal schema 1, active pointer, точную identity и подтверждение дочернего процесса. Неопределённый исход блокирует повтор; откат требует подтверждённого завершения ребёнка. | [nexus_launcher/portable_transition.py](D:/nexus2/launcher-next/nexus_launcher/portable_transition.py), [nexus_launcher/portable_bootstrap.py](D:/nexus2/launcher-next/nexus_launcher/portable_bootstrap.py), [nexus_launcher/windows_bootstrap_process.py](D:/nexus2/launcher-next/nexus_launcher/windows_bootstrap_process.py); соответствующие `tests/test_portable_transition.py`, `tests/test_portable_bootstrap.py` |
| F09 | Managed child проверяет слот/identity, но не переключает tester-профиль на возвращённый `root/data`. Профиль остаётся `%LOCALAPPDATA%/NEXUS Tester/beta`. | [nexus_launcher/managed_tester_main.py](D:/nexus2/launcher-next/nexus_launcher/managed_tester_main.py), [nexus_launcher/tester_main.py](D:/nexus2/launcher-next/nexus_launcher/tester_main.py), [nexus_launcher/portable_storage.py](D:/nexus2/launcher-next/nexus_launcher/portable_storage.py), [tests/test_portable_storage.py](D:/nexus2/launcher-next/tests/test_portable_storage.py) |
| F10 | Обычный Windows data root — `%APPDATA%/.nexus-launcher`; tester дополнительно переопределяет APPDATA. `install_root` в UI — путь игровых сборок, не установка Desktop. | [nexus_launcher/platform_support.py](D:/nexus2/launcher-next/nexus_launcher/platform_support.py):app_data_dir, [nexus_launcher/modern_main.py](D:/nexus2/launcher-next/nexus_launcher/modern_main.py):APP_DIR/_storage_root, `nexus_launcher/tester_main.py` |
| F11 | Учётные данные принадлежат account service/keyring; staging имеет отдельный service suffix. | [nexus_launcher/nexus_account.py](D:/nexus2/launcher-next/nexus_launcher/nexus_account.py):NexusAccountClient; хранилище не читалось |
| F12 | `safe_paths` запрещает UNC/device roots, неоднозначные имена и reparse points; pinning удерживает предков, Windows replacement идёт через source handle с hash-проверкой. Длинные пути требуют end-to-end проверки. | [nexus_launcher/safe_paths.py](D:/nexus2/launcher-next/nexus_launcher/safe_paths.py), [tests/test_windows_pinning.py](D:/nexus2/launcher-next/tests/test_windows_pinning.py) |
| F13 | В проверенных installer/bootstrap/build путях нет создания `.lnk`, ARP registration или uninstaller. AppUserModelID в отдельных launcher entrypoints не является установкой ярлыков. | `nexus_launcher/installer_main.py`, `nexus_launcher/startup_bootstrap_main.py`, `nexus_launcher/build_tester_release.py`, [nexus_launcher/stable_main.py](D:/nexus2/launcher-next/nexus_launcher/stable_main.py), `nexus_launcher/modern_main.py`; ограниченный поиск этих операций в актуальных исходниках |
| F14 | Текущий рабочий spec включает v2 hiddenimports, сохранённый beta2 component spec их не содержит; production v2 root не задан. | `packaging/specs/NexusStartupBootstrap.spec`, [saved component spec](D:/nexus2/startup-updater-20261016/component-build-keyed/candidate.spec), [nexus_launcher/update_v2_anchor.py](D:/nexus2/launcher-next/nexus_launcher/update_v2_anchor.py) |

Штатная read-only проверка Authenticode beta2 EXE в этом этапе: `NotSigned`, signature type `None`. Это факт о бинарнике, не malware verdict. Более ранняя SAC-диагностика — отдельная работа; блокированный EXE не перезапускался.

Нумерованный общий план Desktop 0–7 не предоставлен. Этот документ исполняет именно присланное задание **Desktop Phase 1: Installation Contract**, не присваивает статусы неизвестным этапам 0–7.

## 2. Предлагаемый контракт каталогов

Область установки и основные корни I/D **приняты для проектирования** (§10.1). Детальная структура, selector и полная модель servicing/ownership пока остаются предложениями (§10.2). Ни одно из этих решений не описывает уже реализованную stable-установку.

### 2.1. Область установки

Принято для проектирования: первая версия — per-user, Windows x64, без административных прав и all-users installation. Каталог программы определяется через Windows Known Folder API. `asInvoker`, отсутствие HKLM/services/tasks и фиксированный root без custom install dir — технические ограничения предложенной первой версии; автозапуск запрещён согласованным направлением. Папки определяются для текущего token SID, а не по строке из environment, receipt или команды сервера.

Основной install root **I**: `FOLDERID_UserProgramFiles/NEXUS`, обычно `%LOCALAPPDATA%/Programs/NEXUS`.
Основной data root **D**: `FOLDERID_LocalAppData/NEXUS/stable`.

Выбор I обоснован разделением per-user программ и данных: Windows определяет UserProgramFiles как `%LOCALAPPDATA%/Programs`. D находится вне install ownership и сохраняется при удалении. Размещение всего продукта прямо в LocalAppData смешало бы изменяемый профиль и пакеты; Program Files потребовал бы лишнего elevation/другой модели обновлений. Факт текущего beta layout не обязывает stable использовать `NEXUS Tester`.

### 2.2. Вариант структуры — selector пока не утверждён

Приняты только корни I/D и установка полного onedir-комплекта. Приведённое дерево показывает **один из вариантов**, зависящий от ещё не утверждённого selector. Имена внутренних каталогов, bootstrap slots и формат receipts не фиксируются как окончательное решение. Если selector не будет выбран, потребуется отдельно утвердить обслуживание полного bootstrap onedir без него.

```text
I/                                      только управляемые программные файлы
  NEXUS.exe                             вариант: selector (НОВЫЙ, НЕ УТВЕРЖДЁН)
  bootstrap/<owned-id>/                  полный immutable bootstrap onedir
    NEXUS.exe
    _internal/...
  bootstrap-state/                       выбранный bootstrap, receipts, maintenance journal
  managed/                              root существующего slot engine
    slots/portable-stage-<id>/
      files/<entrypoint>.exe
      files/_internal/...
      envelope.json
      journal.json
    active.json
    initial-provision.json
    highest-package.json
    transition.json                     только когда создан механизмом переходов
    cache/                              управляемые загрузки, без credentials
  maintenance/<operation-id>/            staging, временные backups и uninstaller worker
  install-receipt.json

D/                                      не входит в uninstall file ownership
  profile/                              настройки/локальные модели стабильного клиента
  logs/
  diagnostics/
  trust-v2/                             только после отдельного допуска v2
  cache/                                пользовательский cache; default uninstall сохраняет
```

Игровые сборки/миры/projects остаются по пути, выбранному пользователем в сервисе хранения. Setup не перенастраивает их и не предполагает, что они находятся внутри D. Не допускается создавать новые user projects под I. Существующие пользовательские файлы, случайно попавшие в I, не становятся собственностью установщика.

Если будет выбран НОВЫЙ selector, его роль ограничивается минимальным local dispatcher, а не новым downloader/распаковщиком/slot engine. Он должен проверять разрешённый bootstrap receipt и запускать только выбранный onedir bootstrap. Нет сети, динамического shell command, app auth или серверного key provisioning. Цель варианта — не менять работающую пару bootstrap EXE + DLL по частям. Необходимость selector пока не утверждена; его существование/проверенность не заявляется. Вложенный настоящий bootstrap может сохранить имя NEXUS.exe. Для выбора нужен эксперимент из §10.2, а не только эта схема.

Application `managed` сохраняет ожидаемый slot engine layout; существующие journals v1 не переименовываются и не переводятся в другую schema. `managed/data`, который сейчас возвращает generic resolver, нельзя автоматически начать использовать для stable-profile: стабильный data resolver должен явно получить D от скомпилированной channel policy. Соединение с сервисами профиля — отдельная будущая адаптация, не изменение tester env.

В trust-v2 сохраняются high-water marks между переустановками. Install receipt может хранить зеркальную краткую identity, но не заменяет криптографическую историю. Default uninstall сохраняет D целиком; если целостность trust-state нарушена, reinstall не обнуляет историю для обхода rollback-защиты.

### 2.3. Пути, ACL и безопасное создание

- Допуск только на локальный поддерживаемый том; UNC/mapped network/removable и системные/shared directories для первой версии запрещены. Точную поддержку томов проверять до записи, не выводить из одной буквы диска.
- Root получают из Known Folders; проверяют canonical root, token SID, владельца и DACL. Запись посторонними непривилегированными SID недопустима. Доступ SYSTEM/Administrators не считается защитой от администратора; same-user malware не покрывается.
- Создавать компоненты без перехода через reparse points; удерживать проверенные directory handles. Повторять leaf/handle checks при записи, commit и удалении. Не считать `resolve()` и preflight достаточными против TOCTOU.
- Сохранить `checked_path`, `relative_parts`, pinning и handle replacement; не переходить к незащищённому rename при отказе. Fail closed на небезопасной namespace/ACL. Для hardlinks не выполнять запись through existing leaf.
- Корректность Unicode/пробелов/не-BMP обязательна; длины WinAPI — UTF-16 code units/bytes по API, не `len()` Python-строки.
- Extended spelling формируется только внутри trusted I/O после валидации обычного абсолютного пути; caller-supplied device paths по-прежнему запрещены. Поддержка всех операций, включая Python read/enumeration/cleanup и Shell, должна быть доказана. Изменение реестра LongPathsEnabled не является предусловием, выполняемым Setup.
- В этой среде уже наблюдался отдельный отказ обычного Python read длинного пути после успешного extended rename. Поэтому требование long-path пока **не принято**, и один исправленный API не делает весь install stack совместимым.
- Redirected Desktop/Start Menu получать через Known Folders. Не создавать `%USERPROFILE%/Desktop` вручную; если реальный путь не проходит текущую security policy, пропустить optional shortcut с понятным результатом, не ослаблять все проверки.

## 3. Ownership и install receipt

Предлагается отдельный **installation receipt schema 1**, namespace `nexus-desktop-install-v1`. Это не `initial-provision.json`, не `transition.json` и не TUF metadata. Согласован принцип удаления только подтверждённо принадлежащих файлов; окончательные формат receipt и recovery при его повреждении **не утверждены**. Следующие поля и алгоритмы — требования/кандидаты для дальнейшего доказательства, не разрешение реализовать receipt.

Обязательные поля: product/channel/platform/arch, install_id UUID, owner SID, layout_version, operation_id, generation, phase, canonical root identity, bootstrap slot/selector identity, ссылка на подписанный catalog; для каждого принадлежащего файлу — относительный путь, kind, размер, SHA-256, catalog identity. Отдельные списки shortcut и ARP identity, выбор optional Desktop shortcut. Не сохранять password/token/email/code или произвольный executable command.

Файлы приложения в динамических слотах описываются уже существующими подписанными inventory + slot receipts; install receipt хранит принадлежность managed-root и ссылки, а не объявляет любые его будущие файлы своими. Каждый дочерний receipt верифицируется отдельно.

Запись bounded UTF-8 JSON, с запретом duplicate keys/unknown schema/path ambiguities, fsync + безопасная атомарная замена. Journal сохраняет прежнее/новое состояние целиком. Версия receipt монотонна в пределах install_id.

**Receipt не является самостоятельным полномочием на удаление.** Пользователь может его изменить. Разрешение на действие — пересечение compiled product root policy, SID/ACL и handle checks, signed catalog, относительного пути и существующего operation journal. Хеш локального receipt защищает лишь от случайного повреждения. Перенаправление root/registry key/shortcut target в receipt не расширяет область полномочий.

Режимы владения:

- Новый пустой I: создать уникальный install_id и ownership до публикации ярлыков.
- Существующий непустой I без проверяемого receipt: **не усыновлять**, не перезаписывать и не удалять. Потребуется отдельная recovery/import процедура.
- Неизвестные/модифицированные файлы: сохранить, сообщить; не использовать recursive cleanup как repair. Подозрительный EXE не исполнять.
- Повреждённый receipt: ремонт допускается только при восстановлении полномочий из independently verified catalog/journal в разрешённом root. Если доказательств нет — остановка и ручное решение. Не превращать отсутствие receipt в clean install.
- Symlink/junction в любом управляемом участке: отказ без обхода. Не удалять её цель. При изменении SID/root identity — отказ.

## 4. Install, reinstall, repair, update, rollback, uninstall

### 4.1. Предлагаемая транзакция обслуживания

Повторное использование package/slot/rollback engine принято только там, где совместимость подтверждена исходниками и тестами. Дополнительные installer-состояния и recovery ниже пока проектные: полная модель ownership/recovery остаётся открытой (§10.2).

Один per-user maintenance lock по SID/product/channel и совместимая проверка process lease для I/managed. Текущий session-local lease сам по себе не доказывает отсутствие процесса в другой Windows session этого пользователя. До операции обязателен проверяемый межсессионный протокол; при невозможности доказать остановку — BLOCKED.

Состояния установки: PREFLIGHT → PAYLOAD_VERIFIED → STAGED → COMMITTING → INSTALLED. Дополнительно CANCELLED, RECOVERY_REQUIRED и INTEGRATION_PENDING. INSTALLED означает проверенные файлы/ownership, не подтверждённый login/game/first-launch. Application readiness остаётся отдельным существующим ACK-контрактом. Никакого success после одного Popen.

### 4.2. Первый install одним NEXUS-Setup.exe

1. Setup asInvoker устанавливает identity текущего пользователя и Known Folders; валидирует место, ACL, диск, свободные байты для полных пакетов + staging + сохраняемых версий.
2. До распаковки проверяет подписанный catalog целого bootstrap bundle и первоначального клиента, длины/hash архивов, затем inventory. Бандл самого bootstrap требует собственного явного описания: подпись только клиентского ZIP не покрывает внешний NEXUS.exe/_internal.
3. Распаковывает только в собственную операцию на томе назначения с проверками существующего package engine; если bootstrap payload не подходит его формату, нужен узкий адаптер verified descriptor, а не отключение проверок.
4. Фиксирует согласованную после отдельного выбора bootstrap layout и ownership. Selector/bootstrap-slot применимы только при утверждении соответствующего варианта. Начальный client provision переиспользует `provision_initial` после подтверждения совместимости и адаптации stable root; не объявляет новую схему над старыми beta receipts.
5. Публикует ARP/Start Menu после commit. При сбое интеграции оставляет восстановимый INTEGRATION_PENDING, не теряет installed files.
6. Desktop shortcut — явный checkbox. «Запустить NEXUS» — отдельное действие после проверки целостности; SAC-отказ отображается честно, не лечится настройками защиты.

Принято для проектирования: установщик распространяется **одним `NEXUS-Setup.exe`**, устанавливающим полный onedir-комплект, включая `NEXUS.exe`, `_internal` и необходимые ресурсы, без ручной распаковки пользователем. Это не означает onefile-installed-client и не утверждает installer framework или selector. Предлагается встроить полные payload, чтобы первый install не требовал сетевого feed. Если bundle/metadata истекли, нужен актуальный утверждённый Setup; даты/подписи не правятся на машине пользователя.

### 4.3. Повторная установка и repair

- Существующая проверенная установка той же identity: verify/repair и восстановление только выбранных интеграций; не новый профиль/install_id.
- Отсутствующие или повреждённые программные файлы заменяются из проверенного bundle в новый полный bootstrap/application slot. Восстановление ровно той же разрешённой identity не считается разрешением downgrade.
- Не перезаписывать файлы работающего процесса. Предложить штатное закрытие с согласием; timeout/unknown → отказ. Не завершать процесс по одному совпадению имени NEXUS.exe и не принуждать все процессы пользователя к остановке.
- Корруптированный binary в доказанно принадлежащем слоте можно изолировать как непригодный, но очистка требует своих ownership checks. Незаявленные файлы сохраняются.
- Отсутствующий указатель не «угадывается» по максимальному имени каталога; использовать проверенный journal/recovery. Повторная установка не стирает trust history или настройки.

### 4.4. Update и rollback

Application updates используют существующие slots/transition/health owners. Не создавать второй механизм распаковки, ACK или pointer switching внутри Setup. Проверка безопасности/минимального выпуска должна поступать от отдельно допущенного trust layer; legacy field `minimum_supported_version` не является доказанным min-safe floor.

Открытый вариант: bootstrap обслуживается полным immutable onedir-slot; selector, если выбран, не переключает его до проверки всех файлов. Старую пару EXE/DLL не обновлять по частям. Кандидат первого Desktop выпуска — bootstrap replacement отдельным утверждённым Setup после остановки, без автоматического self-update selector. Обновление самого selector и его recoverable receipt требуют отдельного выбора и проверки; эти механизмы ещё не утверждены и не реализованы.

Rollback приложения разрешён только после подтверждённой остановки кандидата, проверки прежнего package и разрешённости его security policy. UNKNOWN не означает FAILED. Не откатывать metadata high-water и не возвращать отозванный/слишком старый выпуск. Истечение envelope установленной версии отличается от права установить нового кандидата (F07).

Профиль между версиями должен быть обратно совместим. Непроверенная необратимая миграция данных блокирует обещание rollback. ACK готовности не подтверждает совместимость схемы данных.

### 4.5. Uninstall

Принято для проектирования: по умолчанию удалить только доказанно принадлежащие программе файлы и собственные интеграции Windows. D, credentials, серверные аккаунты, пользовательские builds/projects/worlds и beta-каталоги сохраняются. Default uninstall не делает logout/revoke и не обращается к серверу. Отдельная очистка данных в этой версии не реализуется. Конкретные worker, receipt и recovery-механизмы ниже пока предложения, не утверждённая реализация удаления.

Uninstaller запускает проверенный maintenance worker из собственной операции вне удаляемого immutable slot, ждёт точного завершения исходного процесса и проверяет lease. Никаких shell-строк `rmdir /s`, wildcard по профилю и запланированного удаления произвольного пути на reboot. Self-removal worker — только bounded, journalled и после установления владения; если нельзя безопасно удалить себя, оставить известный остаток, не расширять permissions.

Удалять файлы по проверенному manifest с повторными handle/reparse checks; при несоответствии содержимого сохранить и сообщить. Каталоги удалять снизу вверх только если пусты. Не выполнять recursive delete root по строке из receipt/config/registry. Неполный uninstall сохраняет tombstone/recovery state вне удаляемого slot до завершения, не сообщает COMPLETE.

Повторная установка после uninstall переиспользует стабильный профиль и trust history только после валидации их identity/schema. Удаление программы не даёт права повторно привязать устройство к другому аккаунту или сбросить серверные ограничения.

## 5. Данные и миграция

Принято для проектирования: stable и beta раздельны; legacy/RC4/beta не мигрируют автоматически. **Импорт несекретных настроек пока не утверждён**: ниже указаны ограничения возможного будущего импорта, а не обещанная функция первого выпуска.

| Источник | План для stable Desktop |
| --- | --- |
| Legacy Setup/RC4 в пользовательском каталоге | Не считать owned новой установкой; не запускать/удалять автоматически. Stable ставится отдельно. |
| Распакованный bootstrap beta2 | Остаётся независимым private beta-комплектом; не переписать его metadata в stable. |
| `NEXUS Tester/managed-beta` | Не копировать active pointers, slots, подписанные journals или trust state в stable. |
| `NEXUS Tester/beta` | Не переносить profile, device state или staging credentials автоматически. |
| `%APPDATA%/.nexus-launcher` и вложенные legacy/tester roots | Только явный import выбранных несекретных настроек с source/schema checks и preview изменений. Ничего не перемещать. |
| Existing builds/worlds по `install_root` | После согласия пользователя подключить существующий путь либо импортировать копию; не считать сборку owned installer. |

Принятый путь для старого пользователя: отдельный stable install → вход через соответствующий account service → пользователь сам решает судьбу старого клиента. Опциональный проверяемый import несекретных настроек/подключение сборок можно добавить только после отдельного решения и preservation-проверок. Стабильная учётная запись должна быть подтверждена production account service, а не локальным beta-флагом. Этот контракт не разрешает включать production endpoint.

Ручное подтверждение обязательно для: закрытия работающего клиента; импорта/подключения внешних данных; замены существующего ярлыка, созданного не этой установкой; исключительного recovery при утраченных receipts; последующего удаления старой установки. Импорт не переносит passwords/tokens или admin/tester grants. Исходник сохраняется; failed import не делает целевой профиль частично активным.

Логи: bounded, ротация, только фиксированные диагностические поля; без codes/passwords/tokens/email/body. Старый tester.log и новые diagnostics нельзя объявлять полностью очищенными одной интеграцией. Новая stable logging policy требует отдельной проверки.

## 6. Windows integration и выбор инструментария

### 6.1. Ярлыки и Installed apps

Принято для проектирования: Start Menu shortcut создаётся по умолчанию, Desktop — только по выбору пользователя; автозапуска нет. Предлагаемые имена: per-user `FOLDERID_Programs/NEXUS/NEXUS.lnk` и `FOLDERID_Desktop/NEXUS.lnk`, с учётом перенаправления папки. Цель — согласованная фиксированная точка входа I/NEXUS.exe; считать её selector можно только после отдельного утверждения. Не выбирать произвольный последний slot. Working directory задаётся явно; пути и аргументы не объединяются в shell-команду. Icon — проверенный файл из управляемой установки. AppUserModelID стабильный для stable, отдельный для beta.

Использовать штатные `IShellLinkW`/`IPersistFile` и Known Folder API. Они доступны через ctypes/COM interop, но в проекте не подтверждён готовый безопасный wrapper. Не предполагать наличие pywin32/comtypes/WSH. Repair проверяет link target/arguments/owner receipt и восстанавливает только собственный/явно выбранный ярлык; чужую одноимённую ссылку не затирает.

Предложение ARP: `HKCU/Software/Microsoft/Windows/CurrentVersion/Uninstall/NEXUS.Desktop.Stable` с DisplayName, DisplayVersion, Publisher, DisplayIcon, InstallLocation, EstimatedSize, UninstallString и NoModify/NoRepair согласно реальным возможностям. Registry paths фиксированы в compiled product policy. Не задавать WindowsInstaller=1 для не-MSI. Строка удаления корректно цитирует проверенный путь и поддерживаемый mode; путь из реестра не является полномочием для удаления. Не публиковать неработающий QuietUninstallString. Каналы используют разные product identities.

### 6.2. Сравнение вариантов

| Вариант | Плюсы | Ограничения / решение этого проекта |
| --- | --- | --- |
| Existing Python/PySide6 + PyInstaller | Уже есть сборка, UI и package/slot/security owners; без обязательного нового runtime у пользователя | Требуются новые installer ownership/recovery и Windows COM/registry wrappers; extraction/размер onefile; подпись Windows не появляется. **Один из кандидатов**, не утверждённый framework и не готовый installer. |
| Inno Setup / NSIS | Готовые wizard/shortcuts/uninstall и per-user installation | Новый build toolchain; custom slot/trust engine всё равно отдельно; безопасный uninstall и recovery надо доказать. Не выбран и не установлен. |
| MSI/WiX / MSIX | Стандартный servicing/registration | Новые toolchain/package constraints, модель изменяемых slots/профиля и trust/signing надо отдельно проверить. Не считать бесплатным решением SAC. Не выбран. |

Принято переиспользовать существующие package/slot/rollback owners там, где совместимость доказана; это не выбор Python framework для внешнего Setup. Конкретный installer framework остаётся открытым. Перед реализацией нужны сравнение экспериментов §10.2 и отдельное разрешение владельца. Не обещать безопасный uninstaller просто потому, что это умеет готовый wizard.

## 7. Границы доверия и release gates

| Механизм | Что доказывает / чего не доказывает |
| --- | --- |
| Authenticode | Издатель и целостность Windows PE при доверенной цепочке. У beta2 EXE отсутствует. |
| Ed25519 package envelope | Авторство разрешённого package metadata для закреплённого ключа. Не Windows publisher trust. |
| SHA-256/inventory | Соответствие байтов ожидаемому значению; авторство только при authenticated source ожидаемых хешей. |
| TUF v2 | Отдельная будущая цепочка trust/rotation/freshness. Нельзя использовать незаполненный anchor или выдавать hiddenimport за интеграцию. |
| Smart App Control | Решение ОС о допуске исполняемого файла. Setup/ZIP/receipt не дают обхода и не гарантируют допуск. |

Подпись первого клиентского ZIP не защищает автоматически внешний Setup/selector/bootstrap. Первоначальное доверие к полученному Setup остаётся отдельной границей; HTTPS и независимое подтверждение артефакта не заменяют trusted Authenticode. Данный документ не выпускает ключей, сертификатов и production releases.

Не включать feed, не заменять public keys, не переподписывать manifests и не редактировать сроки. Stable требует отдельной build identity/API/keyring/root policy, а не изменения одного beta JSON. **Tester остаётся beta-каналом; stable и beta trust stores не объединяются. Существующая stable-конфигурация не меняется из-за разработки Desktop Setup.** Окончательные stable trust/Authenticode-схема и подключение удалённого feed ещё не утверждены. Test keys никогда не становятся release roots. TUF Trust Phase 2 остаётся незавершённой независимо от Desktop Phase 1.

## 8. Матрица сценариев

| Сценарий | Обязательный результат |
| --- | --- |
| Чистый профиль, обычный пользователь | Install без UAC, точный I, отдельный D, проверенные payload/receipt, ярлыки по выбору |
| Unicode/пробелы/не-BMP | Полный install → запуск → repair → uninstall без потерь/изменения имени |
| Длинный путь | Все операции, в том числе Shell и cleanup, доказаны без реестровых изменений; иначе release BLOCKED |
| Недостаточно места | Отказ до commit; старый active/profile сохранены |
| Повреждённый архив, подпись/hash/entrypoint | Нет activation/ярлыка на непроверенный EXE |
| Занятый I без ownership | Отказ, никаких adoption/overwrite/recursive cleanup |
| Повтор Setup той же сборки | Verify/repair; stable профиль и trust history сохранены |
| Работающий клиент или другая session | Согласованное закрытие либо BLOCKED, без частичной замены |
| Power loss на каждом install/repair/registry/link шаге | Однозначный receipt/journal и recoverable action; не blind replay |
| Падение нового приложения | Существующий health/stop/rollback-контракт; безопасный предыдущий слот либо BLOCKED |
| Неизвестный живой процесс | UNKNOWN; нет второго процесса или unsafe rollback |
| Corrupt receipt / чужой SID / junction / hardlink attack | Fail closed; внешние bytes неизменны |
| Неизвестные файлы при uninstall | Сохранить и сообщить, удалить лишь доказанно owned |
| Обычный uninstall | Удалить программу/свои ссылки/ARP, сохранить D, beta, external worlds и account credentials |
| Uninstall interrupted / worker locked | Восстановимый pending state, честное сообщение об остатках |
| Старый RC4 и beta рядом | Stable ставится отдельно; нет чтения credentials или изменения старой установки |
| Login/server unavailable / offline | Install не объявляет аккаунт авторизованным; feed остаётся отключённым |
| SAC блокирует Setup/selector/bootstrap/DLL | Нет обхода; не сообщать successful application start |

## 9. Тесты и критерии приёмки

В этом этапе тесты/сборка не запускались. Наличие старых PASS не означает PASS для будущего Setup. Не складывать результаты разных snapshots как единый acceptance.

Обязательное покрытие перед выпуском:

1. Unit: Known Folder/root policy, SID/ACL, receipt schema/limits/UTF-8/duplicate keys, ownership, path canonicalization, unsafe registry/shortcut paths.
2. Property/adversarial: traversal, case duplicates, ADS/device names, reparse ancestor/leaf races, hardlinks, changed file after verification; нет записей/удалений за разрешённым root.
3. Existing package/slot suites: installer preservation, initial provision, package, transition, storage, health/IPC, startup backend/flow. Сохранить API и journals v1 либо отдельно утвердить versioned migration.
4. Реальная Windows fixture-проверка: fresh install/reinstall/repair/uninstall, русское имя пользователя, пробелы, emoji, длинные имена, другой том/отказ ACL, работающий child и две sessions. Только изолированные files/keys, не пользовательские credentials.
5. Failure injection: каждый persistent шаг/rename/receipt/shortcut/registry boundary, отказ диска, повреждение payload, отсутствие предыдущего безопасного выпуска.
6. Data preservation: byte-for-byte внешние проекты, исходный beta profile, stable profile и trust state до/после install/repair/update/uninstall. Реальные токены не читать; использовать fake keyring adapters.
7. COM/ARP: корректные target/args/cwd/icon/AppUserModelID, moved/modified shortcut, redirected Desktop, отсутствие per-machine изменений, uninstall из Windows Installed apps.
8. Frozen package: artifact-to-source provenance, полный inventory внешнего Setup/bootstrap и inner package, подписи библиотек, полный onedir, отсутствие secrets/test keys; offline first install без скрытой раздачи.
9. Полный применимый regression на фиксированном окружении плюс native acceptance; opt-in skips перечислены, не объявлены PASS. Текущий long-path failure — открытый блокер, не пропуск теста ради зелёного статуса.
10. Проверка SAC/Authenticode — отдельный gate; Ed25519/TUF не заменяет её. Никакого отключения защиты для приёмки.

Приёмка Desktop Phase 1: owner review архитектуры/каталогов/ownership/migration/Windows integration и явное разрешение следующего этапа. Приёмка реализации позже: все обязательные проверки с командами/результатами, воспроизводимая сборка и однозначный распространяемый артефакт. Этот документ не является таким разрешением.

## 10. Зафиксированные направления и открытые решения

### 10.1. Принято владельцем для проектирования

Все девять пунктов ниже имеют статус **СОГЛАСОВАНО ДЛЯ ПРОЕКТИРОВАНИЯ / НЕ РЕАЛИЗОВАНО**. Они не дают разрешения создавать Setup, selector, install receipt, uninstaller или менять приложение на этом этапе.

| № | Согласованное направление |
| --- | --- |
| 1 | Первая Desktop-версия — Windows x64, только текущий пользователь, без административных прав и установки для всех пользователей. |
| 2 | Каталог программы — `%LOCALAPPDATA%/Programs/NEXUS`, получаемый через Windows Known Folder API. |
| 3 | Отдельный stable data root — `%LOCALAPPDATA%/NEXUS/stable`; он не принадлежит обычному uninstall. |
| 4 | Stable и beta разделены. Нет автоматического переноса beta credentials, trust state, active pointers, journals или тестовых grants в stable. Tester остаётся beta-каналом; stable trust store не подменяется beta-набором. |
| 5 | Один распространяемый `NEXUS-Setup.exe` устанавливает полный onedir-комплект, включая `NEXUS.exe`, `_internal` и необходимые ресурсы; ручная распаковка ZIP не требуется. Framework и selector этим не выбираются. |
| 6 | Start Menu shortcut по умолчанию; Desktop shortcut только по выбору пользователя; автозапуск не добавлять. |
| 7 | Default uninstall удаляет только подтверждённо принадлежащие программе файлы и собственные интеграции Windows; профиль, credentials, проекты, игровые сборки и beta-данные сохраняются. |
| 8 | Legacy/RC4/beta не мигрируют автоматически. Возможность ограниченного импорта несекретных настроек рассматривается отдельно и пока не обещана. |
| 9 | Существующий package/slot/rollback engine переиспользуется там, где совместимость подтверждена исходниками и тестами; дублирующий updater не создаётся. |

Соответствие исходным восьми review-вопросам: scope/root и stable data согласованы по направлению; ярлыки и default uninstall согласованы по направлению; отсутствие автоматической legacy migration согласовано, импорт остаётся отдельным вопросом. Bootstrap selector, framework и блокеры Windows/trust остаются открытыми. Полный ownership/recovery не считается утверждённым только из-за согласованной политики удаления.

### 10.2. Не утверждено: минимальные доказательства перед выбором

Эксперименты в таблице **не выполнены и не разрешены к запуску этим редактированием**. Это минимальные предложения для отдельного допуска; они не заменяют матрицу приёмки §8–9.

| Открытый вопрос | Минимальный эксперимент или доказательство перед решением | Условие для дальнейшего выбора |
| --- | --- | --- |
| Нужен ли новый selector для версионированного bootstrap | Сравнить два локальных fixture-сценария: полный bootstrap onedir под управлением ручного Setup без selector и две bootstrap-версии с минимальным selector. Смоделировать прерывание на persistent границах, занятые EXE/DLL, невалидный pointer, повреждённый кандидат и прежнюю рабочую версию. Без запуска NEXUS и без ключей релиза. | Проверяемые результаты показывают, какой вариант даёт требуемое восстановление без смешивания EXE/DLL, без второго updater и с приемлемой новой доверенной поверхностью. Владелец отдельно выбирает вариант. |
| Конкретный installer framework | Подготовить проверяемое сравнение existing Python/PyInstaller, Inno/NSIS и MSI/MSIX по per-user install, полному onedir, ownership, recoverable servicing, Windows integration, toolchain и ограничениям распространения. После отдельного разрешения — одинаковый минимальный offline fixture install/repair/uninstall для кандидатов; без установки новых инструментов по умолчанию. | Доказана совместимость с принятыми корнями, сохранением данных и существующим engine; стоимость поддержки и непокрытые сценарии явно перечислены. Один файл Setup сам по себе не доказывает пригодность framework. |
| Полный ownership/recovery при повреждённом install receipt | Временный fixture-root с синтетическим manifest: отсутствующий, усечённый, подменённый receipt, чужой SID/root, изменённый hash, неизвестный файл и reparse-подмена. Проверить отказ от удаления/усыновления и восстановление только из независимо проверяемого catalog/journal; внешние sentinels byte-for-byte неизменны. | Показано, откуда берётся полномочие recovery, если receipt недостоверен; отсутствуют blind reset/recursive delete. Окончательные schema и алгоритм требуют отдельного утверждения. |
| Окончательные stable trust и Authenticode signing | Завершить обязательные проверки Trust Phase 2 на тестовых ключах, подтвердить разделение каналов и происхождение anchor; отдельно описать авторство внешнего Setup, bootstrap и клиента. Для Authenticode — установить реально доступный поддерживаемый путь signing и проверить цепочку на отдельном разрешённом образце. До появления такого пути статус остаётся нерешённым. | Нет генерации/замены production-ключей по умолчанию. TUF/Ed25519 не выдаются за Windows publisher trust. Signing-вариант, его условия и применимость к stable отдельно утверждает владелец. |
| Как и когда подключать remote feed | После допуска trust-механизма — отдельно разрешённый изолированный metadata/transport fixture с явной download auth policy, allowlist, expiry/replay/rollback и сетевыми отказами; затем отдельный staging двухверсионный эксперимент по утверждённому scope. Не изменять текущий `feed:null`. | Подтверждены авторизация, цепочка доверия и безопасные исходы; endpoint, channel и момент включения требуют отдельного решения владельца. Локальный install не означает разрешение remote updates. |
| Поддержка длинных путей end-to-end | На согласованном Python/Windows повторить узкие fixture-проверки rename и последующего read, enumerate, repair, cleanup и Shell для Unicode/пробелов/не-BMP и полного пути длиннее MAX_PATH. Зафиксировать реальный отказ ordinary read отдельно от extended API; не уменьшать имя и не менять реестр ради PASS. | Все требуемые операции проходят в заявленном диапазоне без ослабления pinning/path checks. До этого поддержки end-to-end и закрытого блокера нет. |
| Готовность к публичному выпуску | Единый release passport: источник/build/artifact hashes, schema/config, полный применимый regression с объяснёнными skips, Windows native install/repair/uninstall и account/game acceptance, отдельный SAC gate и проверенный полный распространяемый bundle. Свести результаты к одному выпуску, а не суммировать snapshots. | Отсутствуют открытые обязательные блокеры; release scope и распространение отдельно одобрены владельцем. Успешный прототип или один pytest-прогон недостаточны. |

Безопасность путей, сохранение пользовательских данных, отсутствие обхода SAC и запрет смешивать stable/beta не являются опциями для ослабления в этих экспериментах. Включение импорта legacy-настроек также требует отдельного решения и preservation-доказательства.

### 10.3. Следующий разрешённый шаг

**Сейчас разрешено только обновление и проверка Markdown-контракта. Разрешения на прототип ещё нет.** Предлагаемый следующий шаг после отдельного допуска — узкий локальный прототип размещения полного onedir-пакета (`NEXUS.exe`, `_internal`, ресурсы) в явно выделенном пустом тестовом каталоге, без записи в реальные I/D.

Для прототипа заранее ограничить входы тестовым inventory/фикстурами, подтвердить применимость существующих package/path owners и проверять полноту файлов, сохранность внешних sentinels, отказ на повреждённом payload и прерывание размещения. Не исполнять вложенный NEXUS, не принимать beta-пакет за stable и не включать feed. Это исследование установки полного комплекта, не выпуск Setup.

До отдельного утверждения соответствующего scope не создавать новый selector, production install receipt/recovery, uninstaller, ярлыки/ARP registration или framework toolchain. Если узкому прототипу потребуется даже тестовая новая ownership-схема, сначала описать её и получить разрешение, а не считать утверждённой по этой записи.

После прототипа — отдельный отчёт и решение владельца. Согласованные направления не завершают Desktop Phase 1 автоматически и не разрешают реализацию следующего этапа.

### Справочные Windows API

- [Known Folder IDs](https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid): UserProgramFiles/LocalAppData/Programs/Desktop; это основание выбора per-user root, не проверка конкретной машины.
- [Shell Links](https://learn.microsoft.com/en-us/windows/win32/shell/links): IShellLink/IPersistFile.
- [Uninstall registry properties](https://learn.microsoft.com/en-us/windows/win32/msi/uninstall-registry-key): справочник полей MSI; не утверждение, что NEXUS является MSI. Предложенная HKCU-схема non-MSI требует runtime acceptance.

Документ не утверждает завершение Desktop Phase 1, Trust Phase 2, наличие работающего Setup.exe или готовность публичного выпуска.
