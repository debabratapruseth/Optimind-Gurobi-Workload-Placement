"""Five-level validation, with bounded independent projected equivalence evidence.

Canonical algebra recognition is deliberately conservative. Equivalent unfamiliar
encodings are UNVERIFIED, not certified by manifest labels or one good incumbent.
"""
from itertools import product
from pathlib import Path
from time import perf_counter
import math
import gurobipy as gp
from .problem_contract import inputs, digest
from .formulation_ir import parse_ir
from .ir_reference import REQUIREMENTS, direct_to_ir
from .ir_compiler import CompiledIR, restricted_environment
from .validation import validate
from .verification import enumerate_independently, canonical
from .persistence import json_write


def close(a, b):
    return math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-6)


def fidelity(ir, expected, contract):
    """Compare actual domains, rows and expressions, not just declared labels.

This recognizer is for canonical direct algebra; it is not a theorem prover for
arbitrarily reformulated linearizations. Extra rows require exhaustive testing.
"""
    errors = []
    missing = []
    claims = {e.requirement: e for e in ir.manifest}
    refs = {e.requirement: e for e in expected.manifest}
    if set(claims) != set(REQUIREMENTS):
        missing.append('requirement inventory mismatch')
    for req, ref in refs.items():
        claim = claims.get(req)
        if claim is None or claim.status != ref.status:
            missing.append(req + ': mandatory status mismatch')
            continue
        for field in ('variables', 'constraints', 'metrics', 'objectives'):
            if not set(getattr(ref, field)) <= set(getattr(claim, field)):
                errors.append(req + ': incomplete ' + field + ' links')
    actual_vars = {v.id: v.model_dump() for v in ir.variables}
    expected_vars = {v.id: v.model_dump() for v in expected.variables}
    if actual_vars != expected_vars:
        errors.append('variable domains/placement metadata differ')
    actual_rows = {r.id: r.model_dump() for r in ir.constraints}
    for row in expected.constraints:
        if actual_rows.get(row.id) != row.model_dump():
            errors.append(row.family + ': missing/changed algebra ' + row.id)
    if ir.metrics != expected.metrics:
        errors.append('metric expression mismatch')
    if ir.objectives != expected.objectives or ir.objective_sense != expected.objective_sense:
        errors.append('objective definition mismatch')
    if ir.problem_hash != digest(contract):
        missing.append('problem hash mismatch')
    return dict(recognized=not errors and not missing and ir.profile == 'CANONICAL_DIRECT_V1', errors=errors, missing_mandatory=missing,
                additional_rows=sorted(set(actual_rows) - {r.id for r in expected.constraints}))


def placement_from_choices(apps, keys, chosen):
    parts = {a['id']: dict(application_id=a['id'], environments={}, failure_domain_contract='INDEPENDENT_LOCAL_DOMAINS') for a in apps}
    for (aid, env), sid in zip(keys, chosen):
        parts[aid]['environments'][env] = sid
    for p in parts.values():
        p['dr_site_id'] = p['environments']['PROD']
    return next(iter(parts.values())) if len(parts) == 1 else dict(applications=parts)


