from copy import deepcopy
from itertools import product
from pathlib import Path
import json
import pytest
import yaml
from src.config import load, cross_validate, UniqueLoader
from src.portfolio import generate
from src.feasibility import enumerate_candidates, site_reasons, loads
from src.validation import validate
from src.metrics import measure, normalized_scores
from src.solver import solve, guard, LicenseSizeExceeded
from src.main import run
from src.adapters import OptiMindAdapter
from src import schema

ROOT=Path(__file__).resolve().parents[1]

def aws(config, sid='AWS_HK'):
    return next(s for s in config['sites']['sites'] if s['id']==sid)

def placement(app,prod='AWS_HK'):
    return dict(application_id=app['id'],environments={e:prod if e=='PROD' else 'AWS_HK' for e in app['environments']},dr_site_id=prod,failure_domain_contract='INDEPENDENT_LOCAL_DOMAINS')

def test_policy_denial(config,app,portfolio):
    assert 'POLICY_DENIAL' in site_reasons(config,app,aws(config,'AZURE_HK'),'PROD',portfolio)
    p=placement(app,'AZURE_HK')
    assert not validate(config,app,portfolio,p)['valid']

def test_missing_policy(config,app,portfolio):
    config['regulatory']['policies']=[]
    assert not enumerate_candidates(config,app,portfolio)[0]
    assert 'MISSING_POLICY' in site_reasons(config,app,aws(config),'PROD',portfolio)
    assert not validate(config,app,portfolio,placement(app))['valid']

def test_nonprod_hk(config,app,portfolio):
    p=placement(app); p['environments']['DEV']='AWS_SG'
    assert not validate(config,app,portfolio,p)['valid']
    assert 'NONPROD_REQUIRES_HK' in site_reasons(config,app,aws(config,'AWS_SG'),'DEV',portfolio)

def test_missing_service(config,app,portfolio):
    config['sites']['service_category_overrides']['AWS_HK']=['COMPUTE']
    assert 'MISSING_SERVICE' in site_reasons(config,app,aws(config),'PROD',portfolio)
    assert not enumerate_candidates(config,app,portfolio)[0]
    assert not validate(config,app,portfolio,placement(app))['valid']

@pytest.mark.parametrize('resource',['cpu_vcpu','ram_gb','storage_tb','gpu_count'])
def test_capacity_shortage(config,app,portfolio,resource):
    if resource=='gpu_count':
        app['demand']['gpu_count']=1
    config['capacity']['default_residual_per_site'][resource]=0
    assert not enumerate_candidates(config,app,portfolio)[0]
    assert not validate(config,app,portfolio,placement(app))['valid']

def test_aggregate_capacity_not_per_environment(config,app,portfolio):
    config['capacity']['default_residual_per_site']['cpu_vcpu']=100
    # PROD+DR at HK plus 3 NONPROD need 160; SG placement leaves 96 at HK.
    candidates,_=enumerate_candidates(config,app,portfolio)
    assert len(candidates)==1 and candidates[0]['environments']['PROD']=='AWS_SG'
    assert not validate(config,app,portfolio,placement(app))['valid']

def test_same_region_dr(config,app,portfolio):
    p=placement(app); p['dr_site_id']='AWS_SG'
    assert 'DR_SAME_SITE_PROVIDER_REGION_REQUIRED' in validate(config,app,portfolio,p)['reasons']

@pytest.mark.parametrize('field,value',[('ha_verified',False),('independent_failure_domains',1)])
def test_failure_domain_independence(config,app,portfolio,field,value):
    aws(config)[field]=value
    assert 'HA_INDEPENDENCE_UNVERIFIED' in site_reasons(config,app,aws(config),'PROD',portfolio)
    assert not validate(config,app,portfolio,placement(app))['valid']

@pytest.mark.parametrize('value',[None,31.0])
def test_latency(config,app,portfolio,value):
    row=config['dependencies']['latency_matrix_ms']['AWS_HK']
    if value is None:
        del row['AWS_HK']
    else:
        row['AWS_HK']=value
    assert not enumerate_candidates(config,app,portfolio)[0]
    assert not validate(config,app,portfolio,placement(app))['valid']

def test_processing_restriction(config,app,portfolio):
    aws(config)['processing_country']='UK'
    assert not validate(config,app,portfolio,placement(app))['valid']

def test_pending_approval(config,app,portfolio,tmp_path):
    config['regulatory']['materiality']['MATERIAL']['approval_status']='PENDING'
    candidates,_=enumerate_candidates(config,app,portfolio)
    assert all(p['approval_pending'] for p in candidates)
    assert validate(config,app,portfolio,candidates[0])['status']=='CONDITIONAL'
    solution=solve(config,app,candidates,[measure(config,app,portfolio,p) for p in candidates],tmp_path)
    assert solution['status']=='OPTIMAL'
    assert validate(config,app,portfolio,candidates[solution['selected_index']])['status']=='CONDITIONAL'

