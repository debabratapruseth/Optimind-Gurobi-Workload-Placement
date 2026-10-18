"""Public application-card workflow: real optimization, explicitly mocked AI only."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
import yaml
from src import pipeline
from src.config import load
from src.demo_spec import messages
from src.problem_contract import digest
from src.inference_config import load_ai
from src.inference_backends import MockBackend
from src.optimind import OptiMindAdapter
from src.verification import enumerate_independently
from src.runtime_verification import verify_artifacts

ROOT = Path(__file__).resolve().parents[1]


def scenario(tmp_path, change=None):
    data = yaml.safe_load((ROOT/'config/scenario.yaml').read_text())
    for key, value in data['paths'].items():
        content = yaml.safe_load((ROOT/value).read_text())
        if change:
            change(key, content)
        path = tmp_path/f'{key}.yaml'
        path.write_text(yaml.safe_dump(content, sort_keys=False))
        data['paths'][key] = str(path)
    if change:
        change('experiment', data)
    path = tmp_path/'scenario.yaml'
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def mock_ai(config, folder, payload=None):
    contract, sources = pipeline.load_problem(config)
    if payload is None:
        payload = json.dumps(dict(spec_version='1.0', problem_hash=digest(contract),
            application_id=contract.applications[0].id, formulation='DIRECT_ASSIGNMENT',
            objective_encoding='INLINE', environment_order=contract.applications[0].environments))
    settings = load_ai(ROOT/'config/optimind.yaml')
    adapter = OptiMindAdapter(settings, MockBackend(payload))
    adapter.prepare = lambda prompt, *args: (dict(messages=prompt, checkpoint=dict(model_id=settings.model.model_id, revision=settings.model.revision)), {})
    folder.mkdir()
    (folder/'runtime.json').write_text(json.dumps(dict(version=3, input_hashes={k:v['sha256'] for k,v in sources.items()})))
    return adapter


def test_bank_reference_matches_independent_oracle(tmp_path, monkeypatch):
    monkeypatch.setattr(OptiMindAdapter, 'generate', lambda *a: pytest.fail('Reference invoked AI'))
    path = ROOT/'config/scenario.yaml'
    contract, _ = pipeline.load_problem(path)
    assert contract.applications[0].id == 'BANK-PAY-001'
    assert len(contract.fixed_portfolio) == 2
    folder, result = pipeline.run(path, tmp_path)
    assert result.status == 'RECOMMENDED' and result.source == 'REFERENCE_FALLBACK'
    assert not result.genuine_inference
    assert set(result.placement['environments']) == {'PROD','DEV','SIT','UAT'}
    assert set(result.placement['environments'].values()) == {'AWS_HK'}
    assert result.placement['dr_site_id'] == 'AWS_HK'
    assert result.metrics['tco'] == 102240 and result.metrics['latency'] == 5
    assert result.solver['status'] == 'OPTIMAL' and result.solver['mip_gap'] == 0
    assert result.solver['model_counts']['variables'] == 21
    assert result.solver['model_counts']['linear_constraints'] == 111
    assert result.independent_validation['status'] == 'DEPLOYABLE'
    c,_=load(path)
    oracle=enumerate_independently(c,c['applications']['applications'],c['existing_portfolio']['applications'])
    assert result.solver['incumbent'] == pytest.approx(oracle['objective_min'])
    assert json.loads((folder/'problem.json').read_text())['applications'][0]['id'] == 'BANK-PAY-001'
    verify_artifacts(folder)


def test_replacement_card_id_and_demand(tmp_path):
    def change(key, data):
        if key == 'applications':
            data['applications'][0]['id']='CUSTOM-CARD'
            data['applications'][0]['demand']['cpu_vcpu']=40
        if key == 'experiment':data['selected_application_ids']=['CUSTOM-CARD']
    config=scenario(tmp_path,change)
    folder,result=pipeline.run(config,tmp_path/'out')
    assert result.status=='RECOMMENDED' and result.placement['application_id']=='CUSTOM-CARD'
    assert result.independent_validation['reserved_capacity']['AWS_HK']['cpu_vcpu']==200


@pytest.mark.parametrize('failure',['capacity','policy','recovery','latency','budget'])
def test_infeasible_requirements_never_relaxed(tmp_path,failure):
    def change(key,data):
        if failure=='capacity' and key=='capacity':data['default_residual_per_site']['cpu_vcpu']=1
        if failure=='policy' and key=='regulatory':data['policies']=[]
        if failure=='recovery' and key=='sites':
            for site in data['sites']:site['recovery']['verified']=False
        if failure=='latency' and key=='dependencies':data['latency_matrix_ms']={}
        if failure=='budget' and key=='cost':data['budget']={'enabled':True,'max_total_tco_usd':1}
    config=scenario(tmp_path,change)
    _,result=pipeline.run(config,tmp_path/'out')
    assert result.status=='INFEASIBLE' and result.placement is None
    assert not result.genuine_inference


@pytest.mark.parametrize('failure',['unknown_field','dependency','selected_id','multiple','generated_portfolio'])
def test_invalid_or_unsupported_inputs_rejected(tmp_path,failure):
    def change(key,data):
        if key=='applications':
            a=data['applications'][0]
            if failure=='unknown_field':a['arbitrary_constraint']=True
            if failure=='dependency':a['dependencies'][0]['target']='UNKNOWN'
            if failure=='multiple':
                b=deepcopy(a);b['id']='SECOND';data['applications'].append(b)
        if key=='experiment':
            if failure=='selected_id':data['selected_application_ids']=['MISSING']
            if failure=='multiple':data.update(scope='MULTIPLE_NEW_APPLICATIONS',selected_application_ids=['BANK-PAY-001','SECOND'])
            if failure=='generated_portfolio':data['portfolio_size']=3
        if key=='dataset_generator' and failure=='generated_portfolio':data['portfolio_sizes']=[3]
    with pytest.raises(ValueError):pipeline.load_problem(scenario(tmp_path,change))


def test_compact_ai_bank_card_real_compilation_mocked_generation(tmp_path):
    config=ROOT/'config/scenario.yaml';runtime=tmp_path/'runtime'
    adapter=mock_ai(config,runtime)
    contract,_=pipeline.load_problem(config)
    assert json.loads(messages(contract)[1]['content'])['problem']['applications'][0]['id']=='BANK-PAY-001'
    folder,result=pipeline.run(config,tmp_path/'out',mode='AI_ASSISTED',runtime_evidence=runtime,adapter=adapter)
    assert result.status=='RECOMMENDED' and result.source=='OPTIMIND_SPEC_TRUSTED_MILP'
    assert not result.genuine_inference and not result.fallback_used
    assert result.independent_validation['valid'] and result.solver['optimality_proven']
    assert result.metrics['tco']==102240
    assert json.loads((folder/'ai/spec_validation.json').read_text())['equivalence']['complete']


def test_ai_failure_never_falls_back(tmp_path):
    config=ROOT/'config/scenario.yaml';runtime=tmp_path/'runtime'
    adapter=mock_ai(config,runtime,'{"invalid":true}')
    _,result=pipeline.run(config,tmp_path/'out',mode='AI_ASSISTED',runtime_evidence=runtime,adapter=adapter)
    assert result.status=='FAILED' and not result.fallback_used and result.placement is None


def test_ai_requires_runtime_and_matching_inputs(tmp_path):
    with pytest.raises(ValueError,match='VERIFIED_COLAB'):
        pipeline.run(mode='AI_ASSISTED')
    runtime=tmp_path/'runtime';runtime.mkdir();(runtime/'runtime.json').write_text('{"version":3,"input_hashes":{}}')
    with pytest.raises(ValueError,match='MATCHING_SCENARIO'):
        pipeline.run(mode='AI_ASSISTED',runtime_evidence=runtime)


def test_public_notebook_is_syntactically_valid_and_safe_by_default():
    notebook=json.loads((ROOT/'notebooks/run_pipeline.ipynb').read_text())
    texts=[''.join(c['source']) for c in notebook['cells'] if c['cell_type']=='code']
    for source in texts:compile(source,'pipeline notebook','exec')
    text='\n'.join(texts)
    assert 'USE_AI = False' in text and 'RUN_PIPELINE = False' in text
    assert 'src.pipeline' in text and 'src.text_environment' in text
    assert 'allow_reference_fallback' not in text
    assert all(not c.get('outputs') for c in notebook['cells'])


def test_public_notebook_launch_consumes_permission_and_prevents_repeat(tmp_path):
    import os,sys,uuid
    from types import SimpleNamespace
    notebook=json.loads((ROOT/'notebooks/run_pipeline.ipynb').read_text())
    source=next(''.join(c['source']) for c in notebook['cells'] if c['cell_type']=='code' and 'if not RUN_PIPELINE:' in ''.join(c['source']))
    proc=tmp_path/'proc';proc.mkdir();calls=[]
    def run(command):
        assert (tmp_path/'.placement-launch.lock').exists()
        calls.append(command);return SimpleNamespace(returncode=0)
    env=dict(RUN_PIPELINE=True,USE_AI=True,Path=lambda p:proc if p=='/proc' else Path(p),
             RUNTIME_PROJECT=tmp_path,SCENARIO=tmp_path/'scenario.yaml',RESULTS=tmp_path/'results',
             DRIVE_PROJECT=tmp_path/'drive',RUNTIME_EVIDENCE=tmp_path/'runtime',CACHE=tmp_path/'cache',
             os=os,sys=sys,uuid=uuid,subprocess=SimpleNamespace(run=run),sync_verified=lambda *a:None)
    exec(source,env);exec(source,env)
    assert len(calls)==1 and 'src.pipeline' in calls[0] and 'AI_ASSISTED' in calls[0]
    assert not env['RUN_PIPELINE'] and not (tmp_path/'.placement-launch.lock').exists()


def test_public_notebook_rejects_overlapping_worker(tmp_path):
    notebook=json.loads((ROOT/'notebooks/run_pipeline.ipynb').read_text())
    source=next(''.join(c['source']) for c in notebook['cells'] if c['cell_type']=='code' and 'if not RUN_PIPELINE:' in ''.join(c['source']))
    worker=tmp_path/'123';worker.mkdir();(worker/'cmdline').write_bytes(b'python\0-m\0src.inference_worker\0')
    env=dict(RUN_PIPELINE=True,Path=lambda p:tmp_path)
    with pytest.raises(AssertionError,match='Existing inference'):exec(source,env)
    assert env['RUN_PIPELINE'] is False
