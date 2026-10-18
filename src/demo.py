"""Single-workload demo. Generated Python is never executed; fallback is explicit."""
import argparse
import json
import re
from pathlib import Path
from time import perf_counter
from typing import Literal
from uuid import uuid4
import yaml
from pydantic import Field
from .schema import Strict
from .config import load, UniqueLoader
from .portfolio import generate
from .problem_contract import from_config, digest, canonical_bytes
from .inference_config import load_ai, InferenceAI
from .optimind import OptiMindAdapter
from .generation import messages, parse_response
from .formulation_ir import parse_ir
from .ir_reference import direct_to_ir
from .formulation_validation import fidelity, verify_formulation
from .validation import validate
from .verification import enumerate_independently, canonical
from .feasibility import site_reasons, loads, enumerate_candidates
from .metrics import measure
from .main import run as reference_run, source_hashes
from .persistence import atomic, json_write, hash_file
from .runtime_verification import seal

ROOT = Path(__file__).resolve().parents[1]


class DemoConfig(Strict):
    version: Literal[1] = 1
    benchmark: str = 'config/scenario.yaml'
    mode: Literal['AI_ASSISTED', 'REFERENCE_FALLBACK'] = 'AI_ASSISTED'
    ai_config: str = 'config/optimind.yaml'
    allow_reference_fallback: bool = False
    formulation_interface: Literal['STRUCTURED_IR', 'COMPACT_SPEC'] = 'STRUCTURED_IR'
    reference_reason: str = Field(default='Explicitly selected reference demonstration; no AI claim.', min_length=1)
    max_alternatives: int = Field(default=3, ge=0, le=10)
    max_explanation_assignments: int = Field(default=10000, gt=0, le=200000)


class Recommendation(Strict):
    version: Literal[1] = 1
    run_id: str
    source: Literal['OPTIMIND_IR', 'OPTIMIND_SPEC_TRUSTED_MILP', 'REFERENCE_FALLBACK']
    status: Literal['RECOMMENDED', 'INFEASIBLE', 'REJECTED', 'FAILED'] = 'FAILED'
    fallback_used: bool = False
    fallback_reason: str | None = None
    model: dict = Field(default_factory=dict)
    genuine_inference: bool = False
    placement: dict | None = None
    metrics: dict | None = None
    solver: dict = Field(default_factory=dict)
    independent_validation: dict = Field(default_factory=dict)
    explanation: dict = Field(default_factory=dict)
    errors: list[dict] = Field(default_factory=list)
    timings: dict = Field(default_factory=dict)
    input_hashes: dict = Field(default_factory=dict)


def resolve(path, config_path):
    p = Path(path)
    if p.is_absolute(): return p
    for parent in Path(config_path).resolve().parents:
        if (parent/p).is_file(): return parent/p
    raise ValueError('CONFIG_PATH_NOT_FOUND: '+path)