@pytest.mark.parametrize('status',['DENIED',None])
def test_approval_fail_closed(config,app,portfolio,status):
    if status is None:
        config['regulatory']['materiality']={}
    else:
        config['regulatory']['materiality']['MATERIAL']['approval_status']=status
    assert not enumerate_candidates(config,app,portfolio)[0]
    assert not validate(config,app,portfolio,placement(app))['valid']

def test_sample_missing_recovery_is_infeasible(tmp_path):
    folder,result=run(ROOT/'tests/fixtures/config/experiments/experiment.yaml',tmp_path)
    assert result['status']=='INFEASIBLE'
    assert json.loads((folder/'solver.json').read_text())['status']=='INFEASIBLE'
    assert 'MISSING_RECOVERY_EVIDENCE' in (folder/'screening.json').read_text()
    for name in ['metadata.json','validation.json','placement.json','summary.csv','solver.log','generated_formulation.py','COMPLETE.json','reference_model.lp','infeasible.ilp']:
        assert (folder/name).is_file()

def test_cost_no_double_count(config,app,portfolio):
    # 5 full CPU reservations at HK, one occupied-site overhead, one license/ops.
    metric=measure(config,app,portfolio,placement(app))
    assert metric['tco']==36*(160*15+190+100+150)==102240
    assert sum(metric['tco_breakdown'].values())==metric['tco']
    assert metric['tco_breakdown']['dr']==32*15*36
    assert validate(config,app,portfolio,placement(app),metric)['valid']
    metric['tco']+=1
    assert not validate(config,app,portfolio,placement(app),metric)['valid']

def test_seed_reproducibility(config):
    first=generate(config)
    assert len(first)==25 and first==generate(config)
    assert first[:2]==config['existing_portfolio']['applications']
    config['experiment']['dataset']='VALIDATION'
    assert first!=generate(config)

@pytest.mark.parametrize('kind',['variables','constraints'])
def test_real_model_size_guard(config,kind):
    import gurobipy as gp
    with gp.Env(params={'OutputFlag':0}) as env, gp.Model(env=env) as model:
        if kind=='variables':
            model.addVars(1801,vtype=gp.GRB.BINARY)
        else:
            x=model.addVar()
            model.addConstrs((x<=i+1 for i in range(1801)))
        with pytest.raises(LicenseSizeExceeded):
            guard(model,config['solver'])
        assert model.Status==gp.GRB.LOADED

def test_guard_blocks_optimizer_integration(config,app,portfolio,tmp_path,monkeypatch):
    import gurobipy as gp
    config['solver']['safety_limits']['max_linear_constraints']=80
    candidates,_=enumerate_candidates(config,app,portfolio)
    def forbidden(*args,**kwargs):
        pytest.fail('optimize must not be called on oversized model')
    monkeypatch.setattr(gp.Model,'optimize',forbidden)
    with pytest.raises(LicenseSizeExceeded):
        solve(config,app,candidates,[measure(config,app,portfolio,p) for p in candidates],tmp_path)

def test_no_quadratic(config):
    import gurobipy as gp
    with gp.Env(params={'OutputFlag':0}) as env, gp.Model(env=env) as m:
        x=m.addVar(); m.setObjective(x*x)
        with pytest.raises(ValueError,match='ONLY_LINEAR'):
            guard(m,config['solver'])

def test_independent_exhaustive_oracle(config,app,portfolio,tmp_path):
    # Deliberately bypass all screening and enumerate 10^4 assignments through
    # the independent validator. Compare the complete feasible set and objective.
    ids=[s['id'] for s in config['sites']['sites']]
    feasible=[]
    for values in product(ids,repeat=len(app['environments'])):
        p=placement(app); p['environments']=dict(zip(app['environments'],values)); p['dr_site_id']=p['environments']['PROD']
        if validate(config,app,portfolio,p)['status']=='DEPLOYABLE':
            feasible.append(p)
    candidates,_=enumerate_candidates(config,app,portfolio)
    key=lambda p:tuple(sorted(p['environments'].items()))
    assert {key(p) for p in feasible}=={key(p) for p in candidates}
    metrics=[measure(config,app,portfolio,p) for p in candidates]
    scores,_=normalized_scores(config,metrics)
    result=solve(config,app,candidates,metrics,tmp_path)
    assert result['status']=='OPTIMAL'
    assert result['model_counts']==dict(variables=2,linear_constraints=81,quadratic_constraints=0,quadratic_objective_terms=0,general_constraints=0,sos_constraints=0)
    assert result['incumbent']==pytest.approx(min(scores))
    assert validate(config,app,portfolio,candidates[result['selected_index']],metrics[result['selected_index']])['valid']

