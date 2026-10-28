import io
import json
from email.message import Message
from unittest.mock import patch

from nexus_launcher.nexus_account import NexusAccountClient


class FakeResponse:
    def __init__(self, payload, content_type="application/json"):
        self.payload = payload
        self.stream = io.BytesIO(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        return self.stream.read(size)


def test_login_stores_token_and_loads_skin():
    replies = [
        FakeResponse(
            {
                "token": "a" * 64,
                "user": {
                    "minecraftNick": "Builder",
                    "email": "b@nexus.test",
                    "skinUrl": "/api/launcher/profile/skin",
                    "skinModel": "slim",
                },
            }
        ),
        FakeResponse(b"png", "image/png"),
    ]
    with patch("nexus_launcher.nexus_account.open_https", side_effect=replies), patch("nexus_launcher.nexus_account.keyring.set_password") as save:
        profile = NexusAccountClient("https://example.test").login("Builder", "password")
    assert profile.minecraft_nick == "Builder"
    assert profile.skin_png == b"png"
    assert profile.skin_model == "slim"
    save.assert_called_once()


def test_restore_without_saved_session_is_logged_out():
    with patch("nexus_launcher.nexus_account.keyring.get_password", return_value=None):
        assert NexusAccountClient().restore() is None
