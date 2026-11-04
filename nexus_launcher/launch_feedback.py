"""Recovery instructions for known failures; no credentials or URLs in copy."""


def launch_failure_message(text):
    if 'GAME_TICKET_UNAVAILABLE' in text:
        return ('Сервис игровых пропусков NEXUS временно недоступен. '
                'Игра не запускалась. Повторите запуск позже; переустанавливать сборку не требуется. '
                'Код: GAME_TICKET_UNAVAILABLE.')
    if 'IncompleteRead' in text:
        return ('Соединение оборвалось до завершения загрузки. Повторите попытку: '
                'уже проверенные файлы сохранятся, незавершённые будут загружены повторно. '
                'Код: DOWNLOAD_INTERRUPTED.')
    if 'maven.neoforged.net' in text and any(marker in text.lower() for marker in ('timeout', 'timed out', 'connectionpool')):
        return ('Не удалось дождаться ответа сервера NeoForge. Проверьте подключение и повторите запуск. '
                'Переустанавливать лаунчер не требуется. Код: NEOFORGE_UNAVAILABLE.')
    return text
