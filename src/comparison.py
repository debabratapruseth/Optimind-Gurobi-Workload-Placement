"""Isolated-process formulation benchmarks plus independent equivalence checks."""
import argparse
from itertools import product
import json
from pathlib import Path
import statistics
import subprocess
import sys
from time import perf_counter
import uuid
import gurobipy as gp
from .config import load, formulation_method
from .portfolio import generate
from .validation import validate
from .verification import enumerate_independently, canonical
from .direct import build
from .solver import guard
from .persistence import json_write, csv_write, hash_file

KEYS=('tco','latency','concentration','blast_radius')


def verify_projection(c, apps, portfolio, oracle):
    """Fixed-assignment solver checks are verification only, not optimizer input."""
    start=perf_counter();seen=set();examined=0
    with gp.Env(params={'OutputFlag':0}) as env:
        problem=build(c,apps,portfolio,env);m=problem['model']
        try:
            guard(m,c['solver']);m.Params.OutputFlag=0;m.setObjective(0)
            keys=list(problem['domains'])
            for selection in product(*(problem['domains'][key] for key in keys)):
                examined+=1
                parts={a['id']:dict(application_id=a['id'],environments={},failure_domain_contract='INDEPENDENT_LOCAL_DOMAINS') for a in apps}
                for (aid,e),s in zip(keys,selection):parts[aid]['environments'][e]=s
                for p in parts.values():p['dr_site_id']=p['environments']['PROD']
                placement=next(iter(parts.values())) if len(apps)==1 else dict(applications=parts)
                audit=validate(c,apps[0] if len(apps)==1 else apps,portfolio,placement)
                for (aid,e,s),x in problem['x'].items():x.LB=x.UB=int(parts[aid]['environments'][e]==s)
                m.optimize()
                if m.Status not in (gp.GRB.OPTIMAL,gp.GRB.INFEASIBLE):
                    raise AssertionError('fixed-assignment equivalence check not certified')
                if (m.Status==gp.GRB.OPTIMAL)!=audit['valid']:
                    raise AssertionError('direct feasible set differs from independent hard-constraint audit')
                if audit['valid']:
                    seen.add(canonical(placement))
                    for k,expr in problem['metrics'].items():
                        if abs(expr.getValue()-audit['independent_metrics'][k])>1e-6:
                            raise AssertionError(f'direct metric differs: {k}')
            expected={canonical(r['placement']) for r in oracle['records'] if r['within_budget'] and r['status']=='DEPLOYABLE'}
            if seen!=expected:
                raise AssertionError('direct model loses or adds oracle-feasible placements')
            return dict(examined_projected_assignments=examined,feasible_count=len(seen),complete_feasible_set_equal=True,
                        all_feasible_metric_vectors_equal=True,runtime_seconds=perf_counter()-start)
        finally:m.dispose()


