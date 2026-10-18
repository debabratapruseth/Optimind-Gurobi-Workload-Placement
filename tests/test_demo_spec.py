"""Compact choices with real restricted solves and explicitly mocked generation."""
import json
import pytest
import yaml
from src import demo
from src.demo_spec import OptimizationSpec, parse_spec, compile_spec, messages
from src.problem_contract import from_config, digest, canonical_bytes
from src.config import load
from src.portfolio import generate
from src.runtime_verification import verify_artifacts
from src.formulation_validation import verify_formulation
from tests.test_demo import adapter, config, ROOT


@pytest.fixture
def contract():
    c, _ = load(ROOT/'tests/fixtures/config/scenarios/single.yaml')
    return from_config(c, generate(c))


def payload(contract, encoding='INLINE'):
    return dict(spec_version='1.0', problem_hash=digest(contract),
        application_id=contract.applications[0].id, formulation='DIRECT_ASSIGNMENT',
        objective_encoding=encoding, environment_order=['DEV', 'PROD'])


def demo_config(tmp_path, fallback=False):
    path = config(tmp_path, fallback=fallback)
    data = yaml.safe_load(path.read_text())
    data['formulation_interface'] = 'COMPACT_SPEC'
    path.write_text(yaml.safe_dump(data))
    return path


@pytest.mark.parametrize('encoding', ['INLINE', 'EXPLICIT_SCORE'])
def test_spec_real_solver_equivalence_and_provenance(tmp_path, contract, encoding):
    raw = json.dumps(payload(contract, encoding))
    folder, result = demo.run_demo(demo_config(tmp_path), tmp_path/'out', adapter=adapter(raw))
    assert result.status == 'RECOMMENDED', result.errors
    assert result.source == 'OPTIMIND_SPEC_TRUSTED_MILP' and not result.fallback_used
    assert not result.genuine_inference
    assert result.solver['optimality_proven'] and result.independent_validation['valid']
    assert result.metrics['tco'] == 32040 and result.metrics['latency'] == 3
    assert result.metrics['concentration'] > 0 and result.metrics['blast_radius'] > 0
    assert set(result.placement['environments']) == {'DEV','PROD'}
    assert result.explanation['capacity']['AWS_HK']['cpu_vcpu']['reserved'] == 30
    assert result.explanation['formulation']['algebra_author'] == 'TRUSTED_COMPILER'
    report = json.loads((folder/'ai/spec_validation.json').read_text())
    assert report['equivalence']['complete']
    assert not any(report['equivalence'][k] for k in ['extra_infeasible','missing_feasible','metric_mismatches','objective_mismatches'])
    ir = json.loads((folder/'ai/expanded_ir.json').read_text())
    assert any(v['id']=='demo_normalized_score' for v in ir['variables']) == (encoding=='EXPLICIT_SCORE')
    assert (folder/'ai/raw_response.txt').read_text() == raw
    assert not (folder/'ai/generated_ir.json').exists()
    verify_artifacts(folder)


@pytest.mark.parametrize('change', [
    {'problem_hash':'0'*64}, {'application_id':'unknown'}, {'environment_order':['PROD']},
    {'environment_order':['PROD','PROD']}, {'environment_order':['PROD','TEST']},
    {'formulation':'GENERATED_PYTHON'}, {'objective_encoding':'MAXIMIZE'},
    {'disable_regulation':True}, {'weights':{'tco':1}}, {'sites':['AWS_SG']},
    {'python':'import os'}, {'spec_version':'2.0'},
])
def test_inconsistent_specs_rejected_before_compilation(contract, change):
    data = payload(contract); data.update(change)
    with pytest.raises(ValueError): parse_spec(json.dumps(data),contract)


@pytest.mark.parametrize('raw', ['{} trailing', '<think>text</think>{}', '```python\npass\n```',
                                   '{"spec_version":"1.0","spec_version":"1.0"}'])
def test_strict_format_no_repair(contract, raw):
    with pytest.raises(ValueError): parse_spec(raw, contract)


def test_compact_failure_fallback_explicit(tmp_path):
    path = demo_config(tmp_path)
    first, failed = demo.run_demo(path,tmp_path/'out',adapter=adapter('invalid'))
    before=(first/'COMPLETE.json').read_bytes()
    assert failed.status=='FAILED' and failed.source=='OPTIMIND_SPEC_TRUSTED_MILP'
    assert not failed.fallback_used and not (first/'reference').exists()
    path=demo_config(tmp_path,fallback=True)
    second,result=demo.run_demo(path,tmp_path/'out',adapter=adapter('invalid'))
    assert result.source=='REFERENCE_FALLBACK' and result.fallback_used and result.errors
    assert result.status=='RECOMMENDED' and second!=first
    assert (first/'COMPLETE.json').read_bytes()==before
    verify_artifacts(first);verify_artifacts(second)


