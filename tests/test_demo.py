"""Real restricted Gurobi + mocked model inference; no generated Python execution."""
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
import yaml
from src import demo
from src.config import load
from src.portfolio import generate
from src.problem_contract import from_config, canonical_bytes
from src.ir_reference import direct_to_ir
from src.inference_config import load_ai
from src.inference_backends import MockBackend
from src.optimind import OptiMindAdapter
from src.persistence import hash_file
from src.runtime_verification import verify_artifacts

ROOT=Path(__file__).resolve().parents[1]


def config(tmp_path,mode='AI_ASSISTED',fallback=False,benchmark=None):
    p=tmp_path/'demo.yaml'
    p.write_text(yaml.safe_dump(dict(version=1,benchmark=str(benchmark or ROOT/'tests/fixtures/config/scenarios/single.yaml'),
        mode=mode,ai_config=str(ROOT/'tests/fixtures/config/demo/optimind.yaml'),allow_reference_fallback=fallback)))
    return p


@pytest.fixture(scope='module')
def valid_ir(tmp_path_factory):
    c,_=load(ROOT/'tests/fixtures/config/scenarios/single.yaml')
    return direct_to_ir(from_config(c,generate(c)),tmp_path_factory.mktemp('demo-ir')).model_dump()


def adapter(payload):
    settings=load_ai(ROOT/'tests/fixtures/config/demo/optimind.yaml')
    a=OptiMindAdapter(settings,MockBackend(payload))
    a.prepare=lambda prompt,folder,*args: (dict(messages=prompt,checkpoint=dict(model_id=settings.model.model_id,revision=settings.model.revision)),{})
    return a


def test_valid_ai_ir_real_solver_and_explanation(tmp_path,valid_ir):
    p=config(tmp_path);before=hash_file(p)
    folder,r=demo.run_demo(p,tmp_path/'out',adapter=adapter(json.dumps(valid_ir)))
    assert r.status=='RECOMMENDED' and r.source=='OPTIMIND_IR' and not r.fallback_used
    assert not r.genuine_inference  # Explicit mock provenance, never a live model claim.
    assert r.independent_validation['valid'] and r.solver['optimality_proven']
    assert set(r.placement['environments'])=={'PROD','DEV'}
    assert r.explanation['dr']['site']==r.explanation['production']
    assert r.explanation['total_tco']==r.metrics['tco']
    assert len(r.explanation['latency_edges'])==2
    for site in r.explanation['capacity'].values():
        assert all(row['peak_headroom']>=0 for row in site.values())
    assert any(reasons for sites in r.explanation['eligibility'].values() for reasons in sites.values())
    assert r.explanation['alternatives']
    assert hash_file(p)==before
    demo.Recommendation.model_validate_json((folder/'recommendation.json').read_text())
    verify_artifacts(folder)
    assert (folder/'ai/generated_ir.json').is_file()


@pytest.mark.parametrize('kind',['invalid_json','missing_row','missing_manifest','wrong_objective'])
def test_invalid_ai_no_silent_fallback(tmp_path,valid_ir,kind,monkeypatch):
    ir=deepcopy(valid_ir)
    if kind=='missing_row':ir['constraints'].pop(0)
    if kind=='missing_manifest':ir['manifest'].pop(0)
    if kind=='wrong_objective':ir['objective_sense']='MAX'
    raw='not JSON' if kind=='invalid_json' else json.dumps(ir)
    monkeypatch.setattr(demo,'verify_formulation',lambda *a,**kw:pytest.fail('Uncertified IR must not reach submitted-model solve'))
    folder,r=demo.run_demo(config(tmp_path),tmp_path/'out',adapter=adapter(raw))
    assert r.status=='FAILED' and r.placement is None and not r.fallback_used
    assert not (folder/'reference').exists()
    assert (folder/'ai/raw_response.txt').read_text()==raw
    verify_artifacts(folder)


def test_explicit_fallback_label_and_failure_retained(tmp_path):
    folder,r=demo.run_demo(config(tmp_path,fallback=True),tmp_path/'out',adapter=adapter('invalid'))
    assert r.status=='RECOMMENDED' and r.source=='REFERENCE_FALLBACK' and r.fallback_used
    assert r.fallback_reason and r.errors and (folder/'ai/raw_response.txt').read_text()=='invalid'
    verify_artifacts(folder)


def test_reference_mode_never_invokes_model_and_preserves_previous_run(tmp_path,monkeypatch):
    monkeypatch.setattr(demo,'ai_solution',lambda *a:pytest.fail('No model in reference mode'))
    cfg=config(tmp_path,mode='REFERENCE_FALLBACK')
    first,r=demo.run_demo(cfg,tmp_path/'out');before={str(p.relative_to(first)):hash_file(p) for p in first.rglob('*') if p.is_file()}
    second,r2=demo.run_demo(cfg,tmp_path/'out')
    assert first!=second and r.source==r2.source=='REFERENCE_FALLBACK'
    assert before=={str(p.relative_to(first)):hash_file(p) for p in first.rglob('*') if p.is_file()}