def test_budget_infeasible(config,app,portfolio,tmp_path):
    config['cost']['budget']=dict(enabled=True,max_total_tco_usd=1)
    candidates,_=enumerate_candidates(config,app,portfolio)
    result=solve(config,app,candidates,[measure(config,app,portfolio,p) for p in candidates],tmp_path)
    assert result['status']=='INFEASIBLE'
    assert not validate(config,app,portfolio,candidates[0])['valid']

def test_reduced_dr_peak_recovery(config,app,portfolio):
    app['dr'].update(mode='REDUCED',cpu_ratio=.25,ram_ratio=.25,gpu_ratio=.25,storage_ratio=.25)
    p=placement(app)
    assert loads(config,app,p)['AWS_HK']['cpu_vcpu']==136
    assert loads(config,app,p,True)['AWS_HK']['cpu_vcpu']==160
    config['capacity']['default_residual_per_site']['cpu_vcpu']=150
    assert not validate(config,app,portfolio,p)['valid']
    aws(config)['recovery']['scaling_verified']=False
    assert 'DR_SCALING_UNVERIFIED' in site_reasons(config,app,aws(config),'PROD',portfolio)

def test_variable_shared_pool_peak(config,app,portfolio):
    app['demand_mode']='VARIABLE'; app['peak_demand']={k:v*2 for k,v in app['demand'].items()}
    config['capacity'].update(allocation_mode='SHARED_POOL',reservation_mode='TYPICAL_WITH_SCALING')
    config['capacity']['shared_pool']['oversubscription']['cpu_vcpu']=10
    config['capacity']['default_residual_per_site']['cpu_vcpu']=200
    p=placement(app)
    assert loads(config,app,p)['AWS_HK']['cpu_vcpu']==160
    assert loads(config,app,p,True)['AWS_HK']['cpu_vcpu']==320
    assert not validate(config,app,portfolio,p)['valid']
    candidates,_=enumerate_candidates(config,app,portfolio)
    assert len(candidates)==1 and candidates[0]['environments']['PROD']=='AWS_SG'

def test_transitive_deduplicated_failure(config,app,portfolio):
    portfolio[1]['criticality']='CRITICAL'
    portfolio[1]['dependencies']=[dict(target='SHARED-ID-001',max_p95_latency_ms=30)]
    app['dependencies'].append(dict(target='LEGACY-RISK-001',max_p95_latency_ms=30))
    metric=measure(config,app,portfolio,placement(app))
    shared=next(s for s in metric['failure_scenarios'] if s['type']=='SHARED_SERVICE')
    assert shared['critical_count']==3
    assert shared['infrastructure_exposed_critical']==[]
    assert set(shared['residual_business_disruption_critical'])=={app['id'],'SHARED-ID-001','LEGACY-RISK-001'}
    assert validate(config,app,portfolio,placement(app),metric)['valid']

def test_concentration_count_once(config,app,portfolio):
    metric=measure(config,app,portfolio,placement(app))
    assert metric['critical_application_count']==sum(p['criticality']=='CRITICAL' for p in portfolio)+1
    assert sum(metric['concentration_shares']['provider'].values())==pytest.approx(1)

@pytest.mark.parametrize('strategy',['HIERARCHICAL','PARETO'])
def test_objective_modes(config,app,portfolio,tmp_path,strategy):
    config['objectives']['strategy']=strategy
    config['experiment']['optimization_strategy']=strategy
    config['objectives']['pareto']['enabled']=strategy=='PARETO'
    candidates,_=enumerate_candidates(config,app,portfolio)
    result=solve(config,app,candidates,[measure(config,app,portfolio,p) for p in candidates],tmp_path)
    assert result['status']=='OPTIMAL'
    if strategy=='PARETO':
        assert result['pareto_indices']

@pytest.mark.parametrize('mutation',[
    lambda c:c['solver']['safety_limits'].update(max_variables=1801),
    lambda c:c['capacity']['default_residual_per_site'].update(cpu_vcpu=-1),
    lambda c:c['applications']['applications'][0].update(criticality='HIGH'),
    lambda c:c['sites']['sites'][0].update(unknown_bank_rule=True),
])
def test_schema_errors(config,mutation):
    mutation(config)
    with pytest.raises(ValueError):
        for key,model in [('solver',schema.Solver),('capacity',schema.Capacity),('applications',schema.Applications),('sites',schema.Sites)]:
            model.model_validate(config[key])

