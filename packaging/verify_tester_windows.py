"""Exact owner-signed beta packages; native Windows, local transport only.

No signing key, public feed mutation, account login or game launch.
"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import zipfile


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def reconstruct(archive, approval, output):
    from nexus_launcher.signed_release import canonical, verify_envelope
    from nexus_launcher.portable_package import verify_portable_archive
    compact = json.loads(Path(approval).read_text('utf-8'))
    if compact['release']['channel'] != 'beta' or digest(archive) != compact['release']['sha256']:
        raise ValueError('Unexpected beta package')
    files = []
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            with source.open(member) as stream:
                sha = hashlib.file_digest(stream, 'sha256').hexdigest()
            files.append({'path': member.filename, 'size': member.file_size, 'sha256': sha})
    payload = {**compact['release'], 'files': files}
    if hashlib.sha256(canonical(payload)).hexdigest() != compact['canonical_sha256']:
        raise ValueError('Signed payload reconstruction mismatch')
    envelope = {k: compact[k] for k in ('schema', 'key_id', 'signature')}
    envelope['release'] = payload
    verify_envelope(envelope)
    verify_portable_archive(archive, envelope)
    Path(output).write_text(json.dumps(envelope), encoding='utf-8')
    return envelope


def verify(initial, update, installer, approvals, output, root, installer_sha):
    import nexus_launcher.build_channel as channel
    channel.PUBLIC_PREVIEW_BUILD = True
    from nexus_launcher import public_update_identity
    if public_update_identity.CHANNEL != 'beta':
        raise ValueError('Beta verification source required')
    if digest(installer) != installer_sha:
        raise ValueError('Unexpected installer')
    output = Path(output)
    output.mkdir(exist_ok=False, parents=True)
    first = reconstruct(initial, Path(approvals) / 'baseline-approval.json', output / 'initial-envelope.json')
    latest = reconstruct(update, Path(approvals) / 'update-approval.json', output / 'update-envelope.json')
    if [first['release']['version'], latest['release']['version']] != ['1.0.11', '1.0.12']:
        raise ValueError('Unexpected acceptance versions')
    harness = runpy.run_path(str(Path(__file__).with_name('verify_managed_windows.py')))
    result = harness['verify'](initial, output / 'initial-envelope.json', update,
        output / 'update-envelope.json', Path(root) / 'transition', output / 'two-version.json')
    # Exercise the actual provisioning path independently of the slot transition.
    from nexus_launcher.github_updates import GitHubPackageTransport
    from nexus_launcher.online_installation import install, installation_details
    from nexus_launcher.windows_bootstrap_process import WindowsLaunchLease
    transport = GitHubPackageTransport(public_update_identity.FEED)
    def local_open(url):
        if url == transport.manifest_url:
            return (output / 'update-envelope.json').open('rb')
        if url == latest['release']['url']:
            return Path(update).open('rb')
        raise ValueError('Unexpected offline URL')
    transport._open = local_open
    phases = []
    install_root = Path(root) / 'fresh'
    with WindowsLaunchLease(install_root):
        target = install(install_root, installer, transport, lambda phase, *_: phases.append(phase))
        details = installation_details(target)
    if details.version != '1.0.12' or phases[-1] != 'COMPLETE' or digest(target) != installer_sha:
        raise ValueError('Full installation acceptance failed')
    result.update(channel='beta', fresh_install_version=details.version,
                  files_verified=details.file_count, installer_copy_verified=True,
                  network='local fixture only; no live feed/accounts/game',
                  stable_feed_changed=False)
    (output / 'TESTER-ACCEPTANCE.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('initial', 'update', 'installer', 'approvals', 'output', 'root', 'installer-sha'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.initial, args.update, args.installer, args.approvals,
                            args.output, args.root, args.installer_sha)))