def test_infeasible_inputs_no_invented_placement(tmp_path):
    original=yaml.safe_load((ROOT/'tests/fixtures/config/scenarios/single.yaml').read_text())
    original['paths']={k:str(ROOT/v) for k,v in original['paths'].items()}
    cap=yaml.safe_load(Path(original['paths']['capacity']).read_text())
    cap['default_residual_per_site']['cpu_vcpu']=0
    cp=tmp_path/'capacity.yaml';cp.write_text(yaml.safe_dump(cap));original['paths']['capacity']=str(cp)
    benchmark=tmp_path/'experiment.yaml';benchmark.write_text(yaml.safe_dump(original))
    folder,r=demo.run_demo(config(tmp_path,mode='REFERENCE_FALLBACK',benchmark=benchmark),tmp_path/'out')
    assert r.status=='INFEASIBLE' and r.placement is None and r.metrics is None
    assert r.explanation['deployable_alternatives_count']==0


def test_solver_exception_is_persisted(tmp_path,monkeypatch):
    def fail(*a):raise RuntimeError('solver unavailable')
    monkeypatch.setattr(demo,'reference_run',fail)
    folder,r=demo.run_demo(config(tmp_path,mode='REFERENCE_FALLBACK'),tmp_path/'out')
    assert r.status=='FAILED' and r.placement is None and 'solver unavailable' in r.errors[-1]['message']
    verify_artifacts(folder)


def test_independent_audit_failure_blocks_recommendation(tmp_path,valid_ir,monkeypatch):
    # Use real generation/coverage/solver evaluation, then fail the final independent audit.
    real=demo.validate
    def reject(*args,**kwargs):
        return dict(valid=False,status='REJECTED',reasons=['TEST_AUDIT_FAILURE'])
    monkeypatch.setattr(demo,'validate',reject)
    folder,r=demo.run_demo(config(tmp_path),tmp_path/'out',adapter=adapter(json.dumps(valid_ir)))
    assert r.status=='REJECTED' and r.placement is None
    assert 'TEST_AUDIT_FAILURE' in r.independent_validation['reasons']


def test_single_application_scope_enforced(tmp_path):
    folder,r=demo.run_demo(config(tmp_path,mode='REFERENCE_FALLBACK',benchmark=ROOT/'tests/fixtures/config/scenarios/medium.yaml'),tmp_path/'out')
    assert r.status=='FAILED' and 'ONE_NEW_APPLICATION' in r.errors[-1]['message']


def test_demo_notebook_defaults_safe_and_compiles():
    notebook=json.loads((ROOT/'tests/fixtures/notebooks/run_demo.ipynb').read_text())
    source=[]
    for cell in notebook['cells']:
        if cell['cell_type']=='code':
            text=''.join(cell['source']);compile(text,'demo notebook','exec');source.append(text)
    text='\n'.join(source)
    assert 'USE_AI = False' in text and 'RUN_DEMO = False' in text
    assert 'ALLOW_REFERENCE_FALLBACK = False' in text
    assert 'src.demo' in text and 'src.text_environment' in text


@pytest.mark.parametrize('scenario',['reference_pass','failed_tests','ai_missing_environment','ai_pass'])
def test_student_verification_cell_gates(tmp_path,scenario):
    notebook=json.loads((ROOT/'tests/fixtures/notebooks/run_demo.ipynb').read_text())
    source=next(''.join(c['source']) for c in notebook['cells'] if c['cell_type']=='code' and '# Read persisted evidence' in ''.join(c['source']))
    (tmp_path/'tests').mkdir();(tmp_path/'tests/suite_manifest.json').write_text(json.dumps({'nodeids':['one']}))
    evidence=tmp_path/'evidence';evidence.mkdir()
    (evidence/'runtime.json').write_text(json.dumps(dict(colab_verification='VERIFIED',ready_for_inference=True,readiness_reasons=[],
        tests=dict(collected=1,passed=0 if scenario=='failed_tests' else 1,failed=1 if scenario=='failed_tests' else 0,skipped=0))))
    if scenario=='ai_pass':
        (tmp_path/'text_environment.json').write_text(json.dumps(dict(passed=True,imports_passed=True,cuda_available=True,reasons=[])))
        (tmp_path/'tests/fixtures/config/demo').mkdir(parents=True)
        (tmp_path/'tests/fixtures/config/demo/ai_single.yaml').write_text((ROOT/'tests/fixtures/config/demo/ai_single.yaml').read_text())
        (tmp_path/'tests/fixtures/config/demo/optimind.yaml').write_text((ROOT/'tests/fixtures/config/demo/optimind.yaml').read_text())
    env=dict(json=json,RUNTIME_PROJECT=tmp_path,RUNTIME_EVIDENCE=evidence,RESULTS=tmp_path,USE_AI=scenario.startswith('ai_'),ALLOW_REFERENCE_FALLBACK=False)
    if scenario in ('failed_tests','ai_missing_environment'):
        with pytest.raises(AssertionError):exec(source,env)
    else:exec(source,env)
