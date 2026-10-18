"""Trusted demonstration converter. Never supplied as an AI prompt template.

Exports full algebra, not source code; normalization uses guarded bound solves.
The compiler itself never imports this module or inserts missing constraints.
"""
from collections import defaultdict
import gurobipy as gp
from .direct import build, METRICS, certified_value
from .problem_contract import digest, inputs, canonical_bytes, REQUIREMENT_IDS
from .formulation_ir import parse_ir
from .ir_compiler import restricted_environment
from .solver import guard

REQUIREMENTS = REQUIREMENT_IDS
DOMAIN_REQUIREMENTS = ('regulatory', 'services', 'recovery_resilience', 'approvals')


def family(name):
    if name.startswith('complete['): return 'placement'
    if name.startswith(('reserved[', 'peak[')): return 'capacity'
    if name.startswith('occupied'): return 'tco'
    if name.startswith(('edge_', 'latency_', 'max_latency')): return 'dependency_latency'
    if name.startswith('count'): return 'concentration'
    if name.startswith(('failure_', 'worst_disruption')): return 'blast_radius'
    if name == 'hard_budget': return 'budget'
    raise ValueError('unrecognized trusted constraint family: ' + name)


def export_expression(expr):
    terms = defaultdict(float)
    for i in range(expr.size()):
        terms[expr.getVar(i).VarName] += expr.getCoeff(i)
    return dict(constant=expr.getConstant(), terms={k: v for k, v in sorted(terms.items()) if v})


def direct_to_ir(contract, folder):
    c, apps, portfolio = inputs(contract)
    if c['objectives']['strategy'] == 'PARETO':
        raise ValueError('UNSUPPORTED: Phase 2A conversion has no finite Pareto orchestration')
    with restricted_environment(folder) as env:
        p = build(c, apps, portfolio, env)
        m = p['model']
        try:
            guard(m, c['solver'])
            ranges = {}
            budget = p['budget']
            if budget is not None:
                budget.RHS = gp.GRB.INFINITY
            m.Params.MIPGap = 0
            m.Params.MIPGapAbs = 0
            for key in METRICS:
                extrema = []
                for sense in (gp.GRB.MINIMIZE, gp.GRB.MAXIMIZE):
                    m.setObjective(p['metrics'][key], sense)
                    guard(m, c['solver'])
                    m.optimize()
                    if m.Status == gp.GRB.INFEASIBLE:
                        extrema = [0., 0.]
                        break
                    if m.Status != gp.GRB.OPTIMAL:
                        raise ValueError('UNVERIFIED: normalization not certified')
                    extrema.append(certified_value(p, key, c))
                ranges[key] = extrema
            if budget is not None:
                budget.RHS = c['cost']['budget']['max_total_tco_usd']
            m.update()
            assignments = {v.VarName: dict(application=a, environment=e, site=s) for (a, e, s), v in p['x'].items()}
            variables = [dict(id=v.VarName, kind={'B': 'BINARY', 'I': 'INTEGER', 'C': 'CONTINUOUS'}[v.VType], lower=v.LB, upper=v.UB, assignment=assignments.get(v.VarName)) for v in m.getVars()]
            constraints = [dict(id=r.ConstrName, family=family(r.ConstrName), expression=export_expression(m.getRow(r)), sense={'<': 'LE', '>': 'GE', '=': 'EQ'}[r.Sense], rhs=r.RHS) for r in m.getConstrs()]
            metrics = {k: export_expression(v) for k, v in p['metrics'].items()}
            if c['objectives']['strategy'] == 'HIERARCHICAL':
                objectives = [dict(id=k, expression=metrics[k], priority=4-i, weight=1.) for i, k in enumerate(c['objectives']['hierarchical_order'][1:])]
            else:
                score = gp.LinExpr()
                weights = c['objectives']['weights']
                for k, (lo, hi) in ranges.items():
                    if 0 < hi-lo < 1e-8:
                        raise ValueError('UNVERIFIED: numerically unsupported normalization range')
                    if hi > lo:
                        score += weights[k] / sum(weights.values()) * (p['metrics'][k] - lo) / (hi-lo)
                objectives = [dict(id='weighted', expression=export_expression(score), priority=0, weight=1.)]
            manifest = []
            for req in REQUIREMENTS:
                rows = [r['id'] for r in constraints if r['family'] == req or req == 'dr' and r['family'] == 'capacity']
                refs = sorted({v for r in constraints if r['id'] in rows for v in r['expression']['terms']})
                if req in DOMAIN_REQUIREMENTS or req == 'placement':
                    refs = sorted(assignments)
                metric_refs = [req] if req in metrics else ['latency'] if req == 'dependency_latency' else []
                manifest.append(dict(requirement=req, status='NOT_APPLICABLE' if req == 'budget' and budget is None else 'REPRESENTED', variables=refs, constraints=rows, objectives=[o['id'] for o in objectives] if req == 'objective' else [], metrics=metric_refs))
            return parse_ir(canonical_bytes(dict(ir_version='1.0', problem_hash=digest(contract), profile='CANONICAL_DIRECT_V1', variables=variables, constraints=constraints, metrics=metrics, objectives=objectives, objective_sense='MIN', manifest=manifest)))
        finally:
            m.dispose()
