"""Direct-model equivalence and deliberate formulation corruption tests."""
from copy import deepcopy
from itertools import product
from pathlib import Path
import json
import gurobipy as gp
import pytest
from src.config import load, formulation_method
from src.direct import build, preprocess, solve_direct, extract
from src.errors import UnsupportedDirect
from src.feasibility import enumerate_candidates
from src.metrics import measure
from src.portfolio import generate
from src.schema import Experiment
from src.solver import guard, LicenseSizeExceeded
from src.validation import validate
from src.verification import enumerate_independently, canonical
from src.main import run

ROOT=Path(__file__).resolve().parents[1]
KEYS=('tco','latency','concentration','blast_radius')


def fixture(name):
    c,_=load(ROOT/f'tests/fixtures/config/scenarios/{name}.yaml')
    apps=c['applications']['applications']
    return c,apps,generate(c)


def fixed(problem, placement):
    parts=placement.get('applications',{placement.get('application_id'):placement})
    for (aid,e,s),v in problem['x'].items():
        v.LB=v.UB=int(parts[aid]['environments'][e]==s)


def assignment(apps,sites):
    parts={a['id']:dict(application_id=a['id'],environments={e:s for e in a['environments']},dr_site_id=s,failure_domain_contract='INDEPENDENT_LOCAL_DOMAINS') for a,s in zip(apps,sites)}
    return next(iter(parts.values())) if len(apps)==1 else dict(applications=parts)


def values(problem):
    return {k:v.getValue() for k,v in problem['metrics'].items()}


@pytest.mark.parametrize('name,variables,rows',[('single',29,121),('medium',61,161),('complex',134,231)])
def test_direct_weighted_equals_oracle(name,variables,rows,tmp_path):
    c,apps,portfolio=fixture(name)
    oracle=enumerate_independently(c,apps,portfolio)
    result,_,solutions=solve_direct(c,apps,portfolio,tmp_path)
    assert result['status']=='OPTIMAL' and result['mip_gap']==0
    assert result['model_counts']['variables']==variables
    assert result['model_counts']['linear_constraints']==rows
    assert result['incumbent']==pytest.approx(oracle['objective_min'],abs=1e-8)
    assert result['timings']['candidate_enumeration']==0
    assert len(result['solve_calls'])==9
    for key in KEYS:
        assert result['normalization']['ranges'][key]==pytest.approx(oracle['normalization_ranges'][key],abs=1e-8)
    row=solutions[0]
    equivalent=[r for r in oracle['records'] if abs(r['objective']-oracle['objective_min'])<1e-8]
    assert canonical(row['placement']) in {canonical(r['placement']) for r in equivalent}
    assert validate(c,apps[0] if len(apps)==1 else apps,portfolio,row['placement'],row['metrics'])['valid']


@pytest.mark.parametrize('name,feasible',[('single',9),('medium',4),('complex',282)])
def test_complete_projected_feasible_set_and_exact_metrics(name,feasible):
    # No feasible-candidate list is supplied to build. Independent checking tests
    # every unary-domain combination, INCLUDING jointly invalid assignments.
    c,apps,portfolio=fixture(name)
    domains,_,_=preprocess(c,apps,portfolio)
    with gp.Env(params={'OutputFlag':0}) as env:
        problem=build(c,apps,portfolio,env,domains);m=problem['model']
        try:
            counts=guard(m,c['solver']);assert counts['variables']<1800
            m.Params.OutputFlag=0;m.Params.MIPGap=0
            m.setObjective(0)
            keys=list(domains); found=0
            for chosen in product(*(domains[k] for k in keys)):
                parts={a['id']:dict(application_id=a['id'],environments={},failure_domain_contract='INDEPENDENT_LOCAL_DOMAINS') for a in apps}
                for (aid,e),sid in zip(keys,chosen):parts[aid]['environments'][e]=sid
                for p in parts.values():p['dr_site_id']=p['environments']['PROD']
                p=next(iter(parts.values())) if len(apps)==1 else dict(applications=parts)
                audit=validate(c,apps[0] if len(apps)==1 else apps,portfolio,p)
                fixed(problem,p);m.optimize()
                assert (m.Status==gp.GRB.OPTIMAL)==audit['valid']
                if audit['valid']:
                    found+=1
                    for key,value in values(problem).items():
                        assert value==pytest.approx(audit['independent_metrics'][key],abs=1e-6)
            assert found==feasible
        finally:m.dispose()


