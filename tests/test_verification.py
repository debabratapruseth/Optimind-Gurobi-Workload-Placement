"""Phase 1.5 joint-constraint, independent oracle and robustness regressions."""
from copy import deepcopy
from pathlib import Path
import json
import math
import pytest
from src.config import load, cross_validate
from src.portfolio import generate
from src.feasibility import enumerate_candidates
from src.metrics import measure
from src.validation import validate
from src.verification import enumerate_independently, verify_run, canonical
from src.solver import solve, guard
from src.schema import Experiment

ROOT=Path(__file__).resolve().parents[1]


def benchmark(name):
    c,_=load(ROOT/f'tests/fixtures/config/scenarios/{name}.yaml')
    apps=c['applications']['applications']
    return c,apps,generate(c)


def assign(apps,sites):
    parts={a['id']:dict(application_id=a['id'],environments={e:sid for e in a['environments']},dr_site_id=sid,failure_domain_contract='INDEPENDENT_LOCAL_DOMAINS') for a,sid in zip(apps,sites)}
    return dict(applications=parts) if len(apps)>1 else next(iter(parts.values()))


@pytest.mark.parametrize('name,count,raw',[('single',9,100),('medium',4,1000),('complex',282,100000)])
def test_verified_benchmarks(name,count,raw,tmp_path):
    report=verify_run(ROOT/f'tests/fixtures/config/scenarios/{name}.yaml',tmp_path)
    assert report['verified']
    assert report['model_counts']['variables']==count
    assert report['model_counts']['linear_constraints']==81
    assert report['model_counts']['variables']<1800
    assert report['oracle']['prebudget_feasible_count']==count
    assert report['oracle']['raw_assignment_count']==raw
    assert report['solver_status']=='OPTIMAL' and report['mip_gap']==0
    assert report['incumbent']==pytest.approx(report['oracle']['objective_min'])
    assert report['witness']['status']=='DEPLOYABLE'


def test_shared_capacity_rejects_individually_valid_placements():
    c,apps,portfolio=benchmark('medium')
    p=assign(apps,['AWS_HK']*3)
    audit=validate(c,apps,portfolio,p)
    assert all(v['valid'] for v in audit['applications'].values())
    assert not audit['valid']
    assert 'JOINT_CAPACITY_EXCEEDED:AWS_HK:cpu_vcpu' in audit['reasons']


@pytest.mark.parametrize('resource',['cpu_vcpu','ram_gb','gpu_count','storage_tb'])
def test_joint_capacity_all_resources(resource):
    c,apps,portfolio=benchmark('medium')
    c['capacity']['default_residual_per_site']={r:1000.0 for r in apps[0]['demand']}
    for a in apps:
        a['demand'][resource]=1.0
    c['capacity']['default_residual_per_site'][resource]=4.0
    audit=validate(c,apps,portfolio,assign(apps,['AWS_HK']*3))
    assert all(v['valid'] for v in audit['applications'].values())
    assert not audit['valid']
    assert f'JOINT_CAPACITY_EXCEEDED:AWS_HK:{resource}' in audit['reasons']


def test_new_dependency_directed_latency():
    c,apps,portfolio=benchmark('medium')
    apps[0]['dependencies'][1]['max_p95_latency_ms']=8.0
    forward=assign(apps,['AWS_HK','AZURE_HK','GLOBAL_DC_HK'])
    reverse=assign(apps,['AZURE_HK','AWS_HK','GLOBAL_DC_HK'])
    assert validate(c,apps,portfolio,forward)['valid']
    assert not validate(c,apps,portfolio,reverse)['valid']
    del c['dependencies']['latency_matrix_ms']['AWS_HK']['AZURE_HK']
    assert not validate(c,apps,portfolio,forward)['valid']
    assert canonical(forward) not in {canonical(p) for p in enumerate_candidates(c,apps,portfolio)[0]}


