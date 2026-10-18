"""CLI and reproducible one-experiment run orchestration."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import traceback
import uuid
from time import perf_counter
from .config import load
from .portfolio import generate
from .feasibility import enumerate_candidates
from .metrics import measure
from .validation import validate
from .solver import solve, LicenseSizeExceeded
from .persistence import atomic, json_write, csv_write, hash_file


def run(config, output, resume=None):
    run_started=perf_counter()
    timings=dict(input_loading=0.0,feasibility_preprocessing=0.0,candidate_enumeration=0.0,model_construction=0.0,gurobi_optimization=0.0,independent_validation=0.0)
    root=Path(output).resolve(); root.mkdir(parents=True,exist_ok=True)
    if resume:
        if Path(resume).name!=resume:
            raise ValueError('resume expects a run folder name, not a path')
        previous=root/resume
        metadata=json.loads((previous/'metadata.json').read_text())
        _, sources=load(config)
        hashes={k:v['sha256'] for k,v in sources.items()}
        if metadata['input_hashes']!=hashes or metadata.get('source_hashes')!=source_hashes():
            raise ValueError('resume input/source hashes differ; start a new run')
        if (previous/'COMPLETE.json').exists():
            manifest=json.loads((previous/'COMPLETE.json').read_text())
            if any(not (previous/k).is_file() or hash_file(previous/k)!=v for k,v in manifest.items()):
                raise ValueError('resume artifact integrity verification failed')
            return previous,json.loads((previous/'placement.json').read_text())
        # Interrupted runs remain immutable. Restart deterministically in a linked folder.
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-'+uuid.uuid4().hex[:8]
    folder=root/run_id; folder.mkdir()
    atomic(folder/'run.log','Phase 1 run started\n')
    atomic(folder/'solver.log','Solver has not started.\n')
    metadata=dict(run_id=run_id,started_utc=datetime.now(timezone.utc).isoformat(),python=platform.python_version(),
                  resumed_from=resume,input_hashes={},source_hashes=source_hashes(),synthetic=True)
    validation=dict(valid=False,status='REJECTED',reasons=['RUN_NOT_COMPLETED'])
    result=dict(status='REJECTED',placement=None)
    try:
        # Save the selected experiment even if its schema fails.
        atomic(folder/'input_snapshot'/'experiment.yaml',Path(config).read_text())
        def capture_input(key, source):
            metadata['input_hashes'][key]=source['sha256']
            metadata.setdefault('input_paths',{})[key]=source['path']
            atomic(folder/'input_snapshot'/f'{key}.yaml',source['text'])
        load_started=perf_counter()
        c,sources=load(config,on_source=capture_input)
        timings["input_loading"]=perf_counter()-load_started
        from .config import formulation_method as method
        formulation=method(c)
        metadata["formulation_method"]=formulation
        metadata['input_hashes']={k:v['sha256'] for k,v in sources.items()}
        metadata['input_paths']={k:v['path'] for k,v in sources.items()}
        metadata['experiment_id']=c['experiment']['experiment_id']
        for key,value in sources.items():
            atomic(folder/'input_snapshot'/f'{key}.yaml',value['text'])
        for path in Path(__file__).parent.glob('*.py'):
            atomic(folder/'source_snapshot'/path.name,path.read_text())
        atomic(folder/'generated_formulation.py',Path(__file__).with_name('direct.py' if formulation=='DIRECT_ASSIGNMENT_MILP' else 'solver.py').read_text())
        json_write(folder/'metadata.json',metadata)
        portfolio=generate(c)
        json_write(folder/'portfolio.json',portfolio)
        selected=[next(a for a in c['applications']['applications'] if a['id']==key)
                  for key in c['experiment']['selected_application_ids']]
        app=selected[0] if len(selected)==1 else selected
        direct_rows=[]
        if formulation=='DIRECT_ASSIGNMENT_MILP':
            from .direct import solve_direct
            solution,screening,direct_rows=solve_direct(c,selected,portfolio,folder)
            candidates=[r['placement'] for r in direct_rows]
            metrics=[measure(c,app,portfolio,p) for p in candidates]
            timings.update(solution['timings'])
            json_write(folder/'direct_solutions.json',direct_rows)
        else:
            candidates,screening=enumerate_candidates(c,app,portfolio,timings)
            metric_started=perf_counter()
            metrics=[measure(c,app,portfolio,p) for p in candidates]
            timings['candidate_enumeration']+=perf_counter()-metric_started
            json_write(folder/'candidates.json',[dict(placement=p,metrics=m) for p,m in zip(candidates,metrics)])
        json_write(folder/'screening.json',screening)
        pending=bool(candidates and candidates[0]['approval_pending'])
        # Strict deployment stage is infeasible if approval is pending. The solver then
        # evaluates explicitly labelled conditional proposals, without relaxing policy.
        json_write(folder/'constraint_manifest.json',dict(
            formulation=formulation,application_id=selected[0]['id'] if len(selected)==1 else None,
            application_ids=[a['id'] for a in selected],
            screened_rules=['policy','service','processing','NONPROD_HK','HA','RTO_RPO','direct_latency','approval','capacity'],
            linear_rules=['select_exactly_one','reservation_capacity','simultaneous_peak_capacity','optional_budget'],
            strict_stage_status='INFEASIBLE_APPROVAL_PENDING' if pending else 'SOLVING',
            candidate_count=None if formulation=='DIRECT_ASSIGNMENT_MILP' else len(candidates)))
        conditional_analysis=pending and c['objectives']['infeasibility']['remediation_analysis']
        # Without explicit conditional analysis, pending assignments are excluded
        # by the strict approval gate, even if technically feasible.
        solve_candidates=[] if pending and not conditional_analysis else candidates
        solve_metrics=[] if pending and not conditional_analysis else metrics
        if formulation!='DIRECT_ASSIGNMENT_MILP':
            solution=solve(c,app,solve_candidates,solve_metrics,folder)
            solution['stage']='CONDITIONAL_ANALYSIS' if conditional_analysis else 'STRICT'
            timings.update(solution['timings'])
        json_write(folder/'solver.json',solution)
        index=solution['selected_index']
        if index is None:
            outcome='INFEASIBLE' if solution['status']=='INFEASIBLE' else 'NO_SOLUTION'
            result=dict(status=outcome,placement=None,solver_status=solution['status'])
            validation=dict(valid=False,status=outcome,reasons=['NO_FEASIBLE_INCUMBENT'],screening=screening)
        else:
            placement=candidates[index]; metric=metrics[index]
            validation_started=perf_counter()
            validation=validate(c,app,portfolio,placement,metric)
            if direct_rows:
                model_audit=validate(c,app,portfolio,placement,direct_rows[index]['metrics'])
                if not model_audit['valid']:
                    validation=model_audit
            timings['independent_validation']+=perf_counter()-validation_started
            result=dict(status=validation['status'],placement=placement,metrics=metric,
                        solver_status=solution['status'],optimality_proven=solution['optimality_proven'])
            if pending:
                result['strict_stage_status']='INFEASIBLE_APPROVAL_PENDING'
            if direct_rows and c['objectives']['strategy']=='PARETO':
                validation_started=perf_counter()
                result['pareto_candidates']=[dict(placement=r['placement'],metrics=metrics[i],validation=validate(c,app,portfolio,r['placement'],r['metrics'])) for i,r in enumerate(direct_rows)]
                timings['independent_validation']+=perf_counter()-validation_started
            if 'pareto_indices' in solution:
                result['pareto_candidates']=[dict(placement=candidates[i],metrics=metrics[i],validation=validate(c,app,portfolio,candidates[i],metrics[i])) for i in solution['pareto_indices']]
        proposals=[]
        if c['objectives']['infeasibility']['remediation_analysis'] and result['status'] in ('INFEASIBLE','CONDITIONAL'):
            if pending:
                for selected_app in selected:
                    approval=c['regulatory']['materiality'][selected_app['materiality']]
                    if approval['approval_required'] and approval['approval_status']!='APPROVED':
                        proposals.append(dict(status='CONDITIONAL',application_id=selected_app['id'],action='Obtain required materiality approval',lead_time_days=approval['lead_time_days']))
            if any('MISSING_RECOVERY_EVIDENCE' in reasons for sites in screening['sites'].values() for reasons in sites.values()):
                proposals.append(dict(status='CONDITIONAL',action='Provide verified site RTO/RPO recovery evidence; re-run all checks',automatically_applied=False))
            if screening.get('capacity_rejections') and c['capacity']['capacity_expansion']['allow_conditional_proposal']:
                proposals.append(dict(status='CONDITIONAL',action='Review capacity deficits in screening.json; obtain a complete resource-specific expansion quote and rerun',lead_time_days=c['capacity']['capacity_expansion']['default_lead_time_days'],cpu_unit_cost=c['capacity']['capacity_expansion']['cost_per_cpu_vcpu'],automatically_applied=False))
        json_write(folder/'remediation.json',proposals)
    except LicenseSizeExceeded as exc:
        result=dict(status='LICENSE_SIZE_EXCEEDED',placement=None,model_counts=exc.counts)
        validation=dict(valid=False,status=result['status'],reasons=[str(exc)])
        json_write(folder/'solver.json',dict(status=result['status'],model_counts=exc.counts,optimized=False))
    except Exception as exc:
        from .errors import UnsupportedDirect
        if isinstance(exc,UnsupportedDirect):
            json_write(folder/'solver.json',getattr(exc,'details',dict(status='UNSUPPORTED',reason=str(exc))))
        result=dict(status='UNSUPPORTED' if isinstance(exc,UnsupportedDirect) else 'REJECTED',placement=None,error_type=type(exc).__name__,error=str(exc))
        validation=dict(valid=False,status=result['status'],reasons=[str(exc)])
        atomic(folder/'error.log',traceback.format_exc())
    metadata['finished_utc']=datetime.now(timezone.utc).isoformat()
    metadata['status']=result['status']
    try:
        from importlib.metadata import version
        metadata['dependencies']={p:version(p) for p in ('gurobipy','pydantic','PyYAML')}
    except Exception:
        pass
    json_write(folder/'metadata.json',metadata)
    json_write(folder/'validation.json',validation)
    json_write(folder/'placement.json',result)
    fields=['run_id','status','solver_status','tco','latency','concentration','blast_radius']
    csv_write(folder/'summary.csv',[dict(run_id=run_id,status=result['status'],solver_status=result.get('solver_status',''),**{k:result.get('metrics',{}).get(k,'') for k in fields[3:]})],fields)
    if result.get('placement'):
        placements=list(result['placement']['applications'].values()) if 'applications' in result['placement'] else [result['placement']]
        rows=[]
        for p in placements:
            rows.extend(dict(application_id=p['application_id'],environment=e,site_id=s) for e,s in p['environments'].items())
            rows.append(dict(application_id=p['application_id'],environment='DR',site_id=p['dr_site_id']))
    else:
        rows=[]
    csv_write(folder/'placement.csv',rows,['application_id','environment','site_id'])
    atomic(folder/'run.log',(folder/'run.log').read_text()+f"Finished: {result['status']}\n")
    timings['total_end_to_end']=perf_counter()-run_started
    try:
        import resource, sys
        timings['peak_memory_bytes']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
        timings['memory_scope']='process high-water RSS; compare isolated processes'
    except ImportError:
        timings['peak_memory_bytes']=None
    json_write(folder/'timings.json',timings)
    manifest={str(p.relative_to(folder)):hash_file(p) for p in folder.rglob('*') if p.is_file()}
    json_write(folder/'COMPLETE.json',manifest)
    return folder,result


def source_hashes():
    return {p.name:hash_file(p) for p in sorted(Path(__file__).parent.glob('*.py'))}


def main():
    parser=argparse.ArgumentParser(description='Phase 1 reference workload placement')
    parser.add_argument('--config',required=True)
    parser.add_argument('--output',default='results')
    parser.add_argument('--resume',help='Completed run ID to verify/reuse, or interrupted run ID to restart')
    args=parser.parse_args()
    folder,result=run(args.config,args.output,args.resume)
    print(json.dumps(dict(run_directory=str(folder),status=result['status'])))
    return 2 if result['status'] in ('REJECTED','LICENSE_SIZE_EXCEEDED','NO_SOLUTION','UNSUPPORTED') else 0

if __name__=='__main__':
    raise SystemExit(main())