def test_duplicate_yaml():
    with pytest.raises(ValueError,match='duplicate YAML'):
        yaml.load('version: 1\nversion: 2',Loader=UniqueLoader)

def test_reference_validation(config):
    config['applications']['applications'][0]['dependencies'][0]['target']='UNKNOWN'
    with pytest.raises(ValueError):
        cross_validate(config)

def test_no_ai_execution():
    with pytest.raises(NotImplementedError,match='NOT_IMPLEMENTED'):
        OptiMindAdapter().formulate({})

def test_resume_and_tamper(tmp_path):
    path=ROOT/'tests/fixtures/config/experiments/experiment.yaml'
    folder,result=run(path,tmp_path)
    again,other=run(path,tmp_path,folder.name)
    assert again==folder and other==result
    (folder/'placement.json').write_text('{}')
    with pytest.raises(ValueError,match='integrity'):
        run(path,tmp_path,folder.name)

def test_invalid_input_persisted(tmp_path):
    bad=tmp_path/'bad.yaml'; bad.write_text('version: invalid\n')
    folder,result=run(bad,tmp_path/'results')
    assert result['status']=='REJECTED'
    assert (folder/'error.log').exists() and (folder/'validation.json').exists()

def test_successful_pipeline_and_resume(tmp_path):
    path=ROOT/'tests/fixtures/config/experiments/experiment_recovery_demo.yaml'
    folder,result=run(path,tmp_path)
    assert result['status']=='DEPLOYABLE'
    assert result['solver_status']=='OPTIMAL'
    validation=json.loads((folder/'validation.json').read_text())
    assert validation['valid'] and validation['status']=='DEPLOYABLE'
    again,other=run(path,tmp_path,folder.name)
    assert again==folder and other==result
    # Interrupted run restarts into a new folder with unchanged inputs, preserving originals.
    (folder/'COMPLETE.json').unlink()
    restarted,repeated=run(path,tmp_path,folder.name)
    assert restarted!=folder and repeated['placement']==result['placement']
    assert json.loads((restarted/'metadata.json').read_text())['resumed_from']==folder.name

def test_notebook_python_cells_compile():
    notebook=json.loads((ROOT/'notebooks/run_pipeline.ipynb').read_text())
    for i,cell in enumerate(notebook['cells']):
        if cell['cell_type']=='code':
            compile(''.join(cell['source']),f'cell-{i}','exec')

def test_time_limit_is_not_infeasible_or_optimal(config,app,portfolio,tmp_path):
    config['solver']['time_limit_seconds']=1e-12
    candidates,_=enumerate_candidates(config,app,portfolio)
    result=solve(config,app,candidates,[measure(config,app,portfolio,p) for p in candidates],tmp_path)
    assert result['status']=='TIME_LIMIT'
    assert not result['optimality_proven']
    assert result['selected_index'] is None

def test_malformed_later_input_snapshot_survives(tmp_path):
    experiment=yaml.safe_load((ROOT/'tests/fixtures/config/experiments/experiment.yaml').read_text())
    for k,v in experiment['paths'].items():
        experiment['paths'][k]=str(ROOT/v)
    bad=tmp_path/'bad_sites.yaml'; bad.write_text('version: 1\nunexpected: true\n')
    experiment['paths']['sites']=str(bad)
    path=tmp_path/'experiment.yaml'; path.write_text(yaml.safe_dump(experiment))
    folder,result=run(path,tmp_path/'results')
    assert result['status']=='REJECTED'
    assert (folder/'input_snapshot'/'sites.yaml').read_bytes()==bad.read_bytes()

def test_pending_without_remediation_stays_strict(tmp_path):
    experiment=yaml.safe_load((ROOT/'tests/fixtures/config/experiments/experiment_recovery_demo.yaml').read_text())
    for k,v in experiment['paths'].items():
        experiment['paths'][k]=str(ROOT/v)
    regulatory=yaml.safe_load(Path(experiment['paths']['regulatory']).read_text())
    regulatory['materiality']['MATERIAL']['approval_status']='PENDING'
    objectives=yaml.safe_load(Path(experiment['paths']['objectives']).read_text())
    objectives['infeasibility']['remediation_analysis']=False
    for key,value in [('regulatory',regulatory),('objectives',objectives)]:
        path=tmp_path/f'{key}.yaml'; path.write_text(yaml.safe_dump(value))
        experiment['paths'][key]=str(path)
    path=tmp_path/'experiment.yaml'; path.write_text(yaml.safe_dump(experiment))
    folder,result=run(path,tmp_path/'results')
    assert result['status']=='INFEASIBLE' and result['placement'] is None
    assert json.loads((folder/'solver.json').read_text())['stage']=='STRICT'
    assert json.loads((folder/'remediation.json').read_text())==[]
