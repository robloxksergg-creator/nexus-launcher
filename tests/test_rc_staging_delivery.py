import nexus_launcher.updater as updater


def test_staging_artifact_origin_is_build_gated(monkeypatch):
    monkeypatch.setattr(updater.build_channel, "STAGING_BUILD", False)
    monkeypatch.delenv("NEXUS_ENVIRONMENT", raising=False)
    assert updater.STAGING_DOWNLOAD_HOST not in updater.trusted_download_hosts()
    monkeypatch.setenv("NEXUS_ENVIRONMENT", "staging")
    # Untrusted environment variables cannot expand production download trust.
    assert updater.STAGING_DOWNLOAD_HOST not in updater.trusted_download_hosts()
    monkeypatch.setattr(updater.build_channel, "STAGING_BUILD", True)
    assert updater.STAGING_DOWNLOAD_HOST in updater.trusted_download_hosts()
