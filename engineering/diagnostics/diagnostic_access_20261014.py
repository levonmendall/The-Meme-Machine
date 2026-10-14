"""Disposable diagnostic-output access checks; no supervisor or market imports."""
import argparse
import grp
import inspect
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile
import time
import uuid

from meme_machine.operational.observation import atomic_json
from meme_machine.runtime.sqlite_failure import MAX_TERMINAL_BYTES, write_terminal_record

# Copy the installed filesystem/identity controls, rather than testing root's
# access or silently weakening a service namespace. No application environment
# or credentials are passed to this network-disabled, disposable probe.
ACCESS_PROPERTIES = (
    'User', 'Group', 'SupplementaryGroups', 'DynamicUser', 'UMask',
    'WorkingDirectory', 'RootDirectory', 'RootImage', 'PrivateUsers',
    'ProtectSystem', 'ProtectHome', 'PrivateTmp', 'NoNewPrivileges',
    'ReadWritePaths', 'ReadOnlyPaths', 'InaccessiblePaths', 'BindPaths',
    'BindReadOnlyPaths', 'TemporaryFileSystem', 'PrivateDevices',
    'ProtectKernelTunables', 'ProtectKernelModules', 'ProtectControlGroups',
    'RestrictNamespaces',
)
PROBE_SECONDS = 15
PROBE_BYTES = 8192
PROBE_FILES = ('clock.json', 'probe-result.json', 'supervisor-fatal.json',
               'source-sqlite-terminal.txt')


def service_identity(properties):
    user = properties.get('User', '')
    if not user or properties.get('DynamicUser') != 'no' or properties.get('PrivateUsers') != 'no':
        raise ValueError('diagnostic_access_static_service_identity_required')
    account = pwd.getpwuid(int(user)) if user.isdecimal() else pwd.getpwnam(user)
    group = properties.get('Group') or str(account.pw_gid)
    gid = int(group) if group.isdecimal() else grp.getgrnam(group).gr_gid
    groups = set(os.getgrouplist(account.pw_name, gid))
    for value in properties.get('SupplementaryGroups', '').split():
        groups.add(int(value) if value.isdecimal() else grp.getgrnam(value).gr_gid)
    if account.pw_uid == 0:
        raise ValueError('diagnostic_access_service_must_not_be_root')
    return dict(uid=account.pw_uid, gid=gid, groups=sorted(groups))


def validate_output(output, state_root):
    output, state_root = Path(output), Path(state_root)
    if (not output.is_absolute() or not state_root.is_absolute() or
            not output.is_dir() or output.is_symlink() or output.stat().st_mode & 0o077):
        raise ValueError('output_must_be_existing_private_directory')
    if output.resolve() == state_root.resolve() or state_root.resolve() in output.resolve().parents:
        raise ValueError('output_must_be_outside_economic_state')


def prepare_output(output, properties, *, diagnostic_parent=Path('/var/lib/meme-machine-diagnostics')):
    """Explicit, repeatable parent repair; create only a fresh private run."""
    output = Path(output)
    identity = service_identity(properties)
    if os.geteuid() != 0 or not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError('diagnostic_access_root_and_fresh_run_required')
    parent = output.parent
    if (parent != Path(diagnostic_parent) or parent.is_symlink() or
            parent.resolve() != parent.absolute()):
        raise ValueError('diagnostic_access_exact_parent_required')
    parent.mkdir(mode=0o710, exist_ok=True)
    if not parent.is_dir() or parent.stat().st_uid != 0:
        raise ValueError('diagnostic_access_root_owned_parent_required')
    os.chown(parent, 0, identity['gid'])
    os.chmod(parent, 0o710)  # mkdir(exist_ok=True) cannot repair existing modes.
    output.mkdir(mode=0o700)
    os.chown(output, identity['uid'], identity['gid'])
    os.chmod(output, 0o700)
    return identity


def probe_command(probe_dir, properties, identity, revision):
    if any(key not in properties for key in ACCESS_PROPERTIES):
        raise ValueError('diagnostic_access_unit_properties_incomplete')
    command = ['systemd-run', '--quiet', '--wait', '--collect', '--service-type=exec',
               '--unit=meme-machine-diagnostic-access-' + uuid.uuid4().hex]
    for key in ACCESS_PROPERTIES:
        value = properties[key]
        if value:
            command.append('--property=' + key + '=' + value)
    command += ['--property=PrivateNetwork=yes', '--property=IPAddressDeny=any',
                '--property=RestrictAddressFamilies=AF_UNIX', '--property=RuntimeMaxSec=10',
                '--property=TimeoutStopSec=2', '--property=Restart=no',
                '--property=MemoryMax=128M', '--setenv=PYTHONDONTWRITEBYTECODE=1',
                sys.executable, '-c', probe_payload(),
                '--probe-dir', str(probe_dir), '--identity', json.dumps(identity),
                '--revision', revision]
    return command


def probe_payload():
    # A trusted, bounded program from the exact reviewed implementation. It does
    # not need the new helper installed or make /root visible to ProtectHome.
    # The existing installed atomic_json is the actual filesystem writer.
    return ('import argparse, json, os, time\nfrom pathlib import Path\n'
            'from meme_machine.operational.observation import atomic_json\n'
            'PROBE_BYTES = 8192\nMAX_TERMINAL_BYTES = 65536\n' +
            inspect.getsource(write_terminal_record) + '\n' + inspect.getsource(read_probe) + '\n' +
            inspect.getsource(service_probe) + '\n' +
            "p=argparse.ArgumentParser(); p.add_argument('--probe-dir', required=True); "
            "p.add_argument('--identity', required=True); p.add_argument('--revision', required=True); "
            "a=p.parse_args(); service_probe(Path(a.probe_dir), json.loads(a.identity), a.revision)\n")


