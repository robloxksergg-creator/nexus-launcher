"""Fake token/opener only. No host access, real keyring or server operations."""
from contextlib import nullcontext
from dataclasses import replace
import unittest

from nexus_launcher.projects import ServerProfile
from nexus_launcher.server_controller import PterodactylServerController


class Keyring:
    def __init__(self):
        self.reads = 0
    def get_password(self, *args):
        self.reads += 1
        return 'synthetic-test-token'


class Reply:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def read(self):
        return b'{}'


class PanelCredentialTests(unittest.TestCase):
    def setUp(self):
        self.profile = ServerProfile('main', 'Sample', 'play.example.test',
            panel_url='https://mgr.bisquit.host', panel_server_id='0d2ad2ea')
        self.keyring = Keyring()
        self.requests = []
    def controller(self, **changes):
        def opener(request, timeout):
            self.requests.append(request)
            return Reply()
        return PterodactylServerController(replace(self.profile, **changes),
            opener=opener, keyring_module=self.keyring,
            authorization=lambda permission: nullcontext())

    def test_valid_panel_and_server_preserve_existing_api(self):
        self.controller()._request('/resources')
        self.assertEqual(self.keyring.reads, 1)
        self.assertEqual(self.requests[0].full_url,
            'https://mgr.bisquit.host/api/client/servers/0d2ad2ea/resources')

    def test_foreign_panel_rejected_before_reading_token(self):
        for url in ['https://attacker.example', 'https://mgr.bisquit.host.attacker.example',
                    'http://mgr.bisquit.host', 'https://mgr.bisquit.host:444',
                    'https://user:secret@mgr.bisquit.host',
                    'https://mgr.bisquit.host/api', 'https://mgr.bisquit.host?redirect=evil',
                    'https://mgr.bisquit.host#evil', ' https://mgr.bisquit.host']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.controller(panel_url=url)._request('/resources')
        self.assertEqual(self.keyring.reads, 0)
        self.assertEqual(self.requests, [])

    def test_server_id_injection_refused_without_token(self):
        for identifier in ['../other', '0d2ad2ea/../../other', '0d2ad2ea?x=1', '', '0d2ad2ea ']:
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                self.controller(panel_server_id=identifier)._request('/resources')
        self.assertEqual(self.keyring.reads, 0)
        self.assertEqual(self.requests, [])

    def test_log_path_cannot_bypass_origin_boundary(self):
        result = self.controller(panel_url='https://attacker.example').latest_log()
        self.assertNotIn('synthetic-test-token', result)
        self.assertEqual(self.keyring.reads, 0)
        self.assertEqual(self.requests, [])

    def test_missing_authorization_still_denies_before_token(self):
        controller = self.controller()
        def deny(permission):
            raise PermissionError('denied')
        controller._authorization = deny
        with self.assertRaises(PermissionError):
            controller._request('/resources')
        self.assertEqual(self.keyring.reads, 0)
        self.assertEqual(self.requests, [])


if __name__ == '__main__':
    unittest.main()
