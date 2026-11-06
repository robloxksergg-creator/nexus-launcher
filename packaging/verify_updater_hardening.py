"""Offline regression runner. No product signing keys, game, accounts or feed."""
from pathlib import Path
import sys
from unittest.mock import patch
import pytest

TESTS=[
 'test_update_reliability','test_resumable_download','test_portable_transition',
 'test_portable_bootstrap','test_startup_portable_backend','test_startup_update_flow',
 'test_self_update','test_github_updates','test_portable_package','test_signed_update',
 'test_bootstrap_installation','test_posix_updates','test_posix_update_signing',
 'test_public_update_identity','test_beta_update_trust',
 'test_pack_download_reliability','test_native_transfer','test_native_http',
 'test_functional_pass5','test_parallel_pack_staging','test_parallel_downloads','test_updater',
]

def main():
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root))
    # Tests patch transport with local signed fixtures. Unexpected parent HTTP
    # fails; synthetic child processes exercise only private inherited pipes.
    with patch('socket.create_connection',side_effect=AssertionError('Outbound transport forbidden')):
        return pytest.main(['-q','-ra','-p','no:cacheprovider',
                            '--junitxml='+str(root/'updater-hardening-results.xml'),
                            '--deselect='+str(root/'tests/test_functional_pass5.py')+'::test_progress_phases_do_not_report_network_speed_during_verify',
                            *[str(root/'tests'/(name+'.py')) for name in TESTS]])

if __name__=='__main__':raise SystemExit(main())
