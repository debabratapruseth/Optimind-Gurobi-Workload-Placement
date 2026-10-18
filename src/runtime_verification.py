"""Colab/Drive evidence collection; no inference dependency or model installation."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4
from .hardware import inventory, hardware_key
from .main import source_hashes
from .persistence import json_write, hash_file
from .formulation_check import run as demo
from .test_suite_verification import run_tests, ROOT, check_suite_files


def seal(folder):
    folder = Path(folder)
    json_write(folder/'COMPLETE.json', {str(p.relative_to(folder)):hash_file(p) for p in sorted(folder.rglob('*')) if p.is_file() and p != folder/'COMPLETE.json'})


def verify_artifacts(folder):
    """Check declared manifests before any copy, including nested evidence."""
    folder = Path(folder).resolve()
    if any(p.is_symlink() for p in folder.rglob('*')):
        raise ValueError('symlink artifacts unsupported')
    for marker in folder.rglob('COMPLETE.json'):
        for name, expected in json.loads(marker.read_text()).items():
            target = (marker.parent/name).resolve()
            if not target.is_relative_to(marker.parent.resolve()) or not target.is_file() or hash_file(target) != expected:
                raise ValueError(f'artifact integrity mismatch: {marker.relative_to(folder)}: {name}')


def sync_verified(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError('sync roots must be distinct and non-nested')
    verify_artifacts(source)
    if destination.exists():
        verify_artifacts(destination)
    files = [p for p in source.rglob('*') if p.is_file()]
    hashes = {str(p.relative_to(source)):hash_file(p) for p in files}
    # Repeated synchronization is idempotent; never replace different evidence.
    for name, expected in hashes.items():
        target = destination/name
        if target.exists() and (not target.is_file() or hash_file(target) != expected):
            raise ValueError('destination evidence conflict: '+name)
    shutil.copytree(source, destination, dirs_exist_ok=True)
    for name, expected in hashes.items():
        if hash_file(destination/name) != expected:
            raise ValueError('synchronization hash mismatch: '+name)
    verify_artifacts(destination)
    return dict(verified=True, file_count=len(hashes), source=str(source), destination=str(destination))


def drive_mounted(path):
    path = Path(path).resolve()
    return Path('/content/drive/MyDrive').is_dir() and os.path.ismount('/content/drive') and path.is_relative_to('/content/drive/MyDrive')


def verify_runtime(output, drive_output=None, config=ROOT/'config/scenario.yaml'):
    folder = Path(output).resolve()/('runtime-'+uuid4().hex[:12]);folder.mkdir(parents=True)
    info = inventory(folder)
    report = dict(version=3, project_root=str(ROOT), interpreter=sys.executable, hardware=info, hardware_key=hardware_key(info), source_hashes=source_hashes(),
                  tests_passed=False, benchmarks={}, restricted_license=False, drive={'verified':False}, ready_for_inference=False,
                  colab_verification='PENDING' if not info['colab'] else 'FAILED')
    json_write(folder/'environment.json', info)
    stage = 'VERIFICATION'
    try:
        report['tests'] = run_tests(folder)
        report['tests_passed'] = report['tests']['passed_gate']
        from .pipeline import load_problem
        _, sources = load_problem(config)
        report['scenario_config'] = str(Path(config).resolve())
        report['input_hashes'] = {k: v['sha256'] for k, v in sources.items()}
        path, attempt = demo(Path(config).resolve(), folder/'application', settings=ROOT/'config/runtime/verification.yaml')
        passed = attempt.failure_classification == 'VALID_FORMULATION' and attempt.independent_placement_audit.get('valid')
        report['benchmarks']['application'] = dict(passed=bool(passed), folder=str(path.relative_to(folder)), classification=attempt.failure_classification, solver=attempt.solver)
        report['restricted_license'] = all(v['solver'].get('license_verified_from_startup_log') for v in report['benchmarks'].values()) and bool(report['benchmarks'])
        if source_hashes() != report['source_hashes']:
            raise ValueError('SOURCE_CHANGED_DURING_VERIFICATION')
        _, suite_files = check_suite_files()
        if any(suite_files.values()):
            report['tests_passed'] = False
            report['tests']['source_files_after'] = suite_files
            report['tests']['reasons'].append('TEST_SOURCE_MISMATCH')
        if drive_output is not None:
            stage = 'SYNCHRONIZATION'
            if not drive_mounted(drive_output): raise ValueError('GOOGLE_DRIVE_MOUNT_NOT_VERIFIED')
            destination = Path(drive_output)/folder.name
            # Copy immutable test/benchmark evidence first; runtime.json is finalized below.
            report['drive'] = sync_verified(folder, destination)
        report['ready_for_inference'] = bool(info['colab'] and info['gpus'] and report['tests_passed'] and set(report['benchmarks']) == {'application'} and all(v['passed'] for v in report['benchmarks'].values()) and report['restricted_license'] and report['drive']['verified'])
        report['colab_verification'] = 'VERIFIED' if report['ready_for_inference'] else 'PENDING' if not info['colab'] else 'FAILED'
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
        report['failure_stage'] = stage
    report['readiness_reasons'] = readiness_reasons(report)
    json_write(folder/'runtime.json', report)
    seal(folder)
    if drive_output is not None and drive_mounted(drive_output):
        try: sync_verified(folder, Path(drive_output)/folder.name)
        except Exception as exc:
            report.update(ready_for_inference=False,colab_verification='FAILED',failure_stage='FINAL_SYNCHRONIZATION',error='FINAL_SYNC_FAILED: '+str(exc))
            report['drive']['verified'] = False
            report['readiness_reasons'] = readiness_reasons(report)
            json_write(folder/'runtime.json',report);seal(folder)
    return folder, report


def readiness_reasons(report):
    reasons = list(report.get('tests', {}).get('reasons', []))
    if not report['tests_passed']: reasons.append('TEST_SUITE_NOT_PASSED')
    if not report['hardware']['colab']: reasons.append('NOT_COLAB')
    if not report['hardware']['gpus']: reasons.append('NO_GPU')
    if set(report['benchmarks']) != {'application'} or not all(v['passed'] for v in report['benchmarks'].values()):
        reasons.append('BENCHMARKS_NOT_PASSED')
    if not report['restricted_license']: reasons.append('RESTRICTED_LICENSE_NOT_VERIFIED')
    if not report['drive']['verified']: reasons.append('DRIVE_SYNC_NOT_VERIFIED')
    if report.get('error'): reasons.append(report['error'])
    return reasons


def require_runtime(path, info):
    folder = Path(path)
    verify_artifacts(folder)
    for name, expected in json.loads((folder/'COMPLETE.json').read_text()).items():
        target=(folder/name).resolve()
        if not target.is_relative_to(folder.resolve()) or hash_file(target)!=expected: raise ValueError('runtime evidence integrity failure')
    report=json.loads((folder/'runtime.json').read_text())
    if not report['ready_for_inference'] or report['colab_verification']!='VERIFIED': raise ValueError('COLAB_RUNTIME_VERIFICATION_PENDING')
    if report['hardware_key']!=hardware_key(info) or report['source_hashes']!=source_hashes(): raise ValueError('STALE_RUNTIME_VERIFICATION')
    for package in ('gurobipy','pydantic','pyyaml','pytest'):
        if report['hardware']['packages'].get(package)!=info['packages'].get(package): raise ValueError('CORE_DEPENDENCIES_CHANGED')
    if report.get('version', 1) >= 2:
        _, files = check_suite_files()
        if any(files.values()) or report['tests']['manifest_hash'] != hash_file(ROOT/'tests/suite_manifest.json'):
            raise ValueError('STALE_TEST_SUITE_VERIFICATION')
    if report.get('version', 1) >= 3:
        from .pipeline import load_problem
        _, sources = load_problem(report['scenario_config'])
        if report['input_hashes'] != {k: v['sha256'] for k, v in sources.items()}:
            raise ValueError('STALE_SCENARIO_VERIFICATION')
    if not drive_mounted(report['drive']['destination']): raise ValueError('GOOGLE_DRIVE_MOUNT_LOST')
    destination = Path(report['drive']['destination'])
    verify_artifacts(destination)
    if report.get('version', 1) >= 2 and any(hash_file(destination/name) != hash_file(folder/name) for name in ('runtime.json', 'COMPLETE.json')):
        raise ValueError('RUNTIME_SYNC_EVIDENCE_MISMATCH')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',default='results/runtime');p.add_argument('--drive-output')
    p.add_argument('--config', default=str(ROOT/'config/scenario.yaml'))
    args=p.parse_args();folder,report=verify_runtime(args.output,args.drive_output,args.config)
    print(folder, report['colab_verification'])
    tests = report.get('tests', {})
    print('Tests:', {k: tests.get(k) for k in ('expected_count', 'collected', 'passed', 'failed', 'skipped')})
    for failure in tests.get('failed_tests', []):
        print('FAILED:', failure['nodeid'], failure['reason'].splitlines()[-1][:300])
    print('Test source mismatches:', tests.get('source_files'), tests.get('source_files_after'))
    print('Failure stage:', report.get('failure_stage'))
    print('Readiness:', report['ready_for_inference'], report['readiness_reasons'])
    print('Full evidence:', folder/'tests.log', folder/'tests.json', folder/'runtime.json')
    raise SystemExit(0 if report['ready_for_inference'] else 2)

if __name__=='__main__':main()