def explain(c, app, portfolio, placement, options):
    """Reasons from deterministic screening, metrics and independent audits only."""
    sites = {s['id']:s for s in c['sites']['sites']}
    result = dict(eligibility={e:{sid:site_reasons(c,app,s,e,portfolio) for sid,s in sites.items()}
                               for e in app['environments']},
                  approval_policy=c['regulatory']['materiality'].get(app['materiality']),
                  expansion_policy='Conditional proposal only; never included in a deployable recommendation.',
                  alternatives=[], alternatives_method='Independent bounded enumeration; not generated IR solutions.')
    raw = len(sites)**len(app['environments'])
    if raw <= options.max_explanation_assignments:
        oracle = enumerate_independently(c,[app],portfolio)
        _, screening = enumerate_candidates(c,app,portfolio)
        result['global_rejections'] = screening.get('global_reasons', [])
        rejected = screening.get('capacity_rejections', [])
        result['capacity_rejection_count'] = len(rejected)
        result['capacity_rejection_examples'] = rejected[:options.max_alternatives]
        result['budget_rejection_count'] = sum(not r['within_budget'] for r in oracle['records'])
        rows = sorted((r for r in oracle['records'] if r['within_budget'] and r['status']=='DEPLOYABLE'),key=lambda r:r['objective'])
        result.update(normalization_ranges=oracle['normalization_ranges'],deployable_alternatives_count=len(rows))
        for row in rows:
            if placement is not None and canonical(row['placement'])==canonical(placement): continue
            result['alternatives'].append(dict(placement=row['placement'],metrics=row['metrics'],normalized_objective=row['objective'],
                tradeoff_vs_selected=None if placement is None else {k:row['metrics'][k]-validate(c,app,portfolio,placement)['independent_metrics'][k] for k in row['metrics']}))
            if len(result['alternatives']) >= options.max_alternatives: break
        if options.max_alternatives == 0: result['alternatives']=[]
    else: result['alternatives_unavailable']='Enumeration exceeds configured explanation limit.'
    if placement is None: return result
    audit = validate(c,app,portfolio,placement)
    if not audit['valid'] or audit['status']!='DEPLOYABLE': raise ValueError('EXPLANATION_PLACEMENT_NOT_DEPLOYABLE')
    metrics = measure(c,app,portfolio,placement)
    reserved,peak = loads(c,app,placement),loads(c,app,placement,True)
    capacity = {}
    for sid,usage in reserved.items():
        available=c['capacity']['site_overrides'].get(sid,c['capacity']['default_residual_per_site'])
        capacity[sid]={r:dict(reserved=usage[r],simultaneous_peak=peak[sid][r],available=available[r],
            peak_utilization=peak[sid][r]/available[r] if available[r] else None,peak_headroom=available[r]-peak[sid][r]) for r in usage}
    result.update(production=placement['environments']['PROD'],dr=dict(site=placement['dr_site_id'],
        mode=app['dr']['mode'],failure_domain_contract=placement['failure_domain_contract'],
        required_rto_minutes=app['dr']['rto_minutes'],required_rpo_minutes=app['dr']['rpo_minutes'],
        site_evidence=sites[placement['dr_site_id']]['recovery']),
        nonproduction={e:s for e,s in placement['environments'].items() if e!='PROD'},
        total_tco=metrics['tco'],tco_breakdown=metrics['tco_breakdown'],latency_edges=metrics['latency_edges'],capacity=capacity,
        regulatory_compliance='PASS',recovery_compliance='PASS',validation_reasons=audit['reasons'],
        feasibility_basis='Independent deployment, sovereignty, services, recovery, capacity, latency, approval and budget audit passed.')
    return result


def ai_solution(c, app, portfolio, options, settings_path, folder, runtime_evidence, cache_dir, adapter):
    settings=load_ai(settings_path)
    if not settings.enabled or not re.fullmatch(r'[a-f0-9]{40}',settings.model.revision or ''):
        raise ValueError('ENABLED_IMMUTABLE_CHECKPOINT_REQUIRED')
    if settings.generation.mode != 'STRUCTURED_IR': raise ValueError('DEMO_REQUIRES_STRUCTURED_IR')
    json_write(folder/'settings.json',settings.model_dump())
    contract=from_config(c,portfolio)
    compact=options.formulation_interface=='COMPACT_SPEC'
    if compact:
        from .demo_spec import messages as spec_messages
        prompt=spec_messages(contract)
    else:
        prompt=messages(contract,settings)
    json_write(folder/'problem.json',contract.model_dump());json_write(folder/'prompt.json',prompt)
    adapter=adapter or OptiMindAdapter(settings)
    if adapter.settings.model_dump()!=settings.model_dump(): raise ValueError('ADAPTER_SETTINGS_MISMATCH')
    request,info=adapter.prepare(prompt,folder,runtime_evidence,cache_dir)
    json_write(folder/'request.json',request)
    result=adapter.generate(request,folder);json_write(folder/'response.json',result)
    atomic(folder/'raw_response.txt',result['text'])
    if result['model_id']!=settings.model.model_id or result['revision']!=settings.model.revision:
        raise ValueError('INFERENCE_IDENTITY_MISMATCH')
    json_write(folder/'generation.json',dict(model_id=result['model_id'],revision=result['revision'],
        genuine_inference=not adapter.backend.is_mock,backend=result['backend'],prompt_hash=digest(prompt),
        response_sha256=hash_file(folder/'raw_response.txt'),finish_reason=result.get('finish_reason'),
        input_tokens=result.get('input_tokens'),output_tokens=result.get('output_tokens')))
    if result.get('finish_reason')=='length': raise ValueError('GENERATION_TRUNCATED')
    if compact:
        from .demo_spec import parse_spec, compile_spec
        spec=parse_spec(result['text'],contract)
        json_write(folder/'specification.json',spec.model_dump())
        ir=compile_spec(spec,contract,folder)
    else:
        parsed=parse_response(result['text'],'STRUCTURED_IR')
        if not parsed['format_valid']: raise ValueError('UNSUPPORTED_MODEL_OUTPUT')
        atomic(folder/'generated_ir.json',parsed['ir_payload'])
        ir=parse_ir(parsed['ir_payload'])
        # Legacy algebra authoring retains its original conservative gate.
        expected=direct_to_ir(contract,folder/'coverage_reference')
        coverage=fidelity(ir,expected,contract);json_write(folder/'coverage.json',coverage)
        if coverage['errors'] or coverage['missing_mandatory'] or coverage['additional_rows']:
            raise ValueError('IR_NOT_CERTIFIED: algebra/requirement coverage differs; no generated-model solve authorized')
    report=verify_formulation(contract,canonical_bytes(ir),folder/'validation',
        max_raw=settings.evaluation.max_raw,max_projected=settings.evaluation.max_projected)
    eq=report.get('levels',{}).get('5_equivalence',{})
    if not eq.get('complete') or any(eq.get(k,0) for k in ('extra_infeasible','missing_feasible','metric_mismatches','objective_mismatches')):
        raise ValueError('IR_EQUIVALENCE_NOT_VERIFIED')
    if report.get('failure_classifications'): raise ValueError('IR_VALIDATION_FAILED')
    if report.get('error') or report.get('compilation',{}).get('status')!='COMPILED':
        raise ValueError('IR_COMPILATION_NOT_VERIFIED')
    if compact:
        # Canonical name recognition is not a proof for the auxiliary encoding.
        # Require the same complete feasible-set/metric/objective probes above.
        json_write(folder/'spec_validation.json',dict(status='BOUNDED_EQUIVALENT_TRUSTED_EXPANSION',
            specification_hash=digest(spec),expanded_ir_hash=digest(ir),equivalence=eq,
            algebra_author='TRUSTED_COMPILER',canonical_classification=report['classification']))
    return report.get('placement'),report.get('metrics'),report.get('solver',{}),report.get('placement_audit',{})


