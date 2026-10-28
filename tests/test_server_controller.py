from contextlib import nullcontext

import sys
import time

from nexus_launcher.projects import ServerProfile
from nexus_launcher.server_controller import LocalServerController, PterodactylServerController


class FakeCommandController(LocalServerController):
    def __init__(self, server, command, callback):
        super().__init__(server, callback, authorization=lambda _permission: nullcontext())
        self.command = command

    def build_command(self):
        return self.command


def wait_for(predicate, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition was not reached")


def test_local_controller_console_command_and_graceful_stop(tmp_path):
    script = tmp_path / "fake_server.py"
    script.write_text(
        "import sys\n"
        "print('READY', flush=True)\n"
        "for line in sys.stdin:\n"
        " command=line.strip()\n"
        " print('COMMAND:'+command, flush=True)\n"
        " if command == 'stop': break\n",
        encoding="utf-8",
    )
    jar = tmp_path / "server.jar"
    jar.write_bytes(b"fake")
    server = ServerProfile("test", "Test", "localhost", working_directory=str(tmp_path))
    events = []
    controller = FakeCommandController(
        server, [sys.executable, "-u", str(script)], lambda kind, value: events.append((kind, value))
    )
    assert controller.start()
    wait_for(lambda: "READY" in controller.console)
    assert not controller.start()
    assert controller.send_command("say hello")
    wait_for(lambda: "COMMAND:say hello" in controller.console)
    first_pid = controller.state.pid
    controller.restart()
    wait_for(lambda: controller.state.status == "running" and controller.state.pid != first_pid)
    wait_for(lambda: list(controller.console).count("READY") >= 2)
    controller.stop(timeout=2)
    wait_for(lambda: controller.state.status == "stopped")
    assert controller.state.exit_code == 0
    assert any(kind == "state" for kind, _value in events)


def test_eula_is_not_accepted_automatically(tmp_path):
    (tmp_path / "server.jar").write_bytes(b"fake")
    (tmp_path / "eula.txt").write_text("eula=false\n", encoding="utf-8")
    server = ServerProfile("test", "Test", "localhost", working_directory=str(tmp_path), java_path=sys.executable)
    controller = LocalServerController(server, authorization=lambda _permission: nullcontext())
    assert not controller.start()
    assert controller.state.status == "error"
    assert "EULA" in controller.state.last_error


def test_command_is_an_argument_list_without_shell(tmp_path):
    jar = tmp_path / "server.jar"
    jar.write_bytes(b"fake")
    server = ServerProfile(
        "test",
        "Test",
        "localhost",
        working_directory=str(tmp_path),
        java_path=sys.executable,
        server_jar="server.jar",
        min_memory_mb=1024,
        max_memory_mb=2048,
        additional_arguments='-Dmessage="hello world"',
    )
    command = LocalServerController(server, authorization=lambda _permission: nullcontext()).build_command()
    assert command[0] == sys.executable
    assert "-Xms1024M" in command
    assert "-Xmx2048M" in command
    assert "-Dmessage=hello world" in command
    assert command[-3:] == ["-jar", str(jar), "nogui"]


class FakeKeyring:
    @staticmethod
    def get_password(_service, _key):
        return "ptlc_test-token"


class FakeResponse:
    def __init__(self, payload=b"{}"):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.payload


def test_remote_bisquit_controller_uses_client_api_without_exposing_token():
    requests = []

    def opener(request, timeout):
        requests.append((request, timeout))
        if request.full_url.endswith("/resources"):
            return FakeResponse(b'{"attributes":{"current_state":"running"}}')
        return FakeResponse()

    server = ServerProfile(
        "nexus_launcher.main",
        "GearMorph",
        "5.83.140.209:25698",
        management_type="pterodactyl",
        panel_url="https://mgr.bisquit.host",
        panel_server_id="0d2ad2ea",
        credential_key="nexusmc/main/bisquit",
    )
    controller = PterodactylServerController(server, opener=opener, keyring_module=FakeKeyring(), authorization=lambda _permission: nullcontext())
    controller.refresh()
    assert controller.state.status == "running"
    assert controller.send_command("list")
    assert controller.start()
    assert requests[0][0].full_url.endswith("/api/client/servers/0d2ad2ea/resources")
    assert requests[0][0].headers["Authorization"] == "Bearer ptlc_test-token"
    assert "ptlc_test-token" not in "\n".join(controller.console)


def test_remote_bisquit_controller_tracks_top_level_metrics():
    def opener(request, timeout):
        assert timeout == 12
        return FakeResponse(
            b'{"resources":{"state":"running","cpu_absolute":12.5,'
            b'"memory_bytes":1073741824,"memory_limit_bytes":12884901888,'
            b'"disk_bytes":2147483648,"uptime":65000}}'
        )

    server = ServerProfile(
        "nexus_launcher.main",
        "GearMorph",
        "playgearmorph.bisquitmc.net",
        management_type="pterodactyl",
        panel_url="https://mgr.bisquit.host",
        panel_server_id="0d2ad2ea",
        credential_key="nexusmc/main/bisquit",
    )
    controller = PterodactylServerController(server, opener=opener, keyring_module=FakeKeyring(), authorization=lambda _permission: nullcontext())
    controller.refresh()
    assert controller.state.status == "running"
    assert controller.state.cpu_percent == 12.5
    assert controller.state.memory_bytes == 1073741824
    assert controller.state.memory_limit_bytes == 12884901888
    assert controller.state.disk_bytes == 2147483648
    assert 64 <= controller.state.uptime <= 66