@pytest.mark.parametrize('failure', ['incomplete','objective','placement','compiler'])
def test_compact_audit_failures_block_recommendation(tmp_path,contract,monkeypatch,failure):
    real=demo.verify_formulation
    def changed(*args,**kwargs):
        report=real(*args,**kwargs)
        if failure=='incomplete':report['levels']['5_equivalence']['complete']=False
        elif failure=='objective':report['levels']['5_equivalence']['objective_mismatches']=1
        elif failure=='compiler':report['error']='test compiler failure'
        return report
    monkeypatch.setattr(demo,'verify_formulation',changed)
    if failure=='placement':
        monkeypatch.setattr(demo,'validate',lambda *a:dict(valid=False,status='REJECTED',reasons=['AUDIT_FAILED']))
    folder,r=demo.run_demo(demo_config(tmp_path),tmp_path/'out',adapter=adapter(json.dumps(payload(contract))))
    assert r.status in ('FAILED','REJECTED') and r.placement is None and not r.fallback_used


def test_compact_prompt_and_schema(contract):
    prompt=messages(contract)
    data=json.loads(prompt[1]['content'])
    assert data['problem']==contract.model_dump(mode='json')
    assert data['output_schema']==OptimizationSpec.model_json_schema()
    assert json.loads((ROOT/'schemas/optimization-spec-1.0.json').read_text())==OptimizationSpec.model_json_schema()
    assert len(json.dumps(payload(contract)))<400
    assert 'weights' not in OptimizationSpec.model_fields


def test_compact_truncation_fails_before_expansion(tmp_path,contract,monkeypatch):
    a=adapter(json.dumps(payload(contract)))
    real=a.generate
    def truncated(*args):
        r=real(*args);r['finish_reason']='length';return r
    a.generate=truncated
    folder,r=demo.run_demo(demo_config(tmp_path),tmp_path/'out',adapter=a)
    assert r.status=='FAILED' and 'GENERATION_TRUNCATED' in r.errors[-1]['message']
    assert not (folder/'ai/expanded_ir.json').exists()


@pytest.mark.parametrize('encoding',['INLINE','EXPLICIT_SCORE'])
def test_actual_corrupted_objective_detected_by_independent_oracle(tmp_path,contract,encoding):
    spec=parse_spec(json.dumps(payload(contract,encoding)),contract)
    ir=compile_spec(spec,contract,tmp_path).model_dump()
    # Pretend a compiler defect inverted the objective: no favorable incumbent can hide it.
    ir['objective_sense']='MAX'
    report=verify_formulation(contract,canonical_bytes(ir),tmp_path/'audit')
    assert report['levels']['5_equivalence']['objective_mismatches']>0
    assert 'INCORRECT_OBJECTIVE' in report['failure_classifications']


def test_compact_obeys_configured_model_size_guard(tmp_path,contract):
    contract.solver.safety_limits.max_variables=1
    spec=parse_spec(json.dumps(payload(contract)),contract)
    with pytest.raises(Exception,match='(?i)(license|limit|variable)'):
        compile_spec(spec,contract,tmp_path)


def test_environment_order_changes_only_variable_order(tmp_path,contract):
    data=payload(contract)
    a=compile_spec(parse_spec(json.dumps(data),contract),contract,tmp_path/'a')
    data['environment_order'].reverse()
    b=compile_spec(parse_spec(json.dumps(data),contract),contract,tmp_path/'b')
    assert a.variables[0].assignment.environment=='DEV'
    assert b.variables[0].assignment.environment=='PROD'
    assert {v.id:v for v in a.variables}=={v.id:v for v in b.variables}
    assert a.constraints==b.constraints and a.objectives==b.objectives and a.metrics==b.metrics


def test_explicit_score_extra_variable_is_counted(tmp_path,contract):
    base=compile_spec(parse_spec(json.dumps(payload(contract)),contract),contract,tmp_path/'base')
    contract.solver.safety_limits.max_variables=len(base.variables)
    ir=compile_spec(parse_spec(json.dumps(payload(contract,'EXPLICIT_SCORE')),contract),contract,tmp_path/'expanded')
    report=verify_formulation(contract,canonical_bytes(ir),tmp_path/'audit')
    assert report['compilation']['status']=='LICENSE_SIZE_EXCEEDED'
    assert report['compilation']['model_counts']['variables']==len(base.variables)+1


@pytest.mark.parametrize('change',['capacity','budget','recovery','residency'])
def test_trusted_policy_changes_not_overridden_by_spec(tmp_path,contract,change):
    if change=='capacity':contract.capacity.default_residual_per_site.cpu_vcpu=0.
    elif change=='budget':
        contract.cost.budget.enabled=True
        contract.cost.budget.max_total_tco_usd=1.
    elif change=='recovery':
        for site in contract.sites.sites:site.recovery.verified=False
    else:
        for policy in contract.regulatory.policies:
            policy.approved_hosting_countries=[]
    spec=parse_spec(json.dumps(payload(contract)),contract)
    ir=compile_spec(spec,contract,tmp_path/'expanded')
    report=verify_formulation(contract,canonical_bytes(ir),tmp_path/'audit')
    assert report['solver']['status']=='INFEASIBLE',report
    assert not report.get('placement')
