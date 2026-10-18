"""Regression for Colab torch/torchvision incompatibility; no real model loading."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from src.text_environment import check_packages, probe
from tests.test_phase2b import mocked_adapter, ROOT
from tests.support.optimind_experiment import run


def good():
    return dict(torch='2.13.0+cu130', transformers='5.12.1', accelerate='1.15.0')


def test_reported_colab_versions_pass_without_vision():
    assert check_packages(good())['passed']


def test_reported_vision_conflict_detected():
    result=check_packages(dict(good(), torchvision='0.26.0+cu130'), ['torch (==2.11.0)', 'numpy'])
    assert not result['passed']
    assert any('TORCHVISION_TORCH_MISMATCH' in reason for reason in result['reasons'])


def test_even_compatible_vision_is_unnecessary_in_text_profile():
    result=check_packages(dict(good(), torchvision='0.28.0+cu130'), ['torch==2.13.0'])
    assert not result['passed']
    assert not any('MISMATCH' in reason for reason in result['reasons'])


@pytest.mark.parametrize('name',['torch','transformers','accelerate'])
def test_missing_or_changed_pin_blocks(name):
    packages=good();packages.pop(name)
    assert not check_packages(packages)['passed']
    packages[name]='0.0.1'
    assert not check_packages(packages)['passed']


def test_probe_does_not_import_broken_stack(monkeypatch):
    monkeypatch.setattr('src.text_environment.installed_check', lambda:dict(passed=False,reasons=['vision conflict']))
    assert not probe()['imports_passed']


def test_probe_imports_without_loading(monkeypatch):
    import sys
    monkeypatch.setattr('src.text_environment.installed_check',lambda:check_packages(good()))
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:True),version=SimpleNamespace(cuda='13.0')))
    monkeypatch.setitem(sys.modules,'transformers',SimpleNamespace(AutoTokenizer=object,AutoModelForCausalLM=object,set_seed=object))
    report=probe()
    assert report['passed'] and report['imports_passed'] and not report['model_loaded']


def test_failed_attempt_is_immutable_and_retry_id_is_new(tmp_path):
    args=(ROOT/'tests/fixtures/config/scenarios/single.yaml',ROOT/'tests/fixtures/config/ai/optimind_v2.yaml',tmp_path,'unused')
    failed,_=run(*args,adapter=mocked_adapter('E1',error=RuntimeError('torchvision::nms')))
    original={str(p.relative_to(failed)):p.read_bytes() for p in failed.rglob('*') if p.is_file()}
    retry,record=run(*args,adapter=mocked_adapter('E1','Math\n```python\nx=1\n```'))
    assert retry!=failed and record['attempt_id']==retry.name
    assert original=={str(p.relative_to(failed)):p.read_bytes() for p in failed.rglob('*') if p.is_file()}


def test_notebook_defaults_to_preparation_and_preserves_checkpoint():
    cells=json.loads((ROOT/'tests/fixtures/notebooks/run_optimind.ipynb').read_text())['cells']
    sources=[''.join(c['source']) for c in cells if c['cell_type']=='code']
    for source in sources:compile(source,'notebook','exec')
    assert any('RUN_INFERENCE = False' in s for s in sources)
    inference=next(s for s in sources if 'statuses = {}' in s)
    assert inference.startswith('if not RUN_INFERENCE:')
    install=next(s for s in sources if 'inference_install.log' in s)
    assert "'uninstall', '-y', 'torchvision'" in install
    assert 'text_environment_after.json' in install
    assert any("'--ai-config', str(RUN_CONFIG)" in s for s in sources)
    assert any('PINNED_AI_SOURCE = destination' in s for s in sources)


@pytest.mark.parametrize('failure', ['vision', 'lazy_import'])
def test_worker_fails_before_any_checkpoint_download(failure, tmp_path, monkeypatch):
    import sys
    import src.inference_worker as worker
    from tests.test_phase2b import info, effective, checkpoint
    hw = info()
    if failure == 'vision':
        hw['packages']['torchvision'] = '0.26.0+cu130'
    monkeypatch.setattr(worker, 'inventory', lambda *args: hw)
    monkeypatch.setattr(worker, 'require_runtime', lambda *args: True)
    downloads = []
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(snapshot_download=lambda **kwargs: downloads.append(kwargs)))
    # Missing lazy symbol models the original failure; no model object is created.
    monkeypatch.setitem(sys.modules, 'transformers', SimpleNamespace(AutoTokenizer=object, set_seed=object))
    monkeypatch.setenv('CUDA_VISIBLE_DEVICES', '')
    with pytest.raises((ValueError, ImportError)):
        worker.generate(dict(settings=effective('E1').model_dump(), checkpoint=checkpoint(),
                             backend='TRANSFORMERS', cache_dir=str(tmp_path),
                             runtime_evidence='unused', messages=[]), tmp_path)
    assert downloads == []


def test_probe_blocks_without_cuda(monkeypatch):
    import sys
    monkeypatch.setattr('src.text_environment.installed_check', lambda: check_packages(good()))
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False), version=SimpleNamespace(cuda=None)))
    monkeypatch.setitem(sys.modules, 'transformers', SimpleNamespace(AutoTokenizer=object, AutoModelForCausalLM=object, set_seed=object))
    report = probe()
    assert not report['passed'] and 'CUDA_NOT_AVAILABLE' in report['reasons']