def test_joint_cost_fixed_overhead_once():
    c,apps,portfolio=benchmark('medium')
    c['capacity']['default_residual_per_site']['cpu_vcpu']=512.0
    p=assign(apps,['AWS_HK']*3)
    metrics=measure(c,apps,portfolio,p)
    assert metrics['tco']==36*(72*18+100+3*250)
    assert sum(metrics['tco_breakdown'].values())==metrics['tco']
    assert validate(c,apps,portfolio,p,metrics)['valid']


def test_joint_budget_infeasible_has_oracle_explanation(tmp_path):
    c,apps,portfolio=benchmark('medium')
    c['cost']['budget']=dict(enabled=True,max_total_tco_usd=1.0)
    oracle=enumerate_independently(c,apps,portfolio)
    assert oracle['prebudget_feasible_count']==4 and oracle['deployable_count']==0
    assert all(r['metrics']['tco']>1 for r in oracle['records'])
    candidates,_=enumerate_candidates(c,apps,portfolio)
    solved=solve(c,apps,candidates,[measure(c,apps,portfolio,p) for p in candidates],tmp_path)
    assert solved['status']=='INFEASIBLE'
    assert solved['model_counts']['linear_constraints']==82


def test_single_cost_latency_conflict(tmp_path):
    c,apps,portfolio=benchmark('single');app=apps[0]
    candidates,_=enumerate_candidates(c,app,portfolio)
    metrics=[measure(c,app,portfolio,p) for p in candidates]
    choices=[]
    for objective in ('tco','latency'):
        c['objectives']['weights']={k:float(k==objective) for k in c['objectives']['weights']}
        folder=tmp_path/objective;folder.mkdir()
        solved=solve(c,app,candidates,metrics,folder)
        choices.append(candidates[solved['selected_index']]['environments']['PROD'])
    assert choices==['GLOBAL_DC_HK','AWS_HK']


def test_complex_risk_metrics_vary_and_match_independent():
    c,apps,portfolio=benchmark('complex')
    oracle=enumerate_independently(c,apps,portfolio)
    for metric in ('concentration','blast_radius'):
        low,high=oracle['normalization_ranges'][metric]
        assert low<high
    p=oracle['records'][0]['placement']
    metrics=measure(c,apps,portfolio,p)
    assert metrics['critical_application_count']==9
    for scenario in metrics['failure_scenarios']:
        names=scenario['residual_business_disruption_critical']
        assert len(names)==len(set(names))
    assert validate(c,apps,portfolio,p,metrics)['valid']


@pytest.mark.parametrize('key',['tco','latency','concentration','blast_radius'])
@pytest.mark.parametrize('value',[float('nan'),float('inf'),True,None])
def test_nonfinite_or_malformed_metrics_fail_closed(config,app,portfolio,key,value):
    p=enumerate_candidates(config,app,portfolio)[0][0]
    m=measure(config,app,portfolio,p);m[key]=value
    audit=validate(config,app,portfolio,p,m)
    assert not audit['valid'] and 'INVALID_REPORTED_METRICS' in audit['reasons']


def test_empty_reported_metrics_not_silently_ignored(config,app,portfolio):
    p=enumerate_candidates(config,app,portfolio)[0][0]
    assert not validate(config,app,portfolio,p,{})['valid']


@pytest.mark.parametrize('field,value',[('rto_minutes',61.0),('rpo_minutes',16.0),('verified',False)])
def test_recovery_thresholds_in_filter_and_validator(config,app,portfolio,field,value):
    p=enumerate_candidates(config,app,portfolio)[0][0]
    sid=p['environments']['PROD']
    next(s for s in config['sites']['sites'] if s['id']==sid)['recovery'][field]=value
    assert not validate(config,app,portfolio,p)['valid']
    assert canonical(p) not in {canonical(v) for v in enumerate_candidates(config,app,portfolio)[0]}