@pytest.mark.parametrize('name',['single','medium','complex'])
@pytest.mark.parametrize('strategy',['HIERARCHICAL','PARETO'])
def test_direct_strategies(name,strategy,tmp_path):
    c,apps,portfolio=fixture(name);oracle=enumerate_independently(c,apps,portfolio)
    c['objectives']['strategy']=strategy;c['objectives']['pareto']['enabled']=strategy=='PARETO'
    result,_,rows=solve_direct(c,apps,portfolio,tmp_path)
    assert result['status']=='OPTIMAL'
    def dominates(a,b):
        return all(a[k]<=b[k]+1e-7 for k in KEYS) and any(a[k]<b[k]-1e-7 for k in KEYS)
    for row in rows:
        assert validate(c,apps[0] if len(apps)==1 else apps,portfolio,row['placement'],row['metrics'])['valid']
        assert not any(dominates(r['metrics'],row['metrics']) for r in oracle['records'])
    if strategy=='HIERARCHICAL':
        order=c['objectives']['hierarchical_order'][1:]
        assert tuple(rows[0]['metrics'][k] for k in order)==pytest.approx(min(tuple(r['metrics'][k] for k in order) for r in oracle['records']))
    else:
        assert len(rows)<=c['objectives']['pareto']['max_candidates']
        assert result['maximum_model_counts']['linear_constraints']<=1800
        nondominated={tuple(round(r['metrics'][k],6) for k in KEYS) for r in oracle['records'] if not any(dominates(q['metrics'],r['metrics']) for q in oracle['records'])}
        obtained={tuple(round(r['metrics'][k],6) for k in KEYS) for r in rows}
        assert obtained<=nondominated
        assert len(obtained)==min(len(nondominated),c['objectives']['pareto']['max_candidates'])


def test_no_enumeration_dependency(tmp_path,monkeypatch):
    import src.feasibility as f
    import src.joint as j
    import src.main as runner
    def forbidden(*args,**kwargs):pytest.fail('direct path called complete candidate enumeration')
    monkeypatch.setattr(f,'enumerate_candidates',forbidden)
    monkeypatch.setattr(j,'enumerate_joint',forbidden)
    monkeypatch.setattr(runner,'enumerate_candidates',forbidden)
    folder,result=run(ROOT/'tests/fixtures/config/scenarios/complex_direct.yaml',tmp_path)
    assert result['status']=='DEPLOYABLE'
    assert not (folder/'candidates.json').exists()
    timing=json.loads((folder/'timings.json').read_text())
    assert timing['candidate_enumeration']==0 and timing['total_end_to_end']>0


def test_missing_capacity_constraints_detected():
    c,apps,pf=fixture('medium');p=assignment(apps,['AWS_HK']*3)
    with gp.Env(params={'OutputFlag':0}) as env:
        problem=build(c,apps,pf,env);m=problem['model']
        try:
            fixed(problem,p);m.optimize();assert m.Status==gp.GRB.INFEASIBLE
            m.remove([m.getConstrByName(f'{kind}[AWS_HK,cpu_vcpu]') for kind in ('reserved','peak')]);m.update();m.optimize()
            assert m.Status==gp.GRB.OPTIMAL
            assert not validate(c,apps,pf,p,values(problem))['valid']
        finally:m.dispose()


def test_missing_completeness_detected():
    c,apps,pf=fixture('single')
    with gp.Env(params={'OutputFlag':0}) as env:
        problem=build(c,apps,pf,env);m=problem['model']
        try:
            p=assignment(apps,['AWS_HK']);fixed(problem,p)
            for (a,e,s),v in problem['x'].items():
                if e=='PROD':v.LB=v.UB=0
            m.optimize();assert m.Status==gp.GRB.INFEASIBLE
            m.remove(m.getConstrByName('complete[TEST-APP,PROD]'));m.update();m.optimize()
            assert m.Status==gp.GRB.OPTIMAL
            del p['environments']['PROD']
            assert not validate(c,apps[0],pf,p)['valid']
        finally:m.dispose()


def test_reversed_dependency_detected():
    c,apps,pf=fixture('medium');apps[0]['dependencies'][1]['max_p95_latency_ms']=8.0
    p=assignment(apps,['AZURE_HK','AWS_HK','GLOBAL_DC_HK'])
    mutated=deepcopy(c);matrix=c['dependencies']['latency_matrix_ms']
    mutated['dependencies']['latency_matrix_ms']={s:{t:matrix[t][s] for t in row} for s,row in matrix.items()}
    with gp.Env(params={'OutputFlag':0}) as env:
        problem=build(mutated,apps,pf,env);m=problem['model']
        try:
            fixed(problem,p);m.optimize();assert m.Status==gp.GRB.OPTIMAL
            assert not validate(c,apps,pf,p)['valid']
        finally:m.dispose()