def run_demo(config=ROOT/'config/runtime/reference.yaml', output=ROOT/'results/demo', *, runtime_evidence=None, cache_dir=ROOT/'.model_cache', adapter=None, options=None):
    """UI-independent backend; returns (new artifact directory, Recommendation)."""
    started=perf_counter();folder=Path(output).resolve()/('demo-'+uuid4().hex);folder.mkdir(parents=True)
    result=Recommendation(run_id=folder.name,source='OPTIMIND_IR')
    stage='INPUTS'
    try:
        if options is None:
            options=DemoConfig.model_validate(yaml.load(Path(config).read_text(),Loader=UniqueLoader))
        else:
            options=DemoConfig.model_validate(options.model_dump())
        atomic(folder/'demo_config.yaml',yaml.safe_dump(options.model_dump(),sort_keys=False))
        if options.mode=='REFERENCE_FALLBACK': result.source='REFERENCE_FALLBACK'
        elif options.formulation_interface=='COMPACT_SPEC': result.source='OPTIMIND_SPEC_TRUSTED_MILP'
        benchmark=resolve(options.benchmark,config);c,sources=load(benchmark)
        result.input_hashes={k:v['sha256'] for k,v in sources.items()}
        for k,v in sources.items(): atomic(folder/'input_snapshot'/f'{k}.yaml',v['text'])
        json_write(folder/'provenance.json',dict(source_hashes=source_hashes(),demo_config_hash=hash_file(config)))
        selected=c['experiment']['selected_application_ids']
        if len(selected)!=1: raise ValueError('DEMO_REQUIRES_ONE_NEW_APPLICATION')
        if c['objectives']['strategy']!='WEIGHTED': raise ValueError('DEMO_INITIAL_SCOPE_WEIGHTED_OBJECTIVE_ONLY')
        app=next(a for a in c['applications']['applications'] if a['id']==selected[0]);portfolio=generate(c)
        json_write(folder/'problem.json',from_config(c,portfolio).model_dump())
        placement=metrics=None;solver={};audit={}
        fallback=options.mode=='REFERENCE_FALLBACK'
        if fallback: result.fallback_reason=options.reference_reason
        else:
            stage='AI_SPEC' if options.formulation_interface=='COMPACT_SPEC' else 'AI_IR'
            ai_folder=folder/'ai';ai_folder.mkdir()
            settings_path=resolve(options.ai_config,config)
            result.model=load_ai(settings_path).model.model_dump()
            atomic(ai_folder/'ai_input.yaml',settings_path.read_text())
            try:
                placement,metrics,solver,audit=ai_solution(c,app,portfolio,options,settings_path,ai_folder,runtime_evidence,cache_dir,adapter)
            except Exception as exc:
                result.errors.append(dict(stage=stage,type=type(exc).__name__,message=str(exc)))
                json_write(ai_folder/'rejection.json',result.errors[-1])
                if not options.allow_reference_fallback: raise
                fallback=True;result.fallback_reason=str(exc)
            finally:
                if (ai_folder/'generation.json').exists():
                    result.genuine_inference=json.loads((ai_folder/'generation.json').read_text())['genuine_inference']
        if fallback:
            stage='REFERENCE_FALLBACK';result.source='REFERENCE_FALLBACK';result.fallback_used=True
            ref_folder,ref=reference_run(benchmark,folder/'reference')
            solver=json.loads((ref_folder/'solver.json').read_text());audit=json.loads((ref_folder/'validation.json').read_text())
            placement=ref.get('placement');metrics=ref.get('metrics')
        result.solver=solver;result.independent_validation=audit
        stage='INDEPENDENT_VALIDATION'
        if placement is None:
            result.status='INFEASIBLE' if solver.get('status')=='INFEASIBLE' else 'FAILED'
            if result.status=='FAILED': result.errors.append(dict(stage=stage,message='NO_VERIFIED_SOLUTION'))
        else:
            audit=validate(c,app,portfolio,placement,metrics);result.independent_validation=audit
            if not audit['valid'] or audit['status']!='DEPLOYABLE':
                result.status='REJECTED';result.errors.append(dict(stage=stage,message='PLACEMENT_NOT_DEPLOYABLE',details=audit))
            elif not solver.get('optimality_proven'):
                result.status='FAILED';result.errors.append(dict(stage=stage,message='OPTIMALITY_NOT_PROVEN'))
            else:
                result.status='RECOMMENDED';result.placement=placement;result.metrics=audit['independent_metrics']
        stage='EXPLANATION';result.explanation=explain(c,app,portfolio,result.placement,options)
        if result.source=='OPTIMIND_SPEC_TRUSTED_MILP':
            result.explanation['formulation']=json.loads((folder/'ai/compilation_provenance.json').read_text())
    except Exception as exc:
        result.status='FAILED';result.placement=None;result.metrics=None
        error=dict(stage=stage,type=type(exc).__name__,message=str(exc))
        if error not in result.errors:result.errors.append(error)
    finally:
        from .placement_explanation import build, render
        report = dict(status=result.status, scope='No validated inputs or accepted placement.', selected=[], constraints=[],
            objective={}, alternatives={}, ai={}, solver=result.solver, independent_validation=result.independent_validation)
        if 'portfolio' in locals():
            try:
                report = build(c, app, portfolio, result, options.mode)
            except Exception as exc:
                result.status='FAILED';result.placement=None;result.metrics=None
                result.errors.append(dict(stage='CONSTRAINT_REPORT',type=type(exc).__name__,message=str(exc)))
                report.update(status='FAILED',unavailable_reason='Constraint report failed; no accepted recommendation.')
        json_write(folder/'constraint_audit.json', report)
        atomic(folder/'placement_explanation.md', render(report))
        result.timings['total_seconds']=perf_counter()-started
        json_write(folder/'recommendation.json',result.model_dump())
        json_write(folder/'explanation.json',result.explanation)
        atomic(folder/'summary.md',f'# Workload placement recommendation\n\nStatus: {result.status}\n\nSource: {result.source}\n\nFallback: {result.fallback_used}; reason: {result.fallback_reason}\n\nPlacement:\n```json\n{json.dumps(result.placement,indent=2)}\n```\n\nMetrics:\n```json\n{json.dumps(result.metrics,indent=2)}\n```\n\nErrors:\n```json\n{json.dumps(result.errors,indent=2)}\n```\n')
        atomic(folder/'run.log',f'Status={result.status}; source={result.source}; errors={json.dumps(result.errors)}\n')
        seal(folder)
    return folder,result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default=str(ROOT/'config/runtime/reference.yaml'))
    parser.add_argument('--output',default=str(ROOT/'results/demo'))
    parser.add_argument('--runtime-evidence');parser.add_argument('--cache-dir',default=str(ROOT/'.model_cache'))
    args=parser.parse_args();folder,result=run_demo(args.config,args.output,runtime_evidence=args.runtime_evidence,cache_dir=args.cache_dir)
    print(folder,result.status,result.source)
    raise SystemExit(0 if result.status=='RECOMMENDED' else 2)

if __name__=='__main__':main()
