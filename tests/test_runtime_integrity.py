"""Evidence integrity regressions; no inference or model downloads."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from src import runtime_verification as runtime
from src.test_suite_verification import check_suite_files, ROOT
from src.persistence import json_write, hash_file
from tests.test_phase2b import info


def fake_checks(monkeypatch):
    monkeypatch.setattr(runtime, 'inventory', lambda *a: info())
    monkeypatch.setattr(runtime, 'run_tests', lambda *a: dict(passed_gate=True, reasons=[],
        manifest_hash=hash_file(ROOT/'tests/suite_manifest.json')))
    def demo(config, output, **kwargs):
        assert Path(config).is_absolute() and Path(kwargs['settings']).is_absolute()
        return Path(output)/'demo', SimpleNamespace(failure_classification='VALID_FORMULATION',
            independent_placement_audit={'valid': True}, solver={'license_verified_from_startup_log': True})
    monkeypatch.setattr(runtime, 'demo', demo)
    monkeypatch.setattr(runtime, 'drive_mounted', lambda *a: True)


def test_manual_init_content_rejected(tmp_path):
    (tmp_path/'tests').mkdir()
    init=tmp_path/'tests/__init__.py';init.write_text((ROOT/'tests/__init__.py').read_text())
    manifest=tmp_path/'manifest.json';json_write(manifest,dict(files={'tests/__init__.py':hash_file(init)}))
    init.write_text('')  # Colab touch fixes imports but does not match the release.
    assert check_suite_files(tmp_path,manifest)[1]['changed']==['tests/__init__.py']
    json_write(manifest,dict(files={}))
    assert check_suite_files(tmp_path,manifest)[1]['unexpected']==['tests/__init__.py']


def test_corrupt_source_not_copied(tmp_path):
    source=tmp_path/'source';source.mkdir()
    json_write(source/'runtime.json',{'ready':False});runtime.seal(source)
    destination=tmp_path/'drive';runtime.sync_verified(source,destination)
    before={p.name:p.read_bytes() for p in destination.iterdir()}
    json_write(source/'runtime.json',{'ready':True})
    with pytest.raises(ValueError,match='integrity'):runtime.sync_verified(source,destination)
    assert before=={p.name:p.read_bytes() for p in destination.iterdir()}


def test_different_sealed_evidence_cannot_overwrite(tmp_path):
    source=tmp_path/'source';source.mkdir();json_write(source/'x.json',1);runtime.seal(source)
    destination=tmp_path/'drive';runtime.sync_verified(source,destination)
    json_write(source/'x.json',2);runtime.seal(source)
    with pytest.raises(ValueError,match='destination evidence conflict'):runtime.sync_verified(source,destination)
    assert json.loads((destination/'x.json').read_text())==1


def test_clean_finalization_and_repeat_sync_from_other_cwd(tmp_path, monkeypatch):
    fake_checks(monkeypatch);monkeypatch.chdir(tmp_path)
    folder,report=runtime.verify_runtime(tmp_path/'local',tmp_path/'drive')
    assert report['ready_for_inference'] and report['readiness_reasons']==[]
    dest=Path(report['drive']['destination'])
    for name in ('runtime.json','COMPLETE.json'):
        assert (folder/name).read_bytes()==(dest/name).read_bytes()
    runtime.verify_artifacts(folder);runtime.verify_artifacts(dest)
    assert runtime.sync_verified(folder,dest)['verified']
    runtime.require_runtime(folder,info())


def test_source_change_during_verification_fails(tmp_path,monkeypatch):
    fake_checks(monkeypatch)
    hashes=iter([{'source':'before'},{'source':'after'}])
    monkeypatch.setattr(runtime,'source_hashes',lambda:next(hashes))
    folder,report=runtime.verify_runtime(tmp_path/'local',tmp_path/'drive')
    assert not report['ready_for_inference']
    assert report['failure_stage']=='VERIFICATION'
    assert 'SOURCE_CHANGED_DURING_VERIFICATION' in report['error']
    runtime.verify_artifacts(folder)


def test_final_sync_failure_is_distinct_and_local_seal_valid(tmp_path,monkeypatch):
    fake_checks(monkeypatch)
    real_sync=runtime.sync_verified
    def sync(source,dest):
        if (Path(source)/'COMPLETE.json').exists(): raise OSError('disk unavailable')
        return real_sync(source,dest)
    monkeypatch.setattr(runtime,'sync_verified',sync)
    folder,report=runtime.verify_runtime(tmp_path/'local',tmp_path/'drive')
    assert not report['ready_for_inference'] and not report['drive']['verified']
    assert report['tests_passed'] and report['failure_stage']=='FINAL_SYNCHRONIZATION'
    runtime.verify_artifacts(folder)
    assert json.loads((folder/'runtime.json').read_text())==report


def test_nested_manifest_corruption_rejected(tmp_path):
    nested=tmp_path/'source'/'nested';nested.mkdir(parents=True)
    (nested/'data').write_text('original');runtime.seal(nested)
    (nested/'data').write_text('modified');runtime.seal(nested.parent)
    with pytest.raises(ValueError,match='integrity'):runtime.sync_verified(nested.parent,tmp_path/'drive')
    assert not (tmp_path/'drive').exists()


def test_scenario_change_invalidates_runtime(tmp_path, monkeypatch):
    fake_checks(monkeypatch)
    from tests.test_pipeline import scenario
    config=scenario(tmp_path)
    folder,report=runtime.verify_runtime(tmp_path/'local',tmp_path/'drive',config)
    assert report['ready_for_inference']
    import yaml
    card=tmp_path/'applications.yaml'
    data=yaml.safe_load(card.read_text());data['applications'][0]['demand']['cpu_vcpu']=33
    card.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError,match='STALE_SCENARIO_VERIFICATION'):
        runtime.require_runtime(folder,info())