def test_missing_ai_ml_blocks_complex_app():
    c,apps,portfolio=benchmark('complex')
    c['sites']['service_categories_default'].remove('AI_ML')
    assert not enumerate_candidates(c,apps,portfolio)[0]
    assert enumerate_independently(c,apps,portfolio)['deployable_count']==0


def test_dependency_cycle_closure_terminates():
    c,apps,portfolio=benchmark('medium')
    c['capacity']['default_residual_per_site']['cpu_vcpu']=512.0
    apps[2]['dependencies'].append(dict(target=apps[0]['id'],max_p95_latency_ms=30.0))
    p=assign(apps,['AWS_HK']*3)
    metric=measure(c,apps,portfolio,p)
    assert validate(c,apps,portfolio,p,metric)['valid']


def test_joint_approval_stays_conditional():
    c,apps,portfolio=benchmark('medium')
    c['regulatory']['materiality']['MATERIAL']['approval_status']='PENDING'
    candidates,_=enumerate_candidates(c,apps,portfolio)
    assert candidates and all(p['approval_pending'] for p in candidates)
    assert validate(c,apps,portfolio,candidates[0])['status']=='CONDITIONAL'


def test_scope_and_reference_guards():
    c,apps,_=benchmark('medium')
    duplicate=deepcopy(c['experiment']);duplicate['selected_application_ids'][1]=duplicate['selected_application_ids'][0]
    with pytest.raises(ValueError):Experiment.model_validate(duplicate)
    wrong=deepcopy(c['experiment']);wrong['scope']='SINGLE_NEW_APPLICATION'
    with pytest.raises(ValueError):Experiment.model_validate(wrong)
    apps[0]['dependencies'][0]['target']='UNSELECTED'
    with pytest.raises(ValueError):cross_validate(c)


def test_piecewise_objective_rejected(config):
    import gurobipy as gp
    with gp.Env(params={'OutputFlag':0}) as env, gp.Model(env=env) as m:
        x=m.addVar(lb=0,ub=2)
        m.setPWLObj(x,[0,1,2],[0,2,1])
        with pytest.raises(ValueError,match='piecewise-linear'):
            guard(m,config['solver'])


@pytest.mark.parametrize('strategy',['HIERARCHICAL','PARETO'])
def test_joint_strategies_match_exhaustive_order(strategy,tmp_path):
    c,apps,portfolio=benchmark('medium')
    oracle=enumerate_independently(c,apps,portfolio)
    c['objectives']['strategy']=strategy
    c['objectives']['pareto']['enabled']=strategy=='PARETO'
    candidates,_=enumerate_candidates(c,apps,portfolio)
    metrics=[measure(c,apps,portfolio,p) for p in candidates]
    solved=solve(c,apps,candidates,metrics,tmp_path)
    chosen=metrics[solved['selected_index']]
    if strategy=='HIERARCHICAL':
        order=c['objectives']['hierarchical_order'][1:]
        assert tuple(chosen[k] for k in order)==min(tuple(r['metrics'][k] for k in order) for r in oracle['records'])
    else:
        expected={canonical(r['placement']) for r in oracle['records'] if not any(all(other['metrics'][k]<=r['metrics'][k] for k in ('tco','latency','concentration','blast_radius')) and any(other['metrics'][k]<r['metrics'][k] for k in ('tco','latency','concentration','blast_radius')) for other in oracle['records'])}
        assert {canonical(candidates[i]) for i in solved['pareto_indices']}==expected


def test_oracle_detects_production_metric_corruption(tmp_path,monkeypatch):
    import src.main as runner
    original=runner.measure
    def corrupt(*args):
        value=original(*args);value['tco']+=100
        return value
    monkeypatch.setattr(runner,'measure',corrupt)
    with pytest.raises(AssertionError,match='metric differs'):
        verify_run(ROOT/'tests/fixtures/config/scenarios/single.yaml',tmp_path)
