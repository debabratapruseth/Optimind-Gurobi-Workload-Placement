"""Runtime failure diagnostics and release completeness, without live inference."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from src import runtime_verification as runtime
from src import test_suite_verification as suite
from src.persistence import json_write, hash_file
from src.text_environment import installed_check, probe
from tests.test_phase2b import info, checkpoint, effective


@pytest.mark.parametrize('version', ['1.15.0', None, '1.14.0'])
def test_worker_accelerate_inventory_is_authoritative(version, tmp_path, monkeypatch):
    import src.inference_worker as worker
    hw = info()
    if version is None: hw['packages'].pop('accelerate')
    else: hw['packages']['accelerate'] = version
    monkeypatch.setattr(worker, 'inventory', lambda *a: hw)
    monkeypatch.setattr(worker, 'require_runtime', lambda *a: True)
    # Host imports cannot repair an incomplete mocked distribution inventory.
    monkeypatch.setitem(sys.modules, 'accelerate', SimpleNamespace(__version__='1.15.0'))
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace())
    monkeypatch.setenv('CUDA_VISIBLE_DEVICES', '')
    expected = ImportError if version == '1.15.0' else ValueError
    with pytest.raises(expected) as error:
        worker.generate(dict(settings=effective('E1').model_dump(), checkpoint=checkpoint(),
                             backend='TRANSFORMERS', cache_dir=str(tmp_path),
                             runtime_evidence='unused', messages=[]), tmp_path)
    if version != '1.15.0':
        assert f'PACKAGE_VERSION:accelerate:expected=1.15.0:actual={version}' in str(error.value)


def test_real_distribution_preflight_matches_current_interpreter():
    import importlib.metadata
    from src.text_environment import PINS
    report = installed_check()
    for name in PINS:
        try: actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: actual = None
        assert report['packages'][name] == actual
    result = probe()  # Imports only on an eligible stack; never loads weights.
    assert not result['model_loaded']
    assert result['passed'] == (not result['reasons'])


def test_uploaded_suite_detects_missing_and_stale_files(tmp_path):
    (tmp_path/'tests').mkdir()
    test = tmp_path/'tests/test_example.py';test.write_text('original')
    manifest = tmp_path/'manifest.json'
    json_write(manifest, dict(files={'tests/test_example.py':hash_file(test)}, nodeids=[]))
    test.write_text('stale')
    assert suite.check_suite_files(tmp_path, manifest)[1]['changed'] == ['tests/test_example.py']
    test.unlink()
    assert suite.check_suite_files(tmp_path, manifest)[1]['missing'] == ['tests/test_example.py']


@pytest.mark.parametrize('kind', ['failed', 'skipped', 'missing_collection'])
def test_suite_report_fails_closed(kind, tmp_path, monkeypatch):
    manifest = dict(nodeids=['tests/a.py::test_a'], files={})
    monkeypatch.setattr(suite, 'check_suite_files', lambda: (manifest, dict(missing=[], unexpected=[], changed=[])))
    def run(command, **kwargs):
        data = dict(nodeids=manifest['nodeids'], collected=1, passed=0, failed=0, skipped=0, exit_code=0)
        if kind == 'missing_collection': data.update(nodeids=[], collected=0)
        else: data[kind] = 1
        if kind == 'failed': data['exit_code'] = 1
        json_write(tmp_path/'tests.json', data)
        assert command[0] == sys.executable and kwargs['cwd'] == suite.ROOT
        assert 'PYTEST_ADDOPTS' not in kwargs['env']
        return SimpleNamespace(returncode=data['exit_code'])
    monkeypatch.setattr(suite.subprocess, 'run', run)
    result = suite.run_tests(tmp_path)
    assert not result['passed_gate'] and result['reasons']


def test_failed_tests_propagate_to_readiness(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, 'inventory', lambda *a: info())
    monkeypatch.setattr(runtime, 'run_tests', lambda *a: dict(passed_gate=False, reasons=['PYTEST_FAILED'],
        collected=1, passed=0, failed=1, skipped=0, failed_tests=[dict(nodeid='test_failure', reason='accelerate missing')]))
    def demo(config, output, **kwargs):
        return Path(output)/'demo', SimpleNamespace(failure_classification='VALID_FORMULATION',
            independent_placement_audit={'valid':True}, solver={'license_verified_from_startup_log':True})
    monkeypatch.setattr(runtime, 'demo', demo)
    monkeypatch.setattr(runtime, 'drive_mounted', lambda *a: True)
    folder, report = runtime.verify_runtime(tmp_path/'local', tmp_path/'drive')
    assert not report['ready_for_inference'] and report['colab_verification'] == 'FAILED'
    assert report['restricted_license'] and report['drive']['verified']
    assert 'PYTEST_FAILED' in report['readiness_reasons']
    assert report['tests']['failed_tests'][0]['nodeid'] == 'test_failure'
    assert (tmp_path/'drive'/folder.name/'COMPLETE.json').exists()


def test_pytest_plugin_reports_failure_skip_and_warning(tmp_path):
    import subprocess, os
    (tmp_path/'test_sample.py').write_text('import pytest, warnings\ndef test_ok():\n warnings.warn("diagnostic warning")\ndef test_bad():\n assert False, "explicit failure"\n@pytest.mark.skip(reason="sample skip")\ndef test_skip():\n pass\n')
    env = os.environ.copy();env['PYTHONPATH'] = str(suite.ROOT);env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    env.pop('PYTEST_ADDOPTS', None);env.pop('PYTEST_PLUGINS', None)
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'src.pytest_evidence',
        '--runtime-test-report', str(tmp_path/'report.json')], cwd=tmp_path, env=env, capture_output=True)
    data = json.loads((tmp_path/'report.json').read_text())
    assert result.returncode == 1
    assert (data['collected'], data['passed'], data['failed'], data['skipped']) == (3, 1, 1, 1)
    assert data['failed_tests'][0]['nodeid'] == 'test_sample.py::test_bad'
    assert 'explicit failure' in data['failed_tests'][0]['reason']
    assert data['warnings'][0]['reason'] == 'diagnostic warning'
