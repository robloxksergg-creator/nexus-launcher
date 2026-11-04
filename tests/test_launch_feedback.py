from nexus_launcher.launch_feedback import launch_failure_message


def test_known_errors_explain_recovery_without_raw_transport_details():
    assert 'переустанавливать сборку не требуется' in launch_failure_message('GAME_TICKET_UNAVAILABLE')
    message = launch_failure_message("Connection broken: IncompleteRead(8551913 bytes read, 7982536 expected)")
    assert 'DOWNLOAD_INTERRUPTED' in message
    assert '8551913' not in message
    message = launch_failure_message("HTTPSConnectionPool(host='maven.neoforged.net', port=443): connect timeout=None")
    assert 'NEOFORGE_UNAVAILABLE' in message
    assert 'timeout=None' not in message


def test_unrelated_validation_failure_keeps_its_specific_guidance():
    text = 'Для сборки требуется Java 21 x64.'
    assert launch_failure_message(text) == text