def test_incorrect_dr_capacity_detected():
    c,apps,pf=fixture('single');c['capacity']['default_residual_per_site']['cpu_vcpu']=20.0
    p=assignment(apps,['AWS_HK'])
    with gp.Env(params={'OutputFlag':0}) as env:
        problem=build(c,apps,pf,env);m=problem['model']
        try:
            fixed(problem,p);m.optimize();assert m.Status==gp.GRB.INFEASIBLE
            for kind in ('reserved','peak'):
                m.chgCoeff(m.getConstrByName(f'{kind}[AWS_HK,cpu_vcpu]'),problem['x']['TEST-APP','PROD','AWS_HK'],10)
            m.optimize();assert m.Status==gp.GRB.OPTIMAL
            assert not validate(c,apps[0],pf,p)['valid']
        finally:m.dispose()


@pytest.mark.parametrize('metric',['tco','concentration'])
def test_incorrect_metric_expression_detected(metric):
    c,apps,pf=fixture('single');p=assignment(apps,['AWS_HK'])
    with gp.Env(params={'OutputFlag':0}) as env:
        problem=build(c,apps,pf,env);m=problem['model']
        try:
            # Deliberately omit DR CPU cost or count the app twice in concentration.
            problem['metrics'][metric]+=(-10*18*36 if metric=='tco' else .1)*problem['x']['TEST-APP','PROD','AWS_HK']
            fixed(problem,p);m.optimize();assert m.Status==gp.GRB.OPTIMAL
            assert not validate(c,apps[0],pf,p,values(problem))['valid']
        finally:m.dispose()


def test_incorrect_transitive_blast_detected():
    c,apps,pf=fixture('complex');p=assignment(apps,['GLOBAL_DC_HK']*2+['AWS_SG']*3)
    mutated=deepcopy(apps);mutated[4]['dependencies']=mutated[4]['dependencies'][1:]
    with gp.Env(params={'OutputFlag':0}) as env:
        problem=build(c,mutated,pf,env);m=problem['model']
        try:
            fixed(problem,p);m.optimize();assert m.Status==gp.GRB.OPTIMAL
            assert not validate(c,apps,pf,p,values(problem))['valid']
        finally:m.dispose()


@pytest.mark.parametrize('change',['budget','missing_policy','rto','capacity','approval'])
def test_direct_infeasible(change,tmp_path):
    c,apps,pf=fixture('medium')
    if change=='budget':c['cost']['budget']=dict(enabled=True,max_total_tco_usd=1.0)
    if change=='missing_policy':c['regulatory']['policies']=[]
    if change=='rto':
        for s in c['sites']['sites']:s['recovery']['rto_minutes']=1000
    if change=='capacity':c['capacity']['default_residual_per_site']['cpu_vcpu']=0
    if change=='approval':c['regulatory']['materiality']['MATERIAL']['approval_status']='DENIED'
    result,_,rows=solve_direct(c,apps,pf,tmp_path)
    assert result['status']=='INFEASIBLE' and not rows


def test_direct_size_guard_precedes_all_optimizations(tmp_path,monkeypatch):
    c,apps,pf=fixture('complex');c['solver']['safety_limits']['max_variables']=133
    def forbidden(*args,**kwargs):pytest.fail('oversize model optimized')
    monkeypatch.setattr(gp.Model,'optimize',forbidden)
    with pytest.raises(LicenseSizeExceeded):solve_direct(c,apps,pf,tmp_path)


def test_uncertified_normalization_fails_explicitly(tmp_path):
    c,apps,pf=fixture('complex');c['solver']['time_limit_seconds']=1e-12
    with pytest.raises(UnsupportedDirect,match='NORMALIZATION_NOT_CERTIFIED'):
        solve_direct(c,apps,pf,tmp_path)


def test_pareto_fractional_cent_unsupported(tmp_path):
    c,apps,pf=fixture('single');c['objectives']['strategy']='PARETO'
    c['cost']['per_vcpu_monthly']['AWS_HK']=18.000001
    with pytest.raises(UnsupportedDirect,match='TCO coefficients'):
        solve_direct(c,apps,pf,tmp_path)


def test_formulation_schema_backward_compatible():
    old,_=load(ROOT/'tests/fixtures/config/experiments/experiment.yaml')
    new,_,_=fixture('single')
    assert formulation_method(old)==formulation_method(new)=='ENUMERATION_MILP'
    conflicting=deepcopy(new['experiment']);conflicting['formulation_method']='DIRECT_ASSIGNMENT_MILP'
    with pytest.raises(ValueError,match='conflicting'):Experiment.model_validate(conflicting)