def equivalence(compiled, contract, max_raw=200_000, max_projected=2000):
    c, apps, portfolio = inputs(contract)
    raw = len(c['sites']['sites']) ** sum(len(a['environments']) for a in apps)
    result = dict(complete=False, raw_assignments=raw, examined=0, extra_infeasible=0, missing_feasible=0, metric_mismatches=0, objective_mismatches=0)
    if compiled.ir.objective_sense != 'MIN':
        result['objective_mismatches'] = 1
    if raw > max_raw:
        return dict(result, reason='independent oracle raw assignment limit')
    if compiled.ir.profile == 'GENERAL_LINEAR_V1' and not any(v.assignment for v in compiled.ir.variables):
        return dict(result, reason='unfamiliar placement encoding: assignment metadata required')
    oracle = enumerate_independently(c, apps, portfolio)
    keys = [(a['id'], e) for a in apps for e in a['environments']]
    domains = {key: set() for key in keys}
    for v in compiled.ir.variables:
        if v.assignment:
            d = v.assignment
            if (d.application, d.environment) not in domains or d.site not in {s['id'] for s in c['sites']['sites']}:
                return dict(result, reason='unknown placement metadata')
            domains[d.application, d.environment].add(d.site)
    # Independent oracle supplies any feasible choices absent from the submitted IR.
    for r in oracle['records']:
        parts = r['placement'].get('applications', {apps[0]['id']: r['placement']})
        for key in keys:
            domains[key].add(parts[key[0]]['environments'][key[1]])
    count = math.prod(len(domains[key]) for key in keys)
    result['projected_assignments'] = count
    if count > max_projected:
        return dict(result, reason='projected assignment limit')
    reference = {canonical(r['placement']): r for r in oracle['records'] if r['within_budget']}
    m = compiled.model
    m.NumObj = 0
    m.update()
    m.Params.MIPGap = 0
    m.Params.MIPGapAbs = 0
    original = {v.id: (v.lower, v.upper) for v in compiled.ir.variables}
    metric_exprs = compiled.metrics
    from .ir_compiler import expression
    objectives = {o.id: o.weight * expression(o.expression, compiled.variables) for o in compiled.ir.objectives}
    for chosen in product(*(sorted(domains[k]) for k in keys)):
        result['examined'] += 1
        chosen_map = dict(zip(keys, chosen))
        absent = any(not any(v.assignment and (v.assignment.application, v.assignment.environment, v.assignment.site) == (a, e, chosen_map[a, e]) for v in compiled.ir.variables) for a, e in keys)
        placement = placement_from_choices(apps, keys, chosen)
        ref = reference.get(canonical(placement))
        audit = validate(c, apps[0] if len(apps) == 1 else apps, portfolio, placement)
        if bool(ref) != audit['valid']:
            raise AssertionError('independent oracle/placement audit disagreement')
        bounds_invalid = False
        for v in compiled.ir.variables:
            var = compiled.variables[v.id]
            var.LB, var.UB = original[v.id]
            if v.assignment:
                d = v.assignment
                value = int(chosen_map[d.application, d.environment] == d.site)
                if not v.lower <= value <= v.upper:
                    bounds_invalid = True
                var.LB = var.UB = value
        if absent or bounds_invalid:
            feasible = False
        else:
            m.setObjective(0.)
            stats = compiled.optimize()
            if stats['status'] not in ('OPTIMAL', 'INFEASIBLE'):
                return dict(result, reason='uncertified feasibility probe', probe_status=stats['status'])
            feasible = stats['status'] == 'OPTIMAL'
        if feasible and not audit['valid']:
            result['extra_infeasible'] += 1
        if not feasible and audit['valid']:
            result['missing_feasible'] += 1
        if not feasible or not audit['valid']:
            continue
        expected = dict(audit['independent_metrics'])
        if c['objectives']['strategy'] == 'WEIGHTED':
            expected['weighted'] = ref['objective']
        # Min AND max: a single favorable auxiliary assignment is insufficient.
        probes = [(key, expr, expected[key], 'metric_mismatches') for key, expr in metric_exprs.items()]
        if c['objectives']['strategy'] == 'WEIGHTED' and len(compiled.ir.objectives) == 1:
            o = compiled.ir.objectives[0]
            probes.append((o.id, objectives[o.id], ref['objective'], 'objective_mismatches'))
        elif c['objectives']['strategy'] == 'HIERARCHICAL' and len(compiled.ir.objectives) == 4 and len({o.priority for o in compiled.ir.objectives}) == 4:
            ordered = sorted(compiled.ir.objectives, key=lambda o: -o.priority)
            for o, metric in zip(ordered, c['objectives']['hierarchical_order'][1:]):
                probes.append((o.id, objectives[o.id], expected[metric] * o.weight, 'objective_mismatches'))
        else:
            return dict(result, reason='unsupported objective structure for independent comparison')
        for key, expr, expected_value, label in probes:
            for sense in (gp.GRB.MINIMIZE, gp.GRB.MAXIMIZE):
                m.setObjective(expr, sense)
                stats = compiled.optimize()
                if stats['status'] != 'OPTIMAL':
                    return dict(result, reason='uncertified metric probe', probe_status=stats['status'])
                if not close(m.ObjVal, expected_value):
                    result[label] += 1
    order = c['objectives']['hierarchical_order'][1:]
    hierarchical_optimum = min((tuple(r['metrics'][k] for k in order) for r in reference.values()), default=None)
    result.update(complete=True, reference_feasible_count=len(reference), reference_objective=oracle['objective_min'], hierarchical_order=order, hierarchical_optimum=hierarchical_optimum, normalization_ranges=oracle['normalization_ranges'])
    return result


