"""Verify uploaded test sources and exact collection against a release manifest."""
import json
import os
from pathlib import Path
import subprocess
import sys
from .persistence import hash_file

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/suite_manifest.json'


def check_suite_files(root=ROOT, manifest_path=MANIFEST):
    manifest = json.loads(Path(manifest_path).read_text())
    actual = {p.relative_to(root).as_posix(): hash_file(p) for p in sorted((Path(root)/'tests').rglob('*.py'))}
    expected = manifest['files']
    return manifest, dict(missing=sorted(expected.keys()-actual.keys()),
                          unexpected=sorted(actual.keys()-expected.keys()),
                          changed=sorted(k for k in expected.keys() & actual.keys() if expected[k] != actual[k]))


def run_tests(folder):
    folder = Path(folder).resolve()
    manifest, files = check_suite_files()
    report_path = folder/'tests.json'
    command = [sys.executable, '-m', 'pytest', '-q', '-ra', '-o', 'addopts=',
               '-p', 'src.pytest_evidence', '--runtime-test-report', str(report_path), 'tests']
    env = os.environ.copy()
    env.pop('PYTEST_ADDOPTS', None)
    env.pop('PYTEST_PLUGINS', None)
    env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    with (folder/'tests.log').open('w') as log:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=600)
    data = json.loads(report_path.read_text()) if report_path.exists() else {}
    actual_ids, expected_ids = set(data.get('nodeids', [])), set(manifest['nodeids'])
    reasons = []
    if any(files.values()): reasons.append('TEST_SOURCE_MISMATCH')
    if actual_ids != expected_ids: reasons.append('TEST_COLLECTION_MISMATCH')
    if result.returncode != 0 or data.get('exit_code') != 0: reasons.append('PYTEST_FAILED')
    if data.get('skipped', 0): reasons.append('TESTS_SKIPPED')
    if data.get('passed') != len(manifest['nodeids']): reasons.append('INCOMPLETE_TEST_PASS_COUNT')
    return dict(**data, passed_gate=not reasons, reasons=reasons, source_files=files,
                expected_count=len(expected_ids), missing_nodeids=sorted(expected_ids-actual_ids),
                unexpected_nodeids=sorted(actual_ids-expected_ids), interpreter=sys.executable,
                cwd=str(ROOT), command=command, manifest_hash=hash_file(MANIFEST))
