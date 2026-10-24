"""Restore exact current Hermes source from the pinned existing archive and delta.

Requires a new --output directory and the canonical --repository directory.
No source is executed. All Python network access and Git transports are denied.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import socket
import sys


def deny_network(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.sendto'):
        raise PermissionError('Offline source reconstruction denies network access')


def verify_checkout(directory, revision, git):
    if git(directory, 'rev-parse', 'HEAD').decode().strip() != revision:
        raise RuntimeError('Restored checkout commit differs from the target')
    if git(directory, 'status', '--porcelain').strip():
        raise RuntimeError('Restored checkout is not clean')


def restore(repository, output):
    sys.addaudithook(deny_network)
    here = Path(__file__).resolve().parent
    repository = repository.resolve(strict=True)
    lock = json.loads((here / 'source-delta-lock.json').read_text(encoding='utf-8'))
    with (repository/'provenance/reconstruct.py').open('rb') as handle:
        if hashlib.file_digest(handle, 'sha256').hexdigest() != lock['materializer_sha256']:
            raise ValueError('Materializer source differs from the reviewed pin')
    sys.path.insert(0, str(repository / 'provenance'))
    from reconstruct import _inventory, _materialize, digest, git
    baseline = repository/'integrations/hermes'
    archive = here/lock['archive']['file']
    inventory_file = here/lock['inventory']['file']
    base_archive = baseline/lock['baseline']['archive']['file']
    for path, expected in ((archive,lock['archive']['sha256']),
            (inventory_file,lock['inventory']['sha256']),
            (base_archive,lock['baseline']['archive']['sha256']),
            (baseline/lock['baseline']['inventory']['file'],lock['baseline']['inventory']['sha256'])):
        if not path.is_file() or digest(path) != expected:
            raise ValueError('Source artifact hash differs')
    if archive.stat().st_size != lock['archive']['bytes'] or base_archive.stat().st_size != lock['baseline']['archive']['bytes']:
        raise ValueError('Source archive size differs')
    expected_header = ('# v2 git bundle\n-'+lock['base_revision']+' preserved source prerequisite\n'+lock['revision']+' HEAD\n\n').encode()
    with archive.open('rb') as handle:
        if handle.read(len(expected_header)) != expected_header:
            raise ValueError('Unexpected delta prerequisites or references')
    inventory = _inventory(json.loads(inventory_file.read_text(encoding='utf-8')),lock['revision'],lock['upstream_url'])
    if inventory['tree'] != lock['tree']:
        raise ValueError('Target tree mismatch')
    output = output.expanduser().absolute()
    output = output.parent.resolve(strict=True)/output.name
    if os.path.lexists(output):
        raise ValueError('Output already exists; nothing modified')
    output.mkdir()
    git(output,'init','--quiet')
    python_blocked = False
    try:
        socket.create_connection(('example.com',443),timeout=1)
    except PermissionError:
        python_blocked = True
    import subprocess
    git_blocked = False
    try:
        git(output,'ls-remote','https://example.com/offline-control.git')
    except subprocess.CalledProcessError as error:
        git_blocked = b"transport 'https' not allowed" in error.stderr
    if not python_blocked or not git_blocked:
        raise RuntimeError('Network denial positive control failed')
    git(output,'bundle','verify',str(base_archive))
    git(output,'bundle','unbundle',str(base_archive))
    (output/'.git/shallow').write_text(lock['base_revision']+'\n',encoding='ascii')
    git(output,'update-ref','HEAD',lock['base_revision'])
    source = dict(archive=archive,inventory=inventory,revision=lock['revision'],descriptor=lock)
    result = _materialize(output,source)
    verify_checkout(output, lock['revision'], git)
    result.update(schema=1,passed=True,offline=True,python_network_denied=python_blocked,
        git_https_denied=git_blocked,exact_target_commit=True,clean_checkout=True,
        baseline_archive_sha256=lock['baseline']['archive']['sha256'],
        source_delta_lock_sha256=digest(here/'source-delta-lock.json'),
        scope='Complete target source snapshot only; no dependency installation or model execution')
    (output/'.git/adaptive-current-source.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(restore(args.repository,args.output),indent=2))