@pytest.mark.parametrize('change',['service','processing','rpo','ha','site_approval'])
def test_direct_unary_hard_gates(change,tmp_path):
    c,apps,pf=fixture('single')
    if change=='service':c['sites']['service_categories_default']=[]
    for site in c['sites']['sites']:
        if change=='processing':site['processing_country']='UNAPPROVED'
        if change=='rpo':site['recovery']['rpo_minutes']=1000
        if change=='ha':site['independent_failure_domains']=1
        if change=='site_approval':site['approved']=False
    result,_,rows=solve_direct(c,apps,pf,tmp_path)
    assert result['status']=='INFEASIBLE' and rows==[]


@pytest.mark.parametrize('remediation',[True,False])
def test_pending_direct_approval(remediation,tmp_path):
    c,apps,pf=fixture('single')
    c['regulatory']['materiality']['MATERIAL']['approval_status']='PENDING'
    c['objectives']['infeasibility']['remediation_analysis']=remediation
    result,_,rows=solve_direct(c,apps,pf,tmp_path)
    if remediation:
        assert result['stage']=='CONDITIONAL_ANALYSIS'
        assert validate(c,apps[0],pf,rows[0]['placement'],rows[0]['metrics'])['status']=='CONDITIONAL'
    else:
        assert result['status']=='INFEASIBLE' and not rows


def test_direct_variable_reduced_peak_equivalence(config,app,portfolio,tmp_path):
    app['demand_mode']='VARIABLE';app['peak_demand']={k:v*2 for k,v in app['demand'].items()}
    app['dr'].update(mode='REDUCED',cpu_ratio=.25,ram_ratio=.25,gpu_ratio=.25,storage_ratio=.25)
    config['capacity'].update(allocation_mode='SHARED_POOL',reservation_mode='TYPICAL_WITH_SCALING')
    config['capacity']['shared_pool']['oversubscription']['cpu_vcpu']=100
    config['capacity']['default_residual_per_site']['cpu_vcpu']=200
    oracle=enumerate_independently(config,[app],portfolio)
    result,_,rows=solve_direct(config,[app],portfolio,tmp_path)
    assert result['incumbent']==pytest.approx(oracle['objective_min'],abs=1e-8)
    assert rows[0]['placement']['environments']['PROD']=='AWS_SG'
    assert validate(config,app,portfolio,rows[0]['placement'],rows[0]['metrics'])['valid']


def test_direct_zero_critical_apps_and_no_dependencies(tmp_path):
    c,apps,pf=fixture('single')
    for a in apps+pf:a['criticality']='NON_CRITICAL';a['dependencies']=[]
    result,_,rows=solve_direct(c,apps,pf,tmp_path)
    assert rows[0]['metrics']['blast_radius']==0 and rows[0]['metrics']['concentration']==0 and rows[0]['metrics']['latency']==0
    assert validate(c,apps[0],pf,rows[0]['placement'],rows[0]['metrics'])['valid']


def test_comparison_cli_evidence(tmp_path):
    from src.comparison import compare
    folder,rows=compare([ROOT/'tests/fixtures/config/scenarios/single.yaml'],tmp_path,repeats=1)
    assert len(rows)==2 and all(r['status']=='OPTIMAL' for r in rows)
    assert all(r['median_external_end_to_end']>=r['median_total_end_to_end'] for r in rows)
    evidence=json.loads((folder/'comparison.json').read_text())[0]
    assert evidence['direct_projection_verification']['complete_feasible_set_equal']
    assert len(evidence['runs'])==2


def test_direct_scenario_exposure_and_disruption_counts():
    c,apps,pf=fixture('complex');p=assignment(apps,['GLOBAL_DC_HK']*2+['AWS_SG']*3)
    nodes={a['id']:a for a in pf+apps}
    locations={a['id']:a['site_id'] for a in pf}
    locations.update({a:p['applications'][a]['environments']['PROD'] for a in p['applications']})
    critical={k for k,a in nodes.items() if a['criticality']=='CRITICAL'}
    with gp.Env(params={'OutputFlag':0}) as env:
        problem=build(c,apps,pf,env);m=problem['model']
        try:
            fixed(problem,p);m.optimize();assert m.Status==gp.GRB.OPTIMAL
            for scenario in c['dependencies']['failure_scenarios']:
                initial={k for k,s in locations.items() if s==scenario['site_id']} if scenario['type']=='SITE' else {scenario['application_id']}
                affected=set(initial)
                for _ in range(len(nodes)):
                    affected.update(k for k,a in nodes.items() if any(d['target'] in affected for d in a.get('dependencies',[])))
                direct=len(initial&critical) if scenario['type']=='SITE' else 0
                assert problem['infrastructure'][scenario['id']].getValue()==pytest.approx(direct)
                assert problem['disruption'][scenario['id']].getValue()==pytest.approx(len(affected&critical))
        finally:m.dispose()