def compare(configs, output, repeats=3):
    output=Path(output).resolve()/('comparison-'+uuid.uuid4().hex[:10]);output.mkdir(parents=True)
    reports=[];rows=[]
    for config in configs:
        config=Path(config).resolve();direct=config.with_name(config.stem+'_direct.yaml')
        c,_=load(config);dc,_=load(direct)
        if formulation_method(c)!='ENUMERATION_MILP' or formulation_method(dc)!='DIRECT_ASSIGNMENT_MILP':
            raise ValueError('comparison requires the enumeration and direct formulations explicitly')
        for key in c['experiment']:
            if key not in ('experiment_id','formulation_method','optimization','paths') and c['experiment'][key]!=dc['experiment'][key]:
                raise ValueError(f'benchmark experiments differ in {key}')
        apps=[next(a for a in c['applications']['applications'] if a['id']==aid) for aid in c['experiment']['selected_application_ids']]
        portfolio=generate(c)
        oracle=enumerate_independently(c,apps,portfolio)
        projection=verify_projection(c,apps,portfolio,oracle)
        optimum=oracle['objective_min'];expected={canonical(r['placement']):r for r in oracle['records']}
        report=dict(benchmark=c['experiment']['experiment_id'],oracle_objective=optimum,
                    oracle={k:v for k,v in oracle.items() if k!='records'},direct_projection_verification=projection,runs=[])
        reference_hashes=None
        for repeat in range(repeats):
            # Alternate order to reduce a systematic first-run ordering effect.
            order=[('ENUMERATION_MILP',config),('DIRECT_ASSIGNMENT_MILP',direct)]
            if repeat%2:order.reverse()
            for method,path in order:
                start=perf_counter()
                process=subprocess.run([sys.executable,'-m','src.main','--config',str(path),'--output',str(output/'runs')],capture_output=True,text=True)
                wall=perf_counter()-start
                if process.returncode:
                    raise RuntimeError(process.stdout+'\n'+process.stderr)
                info=json.loads(process.stdout.strip().splitlines()[-1]);folder=Path(info['run_directory'])
                result=json.loads((folder/'placement.json').read_text());solver=json.loads((folder/'solver.json').read_text())
                timing=json.loads((folder/'timings.json').read_text());metadata=json.loads((folder/'metadata.json').read_text())
                if metadata['formulation_method']!=method:
                    raise AssertionError('executed formulation does not match benchmark label')
                hashes={k:v for k,v in metadata['input_hashes'].items() if k!='experiment'}
                if reference_hashes is None:reference_hashes=hashes
                if hashes!=reference_hashes:raise AssertionError('formulations used different problem inputs')
                if result['status']!='DEPLOYABLE' or solver['status']!='OPTIMAL' or solver['mip_gap']!=0:
                    raise AssertionError('benchmark not solved and independently validated to zero gap')
                chosen=expected[canonical(result['placement'])]
                if abs(chosen['objective']-optimum)>1e-8 or abs(solver['incumbent']-optimum)>1e-8:
                    raise AssertionError('different weighted optimum; equivalent tied placements are accepted')
                for k in KEYS:
                    if abs(result['metrics'][k]-chosen['metrics'][k])>1e-6:
                        raise AssertionError('chosen independent metrics disagree')
                    actual=solver['normalization']['ranges'][k];expected_range=oracle['normalization_ranges'][k]
                    if any(abs(a-b)>1e-8 for a,b in zip(actual,expected_range)):
                        raise AssertionError('normalization bounds disagree')
                timing['external_end_to_end']=wall
                timed=sum(timing[k] for k in ('input_loading','feasibility_preprocessing','candidate_enumeration','model_construction','gurobi_optimization','independent_validation'))
                timing['other_runner_overhead']=max(0.0,timing['total_end_to_end']-timed)
                run=dict(method=method,repeat=repeat,run_directory=str(folder),input_hashes=metadata['input_hashes'],
                         source_hashes=metadata['source_hashes'],manifest_sha256=hash_file(folder/'COMPLETE.json'),
                         solver_status=solver['status'],objective=solver['incumbent'],best_bound=solver['best_bound'],gap=solver['mip_gap'],
                         model_counts=solver['model_counts'],timings=timing,placement=result['placement'],
                         metrics={k:result['metrics'][k] for k in KEYS},solve_calls=solver.get('solve_calls',[]))
                report['runs'].append(run)
        for method in ('ENUMERATION_MILP','DIRECT_ASSIGNMENT_MILP'):
            runs=[r for r in report['runs'] if r['method']==method]
            row=dict(benchmark=report['benchmark'],method=method,repeats=repeats,variables=runs[0]['model_counts']['variables'],linear_constraints=runs[0]['model_counts']['linear_constraints'],status='OPTIMAL',objective=runs[0]['objective'],best_bound=runs[0]['best_bound'],gap=0.0)
            for k in ('input_loading','feasibility_preprocessing','candidate_enumeration','model_construction','gurobi_optimization','independent_validation','total_end_to_end','external_end_to_end','other_runner_overhead','peak_memory_bytes'):
                observed=[r['timings'][k] for r in runs if r['timings'][k] is not None]
                row['median_'+k]=statistics.median(observed) if observed else None
            rows.append(row)
        reports.append(report)
    json_write(output/'comparison.json',reports)
    csv_write(output/'comparison.csv',rows,list(rows[0]))
    return output,rows


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--configs',nargs='+',required=True)
    parser.add_argument('--output',default='results/phase1_6')
    parser.add_argument('--repeats',type=int,default=3)
    args=parser.parse_args()
    if args.repeats<1:parser.error('--repeats must be positive')
    folder,rows=compare(args.configs,args.output,args.repeats)
    print(json.dumps(dict(output=str(folder),summary=rows),indent=2))

if __name__=='__main__':main()
