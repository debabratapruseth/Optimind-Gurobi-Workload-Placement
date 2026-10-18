"""Independent exhaustive oracle and CLI for small baseline-verification instances.

Imports no solver, screening or production metric helpers. Unary pruning uses
only the independent validator and preserves all possible jointly feasible choices.
The oracle recomputes normalization/objectives independently, not from solver scores.
"""
import argparse
from collections import Counter
from itertools import product
import json
import math
from pathlib import Path
from time import perf_counter
from .validation import validate

KEYS=('tco','latency','concentration','blast_radius')


def canonical(placement):
    items=placement.get('applications',{placement.get('application_id'):placement})
    return tuple(sorted((key,tuple(sorted(p['environments'].items())),p['dr_site_id'],p['failure_domain_contract']) for key,p in items.items()))


def enumerate_independently(c, apps, portfolio):
    """Complete search; no top-k, candidate list, model coefficients or sampling."""
    started=perf_counter()
    selected={a['id'] for a in apps}
    options=[]; raw_count=1
    no_budget=dict(c,cost=dict(c['cost'],budget=dict(enabled=False,max_total_tco_usd=None)))
    for app in apps:
        local=dict(app,dependencies=[d for d in app['dependencies'] if d['target'] not in selected])
        raw_count*=len(c['sites']['sites'])**len(app['environments'])
        valid=[]
        for values in product([s['id'] for s in c['sites']['sites']],repeat=len(app['environments'])):
            envs=dict(zip(app['environments'],values))
            p=dict(application_id=app['id'],environments=envs,dr_site_id=envs['PROD'],failure_domain_contract='INDEPENDENT_LOCAL_DOMAINS')
            if validate(no_budget,local,portfolio,p)['valid']:
                valid.append(p)
        options.append(valid)
    records=[]; rejected=Counter(); examined=0
    for values in product(*options):
        examined+=1
        placement=values[0] if len(apps)==1 else dict(applications={a['id']:p for a,p in zip(apps,values)})
        audit=validate(no_budget,apps[0] if len(apps)==1 else apps,portfolio,placement)
        if audit['valid']:
            record=dict(placement=placement,metrics=audit['independent_metrics'],status=audit['status'])
            record['within_budget']=not c['cost']['budget']['enabled'] or record['metrics']['tco']<=c['cost']['budget']['max_total_tco_usd']+1e-6
            records.append(record)
        else:
            rejected.update(audit['reasons'])
    limits={k:(min((r['metrics'][k] for r in records),default=0),max((r['metrics'][k] for r in records),default=0)) for k in KEYS}
    weight_sum=math.fsum(c['objectives']['weights'].values())
    for r in records:
        r['objective']=math.fsum(c['objectives']['weights'][k]*(r['metrics'][k]-limits[k][0])/(limits[k][1]-limits[k][0])/weight_sum for k in KEYS if limits[k][1]>limits[k][0])
    feasible=[r for r in records if r['within_budget'] and r['status']=='DEPLOYABLE']
    return dict(raw_assignment_count=raw_count,unary_options=[len(o) for o in options],examined_joint_assignments=examined,
                prebudget_feasible_count=len(records),deployable_count=len(feasible),
                objective_min=min((r['objective'] for r in feasible),default=None),normalization_ranges=limits,
                records=records,rejection_counts=dict(rejected),runtime_seconds=perf_counter()-started)


def verify_run(config, output):
    from .config import load, formulation_method
    from .portfolio import generate
    from .main import run
    from .persistence import json_write, hash_file
    c,_=load(config)
    if formulation_method(c)=='DIRECT_ASSIGNMENT_MILP':
        raise ValueError('Use python -m src.comparison for direct-versus-enumeration verification')
    if c['objectives']['strategy']!='WEIGHTED':
        raise ValueError('verification CLI currently certifies WEIGHTED benchmarks; strategy tests cover alternatives')
    apps=[next(a for a in c['applications']['applications'] if a['id']==key) for key in c['experiment']['selected_application_ids']]
    portfolio=generate(c)
    oracle=enumerate_independently(c,apps,portfolio)
    folder,result=run(config,output)
    solver=json.loads((folder/'solver.json').read_text())
    production=json.loads((folder/'candidates.json').read_text())
    independent={canonical(r['placement']):r for r in oracle['records']}
    actual={canonical(r['placement']):r for r in production}
    if len(actual)!=len(production) or set(independent)!=set(actual):
        raise AssertionError('independent and production feasible assignment sets differ')
    for key,row in actual.items():
        for metric in KEYS:
            if not math.isclose(row['metrics'][metric],independent[key]['metrics'][metric],rel_tol=1e-12,abs_tol=1e-6):
                raise AssertionError(f'independent metric differs: {metric} at {key}')
    if oracle['objective_min'] is None:
        if solver['status']!='INFEASIBLE':
            raise AssertionError('oracle infeasibility disagrees with solver')
        selected=None
    else:
        if result['status']!='DEPLOYABLE' or solver['status']!='OPTIMAL':
            raise AssertionError('benchmark did not finish with validated optimum')
        selected=independent[canonical(result['placement'])]
        if not math.isclose(selected['objective'],oracle['objective_min'],abs_tol=1e-9) or not math.isclose(solver['incumbent'],oracle['objective_min'],abs_tol=1e-9):
            raise AssertionError('Gurobi objective disagrees with independent exhaustive optimum')
    report=dict(benchmark=c['experiment']['experiment_id'],config=str(config),run_directory=str(folder),
                verified=True,source_hashes=json.loads((folder/'metadata.json').read_text())['source_hashes'],
                input_hashes=json.loads((folder/'metadata.json').read_text())['input_hashes'],
                run_manifest_sha256=hash_file(folder/'COMPLETE.json'),
                model_counts=solver['model_counts'],solver_status=solver['status'],mip_gap=solver['mip_gap'],
                incumbent=solver['incumbent'],best_bound=solver['best_bound'],solver_runtime_seconds=solver['runtime_seconds'],
                oracle={k:v for k,v in oracle.items() if k!='records'},
                witness=selected,metric_ranges={k:list(oracle['normalization_ranges'][k]) for k in KEYS})
    report_path=Path(output)/f'verification-{folder.name}.json'
    json_write(report_path,report)
    return report


def main():
    from .persistence import csv_write
    parser=argparse.ArgumentParser(description='Exhaustive baseline verification; tiny instances only')
    parser.add_argument('--configs',nargs='+',required=True)
    parser.add_argument('--output',default='results/phase1_5')
    args=parser.parse_args()
    reports=[verify_run(path,args.output) for path in args.configs]
    rows=[dict(benchmark=r['benchmark'],variables=r['model_counts']['variables'],constraints=r['model_counts']['linear_constraints'],status=r['solver_status'],gap=r['mip_gap'],runtime_seconds=r['solver_runtime_seconds'],objective=r['incumbent'],oracle_objective=r['oracle']['objective_min'],verified=r['verified']) for r in reports]
    csv_write(Path(args.output)/'verification_summary.csv',rows,list(rows[0]))
    print(json.dumps(rows,indent=2))

if __name__=='__main__':
    main()
