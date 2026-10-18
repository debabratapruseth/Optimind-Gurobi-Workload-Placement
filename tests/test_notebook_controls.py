"""Execute notebook control logic with fake subprocesses; never run inference."""
import json
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
import pytest
import yaml
from tests.test_phase2b import ROOT, effective, SHA


def cell_containing(text):
    n=json.loads((ROOT/'tests/fixtures/notebooks/run_optimind.ipynb').read_text())
    return next(''.join(c['source']) for c in n['cells'] if c['cell_type']=='code' and text in ''.join(c['source']))


def config_file(tmp_path):
    settings=effective('E1').model_dump();settings['model']['revision']=SHA
    path=tmp_path/'pinned_ai.yaml';path.write_text(yaml.safe_dump(settings))
    return path


def test_preparation_preserves_source_and_records_budget(tmp_path):
    source=config_file(tmp_path);before=source.read_bytes();calls=[]
    def run(command, **kwargs):
        calls.append(command)
        output=Path(command[command.index('--output')+1]);output.mkdir()
        cfg=Path(command[command.index('--ai-config')+1])
        (output/'pinned_ai.yaml').write_bytes(cfg.read_bytes())
    env=dict(PINNED_AI_SOURCE=source,DRIVE_PROJECT=tmp_path,RESULTS=tmp_path/'results',
             MAX_NEW_TOKENS=8192,uuid=uuid,json=json,sys=sys,subprocess=SimpleNamespace(run=run),
             BENCHMARK='tests/fixtures/config/scenarios/single.yaml',RUNTIME_EVIDENCE=tmp_path/'runtime',CACHE=tmp_path/'cache',
             RUNTIME_PROJECT=tmp_path,sync_verified=lambda *a:None)
    exec(cell_containing('prior_settings ='),env)
    assert source.read_bytes()==before
    generated=yaml.safe_load(env['PINNED_AI'].read_text())
    original=yaml.safe_load(before);original['inference']['max_new_tokens']=8192
    assert generated==original
    assert len(calls)==1 and 'tests.support.prepare_inference' in calls[0]


def launch_env(tmp_path):
    pin=config_file(tmp_path);settings=yaml.safe_load(pin.read_text());settings['inference']['max_new_tokens']=8192;pin.write_text(yaml.safe_dump(settings))
    proc=tmp_path/'proc';proc.mkdir()
    return dict(RUN_INFERENCE=True,SELECTED_EXPERIMENTS=['E2'],PINNED_AI=pin,MAX_NEW_TOKENS=8192,
        Path=lambda path:proc if path=='/proc' else Path(path),RUNTIME_PROJECT=tmp_path,RESULTS=tmp_path/'results',
        DRIVE_PROJECT=tmp_path/'drive',os=os,sys=sys,uuid=uuid,json=json,BENCHMARK='single',
        RUNTIME_EVIDENCE=tmp_path/'runtime',CACHE=tmp_path/'cache',sync_verified=lambda *a:None)


def test_live_worker_blocks_new_launch(tmp_path):
    env=launch_env(tmp_path);worker=tmp_path/'proc'/'123';worker.mkdir()
    (worker/'cmdline').write_bytes(b'python\0-m\0src.inference_worker\0request.json\0')
    with pytest.raises(AssertionError,match='Existing inference'):
        exec(cell_containing('if not RUN_INFERENCE:'),env)
    assert env['RUN_INFERENCE'] is False


def test_budget_change_requires_new_preflight(tmp_path):
    env=launch_env(tmp_path);env['MAX_NEW_TOKENS']=16384
    with pytest.raises(AssertionError,match='Budget changed'):
        exec(cell_containing('if not RUN_INFERENCE:'),env)
    assert not (tmp_path/'.notebook_inference.lock').exists()


def test_launch_consumes_opt_in_and_reexecution_does_not_launch(tmp_path):
    env=launch_env(tmp_path);calls=[]
    def run(command, **kwargs):
        assert (tmp_path/'.notebook_inference.lock').exists()
        calls.append(command)
        return SimpleNamespace(returncode=0)
    env['subprocess']=SimpleNamespace(run=run)
    code=cell_containing('if not RUN_INFERENCE:')
    exec(code,env);exec(code,env)
    assert len(calls)==1 and 'tests.support.optimind_experiment' in calls[0]
    assert not env['RUN_INFERENCE'] and not (tmp_path/'.notebook_inference.lock').exists()
