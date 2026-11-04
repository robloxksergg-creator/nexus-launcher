"""Bound network waits in pinned minecraft-launcher-lib installation helpers.

Keep Requests' certificate/proxy behavior and the library's parsing/checksums.
Do not patch Requests globally or the Microsoft account API module.
"""
import requests

NETWORK_TIMEOUT = (10, 30)


class BoundedSession(requests.Session):
    def request(self, method, url, **kwargs):
        if kwargs.get('timeout') is None:
            kwargs['timeout'] = NETWORK_TIMEOUT
        return super().request(method, url, **kwargs)


class InstallationRequests:
    Session = BoundedSession

    @staticmethod
    def session():
        return BoundedSession()

    @staticmethod
    def get(url, **kwargs):
        if kwargs.get('timeout') is None:
            kwargs['timeout'] = NETWORK_TIMEOUT
        return requests.get(url, **kwargs)

    def __getattr__(self, name):
        return getattr(requests, name)


def configure_installation_http():
    from minecraft_launcher_lib import _helper, install, runtime
    for module in (_helper, install, runtime):
        if module.requests is requests:
            module.requests = InstallationRequests()