def verify_formulation(contract, payload, folder, max_raw=200_000, max_projected=2000):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    report = dict(classification='UNVERIFIED', levels={}, compilation={'status': 'NOT_ATTEMPTED'}, solver={}, placement_audit={}, metrics={}, timings={})
    compiled = None
    try:
        ir = parse_ir(payload)
        report['levels']['1_schema'] = 'PASS'
        report['levels']['2_structure'] = 'PASS'
        c, apps, portfolio = inputs(contract)
        if ir.problem_hash != digest(contract):
            raise ValueError('problem hash mismatch')
        expected = direct_to_ir(contract, folder / 'trusted_recognition')
        faith = fidelity(ir, expected, contract)
        report['levels']['3_fidelity'] = faith
        with restricted_environment(folder / 'compiled') as env:
            compiled = CompiledIR(ir, c['solver'], env)
            report['compilation'] = dict(status='COMPILED', seconds=compiled.compilation_seconds, model_counts=compiled.counts)
            statistics = compiled.optimize()
            report['solver'] = statistics
            compiled.save(folder / 'compiled', statistics)
            if statistics['solution_count']:
                placement = compiled.placement(apps)
                metrics = {k: v.getValue() for k, v in compiled.metrics.items()}
                audit = validate(c, apps[0] if len(apps) == 1 else apps, portfolio, placement, metrics)
                report.update(placement=placement, placement_audit=audit, metrics=metrics)
            report['levels']['4_solution'] = report['placement_audit']
            check = equivalence(compiled, contract, max_raw, max_projected)
            report['levels']['5_equivalence'] = check
            failures = []
            if check['extra_infeasible']: failures.append('UNDERCONSTRAINED')
            if check['missing_feasible']: failures.append('OVERCONSTRAINED')
            if check['metric_mismatches'] or check['objective_mismatches']: failures.append('INCORRECT_OBJECTIVE')
            if faith['missing_mandatory']: failures.append('INVALID_FORMULATION')
            if not failures and faith['errors'] and ir.profile == 'CANONICAL_DIRECT_V1':
                failures.append('INVALID_FORMULATION')
            report['failure_classifications'] = failures
            if failures:
                report['classification'] = failures[0]
            elif check['complete'] and faith['recognized']:
                report['classification'] = 'VALID_FORMULATION'
                if statistics['solution_count'] and c['objectives']['strategy'] == 'WEIGHTED':
                    ref_value = check['reference_objective']
                    if ref_value is not None and not close(statistics['incumbent'], ref_value):
                        report['classification'] = 'VALID_BUT_SUBOPTIMAL_SOLUTION'
                    report['reference_gap'] = None if ref_value is None else (statistics['incumbent'] - ref_value) / max(abs(ref_value), 1e-12)
                if statistics['solution_count'] and c['objectives']['strategy'] == 'HIERARCHICAL':
                    optimum = check['hierarchical_optimum']
                    if optimum is not None and any(not close(report['metrics'][key], value) for key, value in zip(check['hierarchical_order'], optimum)):
                        report['classification'] = 'VALID_BUT_SUBOPTIMAL_SOLUTION'
                if statistics['solution_count'] and not report['placement_audit'].get('valid'):
                    report['classification'] = 'INVALID_FORMULATION'
            report['audit_solver_calls'] = dict(count=len(compiled.history), runtime_seconds=sum(v['runtime_seconds'] for v in compiled.history), maximum_variables=max(v['model_counts']['variables'] for v in compiled.history), maximum_constraints=max(v['model_counts']['linear_constraints'] for v in compiled.history))
            json_write(folder / 'compiled' / 'audit_solves.json', compiled.history)
            compiled.close()
            compiled = None
    except Exception as exc:
        report.update(classification='INVALID_FORMULATION', error_type=type(exc).__name__, error=str(exc))
        if hasattr(exc, 'counts'):
            report['compilation'] = dict(status='LICENSE_SIZE_EXCEEDED', model_counts=exc.counts)
        if '1_schema' not in report['levels']:
            report['levels']['1_schema'] = 'FAIL'
        if 'UNVERIFIED' in str(exc) or 'UNSUPPORTED' in str(exc):
            report['classification'] = 'UNVERIFIED'
    finally:
        if compiled is not None:
            compiled.close()
        report['timings']['validation_total_seconds'] = perf_counter() - started
        json_write(folder / 'validation.json', report)
    return report