def read_probe(path):
    with Path(path).open('rb') as stream:
        body = stream.read(PROBE_BYTES + 1)
    if len(body) > PROBE_BYTES:
        raise ValueError('diagnostic_access_probe_output_bound')
    return body


def check_access(output, state_root, revision, properties, *, write_metadata, run=subprocess.run,
                 stop_probe=subprocess.run):
    """Required before the real clock/start; no access result is cached."""
    output = Path(output)
    validate_output(output, state_root)
    identity = service_identity(properties)
    if (output.stat().st_uid, output.stat().st_gid) != (identity['uid'], identity['gid']):
        raise ValueError('diagnostic_access_run_owner_mismatch')
    if any(output.iterdir()):
        raise ValueError('new_private_output_directory_required')
    probe_dir = Path(tempfile.mkdtemp(prefix='.access-probe-', dir=output))
    os.chown(probe_dir, identity['uid'], identity['gid'])
    os.chmod(probe_dir, 0o700)
    cleanup_allowed = True
    try:
        # Exactly the controller's writer and current umask, but entirely inside
        # the disposable child. This clock never becomes the observation clock.
        write_metadata(probe_dir, 'clock.json', dict(access_probe=True, revision=revision,
                                                   origin_monotonic=0))
        clock_mode = (probe_dir / 'clock.json').stat().st_mode & 0o777
        command = probe_command(probe_dir, properties, identity, revision)
        try:
            completed = run(command, capture_output=True, text=True,
                            timeout=PROBE_SECONDS, check=False)
        except subprocess.TimeoutExpired:
            # Stop only this independently named, network-disabled probe before
            # removing its own files. Never send a PAPER start/stop request here.
            unit = next(value.removeprefix('--unit=') for value in command if value.startswith('--unit='))
            cleanup_allowed = False
            stopped = stop_probe(['systemctl', 'stop', unit], capture_output=True, text=True,
                                 timeout=5, check=False)
            verified = stop_probe(['systemctl', 'show', unit, '-p', 'MainPID', '--value'],
                                  capture_output=True, text=True, timeout=5, check=False)
            if stopped.returncode != 0 or verified.returncode != 0 or verified.stdout.strip() != '0':
                raise ValueError('diagnostic_access_probe_stop_unverified')
            cleanup_allowed = True
            raise ValueError('diagnostic_access_service_probe_timeout') from None
        if completed.returncode != 0:
            raise ValueError('diagnostic_access_service_probe_failed')
        result = json.loads(read_probe(probe_dir / 'probe-result.json'))
        if result != dict(identity, revision=revision, clock_read=True, atomic_replace=True,
                          ancestors_traversable=True, clock_mode=clock_mode, run_mode=0o700):
            raise ValueError('diagnostic_access_service_proof_mismatch')
        if (json.loads(read_probe(probe_dir / 'supervisor-fatal.json')) != dict(access_probe=True) or
                read_probe(probe_dir / 'source-sqlite-terminal.txt') != b'diagnostic_access_probe\n'):
            raise ValueError('diagnostic_access_controller_read_failed')
        return dict(verified=True, identity=identity, network='DISABLED',
                    filesystem_properties={key: properties[key] for key in ACCESS_PROPERTIES},
                    simulated_clock_only=True, controller_clock_mode=clock_mode, probe_run_mode=0o700)
    finally:
        # Exact probe-owned files only; no recursive evidence deletion.
        if cleanup_allowed:
            for name in PROBE_FILES:
                for path in (probe_dir / name, probe_dir / (name + '.tmp')):
                    path.unlink(missing_ok=True)
            probe_dir.rmdir()


def service_probe(probe_dir, identity, revision):
    """Small bounded program executed under the installed service's identity."""
    probe_dir = Path(probe_dir)
    actual = dict(uid=os.geteuid(), gid=os.getegid(), groups=sorted(set(os.getgroups())))
    if actual != identity:
        raise ValueError('diagnostic_access_effective_identity_mismatch')
    for ancestor in (probe_dir, *probe_dir.parents):
        if not os.access(ancestor, os.X_OK, effective_ids=True):
            raise ValueError('diagnostic_access_ancestor_not_traversable')
    clock = json.loads(read_probe(probe_dir / 'clock.json'))
    if clock != dict(access_probe=True, revision=revision, origin_monotonic=0):
        raise ValueError('diagnostic_access_simulated_clock_mismatch')
    atomic_json(probe_dir / 'supervisor-fatal.json', dict(access_probe=False))
    atomic_json(probe_dir / 'supervisor-fatal.json', dict(access_probe=True))
    write_terminal_record(probe_dir / 'source-sqlite-terminal.txt', 'diagnostic_access_probe\n')
    atomic_json(probe_dir / 'probe-result.json', dict(identity, revision=revision,
                clock_read=True, atomic_replace=True, ancestors_traversable=True,
                clock_mode=(probe_dir / 'clock.json').stat().st_mode & 0o777,
                run_mode=probe_dir.stat().st_mode & 0o777))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe-dir', required=True, type=Path)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    service_probe(args.probe_dir, json.loads(args.identity), args.revision)
