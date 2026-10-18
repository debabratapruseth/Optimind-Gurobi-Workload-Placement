"""Trusted translation of validated declarative algebra, never a banking repairer."""
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
import math
import gurobipy as gp
from .formulation_ir import parse_ir
from .solver import guard
from .persistence import json_write

_VERIFIED_ENVIRONMENTS = set()


@contextmanager
def restricted_environment(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / 'solver.log'
    # A fresh log is required: stale restricted banners cannot authorize a license.
    if log.exists():
        raise ValueError('solver output directory must have no existing solver.log')
    with gp.Env(empty=True) as env:
        env.setParam('LogFile', str(log))
        env.start()
        if not log.exists() or 'Restricted license - for non-production use only' not in log.read_text():
            raise RuntimeError('FREE_LICENSE_NOT_VERIFIED')
        env.setParam('OutputFlag', 0)
        _VERIFIED_ENVIRONMENTS.add(id(env))
        try:
            yield env
        finally:
            _VERIFIED_ENVIRONMENTS.discard(id(env))


def expression(expr, variables):
    return gp.LinExpr(list(expr.terms.values()), [variables[k] for k in expr.terms]) + expr.constant


class CompiledIR:
    def __init__(self, payload, solver, env):
        started = perf_counter()
        if id(env) not in _VERIFIED_ENVIRONMENTS:
            raise ValueError('compiler requires an active verified restricted environment')
        self.ir = parse_ir(payload)
        self.solver = solver
        self.history = []
        self.model = gp.Model('structured_ir', env=env)
        m = self.model
        try:
            for param, key in [('TimeLimit', 'time_limit_seconds'), ('MIPGap', 'relative_mip_gap'), ('Threads', 'threads'), ('Seed', 'seed')]:
                m.setParam(param, solver[key])
            m.Params.FeasibilityTol = 1e-9
            m.Params.IntFeasTol = 1e-9
            kinds = {'BINARY': gp.GRB.BINARY, 'INTEGER': gp.GRB.INTEGER, 'CONTINUOUS': gp.GRB.CONTINUOUS}
            self.variables = {v.id: m.addVar(lb=v.lower, ub=v.upper, vtype=kinds[v.kind], name=v.id) for v in self.ir.variables}
            for row in self.ir.constraints:
                lhs = expression(row.expression, self.variables)
                relation = lhs <= row.rhs if row.sense == 'LE' else lhs >= row.rhs if row.sense == 'GE' else lhs == row.rhs
                m.addConstr(relation, name=row.id)
            self.metrics = {k: expression(e, self.variables) for k, e in self.ir.metrics.items()}
            m.ModelSense = gp.GRB.MINIMIZE if self.ir.objective_sense == 'MIN' else gp.GRB.MAXIMIZE
            if len(self.ir.objectives) == 1:
                o = self.ir.objectives[0]
                m.setObjective(o.weight * expression(o.expression, self.variables), m.ModelSense)
            else:
                for i, o in enumerate(self.ir.objectives):
                    m.setObjectiveN(expression(o.expression, self.variables), i, priority=o.priority, weight=o.weight, abstol=0, reltol=0, name=o.id)
            self.counts = guard(m, solver)
            self.compilation_seconds = perf_counter() - started
        except BaseException:
            m.dispose()
            raise

    def optimize(self):
        counts = guard(self.model, self.solver)  # every call, including audit probes
        self.model.optimize()
        m = self.model
        finite = lambda value: value if math.isfinite(value) else None
        names = {getattr(gp.GRB, k): k for k in ('OPTIMAL', 'INFEASIBLE', 'INF_OR_UNBD', 'UNBOUNDED', 'TIME_LIMIT', 'SUBOPTIMAL', 'INTERRUPTED', 'NUMERIC')}
        scalar = m.NumObj == 1
        result = dict(status=names.get(m.Status, str(m.Status)), status_code=m.Status, license='FREE_SIZE_LIMITED', license_verified_from_startup_log=True,
                    solution_count=m.SolCount, incumbent=finite(m.ObjVal) if m.SolCount else None,
                    best_bound=finite(m.ObjBound) if scalar and m.Status not in (gp.GRB.INFEASIBLE, gp.GRB.INF_OR_UNBD) else None,
                    mip_gap=finite(m.MIPGap) if scalar and m.IsMIP and m.SolCount else None,
                    runtime_seconds=m.Runtime, model_counts=counts,
                    optimality_proven=m.Status == gp.GRB.OPTIMAL)
        self.history.append(dict(result))
        return result

    def placement(self, apps):
        parts = {a['id']: dict(application_id=a['id'], environments={}, failure_domain_contract='INDEPENDENT_LOCAL_DOMAINS') for a in apps}
        for v in self.ir.variables:
            if v.assignment and self.variables[v.id].X > .5:
                d = v.assignment
                if d.application not in parts or d.environment in parts[d.application]['environments']:
                    raise ValueError('invalid/duplicate extracted assignment')
                parts[d.application]['environments'][d.environment] = d.site
        for p in parts.values():
            p['dr_site_id'] = p['environments'].get('PROD')
        return next(iter(parts.values())) if len(apps) == 1 else dict(applications=parts)

    def save(self, folder, statistics):
        self.model.write(str(Path(folder) / 'compiled.lp'))
        if self.model.Status == gp.GRB.INFEASIBLE:
            self.model.computeIIS()
            self.model.write(str(Path(folder) / 'infeasible.ilp'))
        json_write(Path(folder) / 'solver.json', statistics)

    def close(self):
        self.model.dispose()
