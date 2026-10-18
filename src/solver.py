"""Hand-authored finite-assignment MILP for one or several new applications.

Each binary chooses a complete screened assignment. This is an exact extended
formulation for the Phase 1 finite domain, not a heuristic. Capacity and budget
are also explicit linear constraints. All complete model counts precede solve.
"""
from pathlib import Path
import math
from time import perf_counter
from .feasibility import loads, RESOURCES
from .metrics import METRICS, normalized_scores

class LicenseSizeExceeded(RuntimeError):
    def __init__(self,counts):
        self.counts=counts
        super().__init__(f'LICENSE_SIZE_EXCEEDED: {counts}')

def guard(model, config):
    model.update()
    counts=dict(variables=model.NumVars,linear_constraints=model.NumConstrs,
                quadratic_constraints=model.NumQConstrs,quadratic_objective_terms=model.NumQNZs,
                general_constraints=model.NumGenConstrs,sos_constraints=model.NumSOS)
    if any(counts[k] for k in ('quadratic_constraints','quadratic_objective_terms','general_constraints','sos_constraints')):
        raise ValueError('ONLY_LINEAR_MILP_ALLOWED')
    if model.NumPWLObjVars:
        raise ValueError('ONLY_LINEAR_MILP_ALLOWED: piecewise-linear objective requires an explicit counted formulation')
    if counts['variables']>min(1800,config['safety_limits']['max_variables'],config['hard_limits']['max_variables']) or counts['linear_constraints']>min(1800,config['safety_limits']['max_linear_constraints'],config['hard_limits']['max_linear_constraints']):
        raise LicenseSizeExceeded(counts)
    return counts

def solve(c, app, candidates, metrics, folder):
    import gurobipy as gp
    folder=Path(folder)
    log=folder/'solver.log'
    # Env owns the log from startup so the license evidence is preserved.
    with gp.Env(empty=True) as env:
        env.setParam('LogFile',str(log))
        env.start()
        if 'Restricted license - for non-production use only' not in log.read_text():
            raise RuntimeError('FREE_LICENSE_NOT_VERIFIED: restricted-license startup evidence required')
        with gp.Model('reference_joint_applications' if isinstance(app,list) else 'reference_single_application',env=env) as model:
            construction_start=perf_counter()
            cfg=c['solver']
            for param,key in [('TimeLimit','time_limit_seconds'),('MIPGap','relative_mip_gap'),('Threads','threads'),('Seed','seed')]:
                model.setParam(param,cfg[key])
            x=model.addVars(len(candidates),vtype=gp.GRB.BINARY,name='assignment')
            model.addConstr(gp.quicksum(x.values())==1,name='select_exactly_one')
            reservations=[loads(c,app,p) for p in candidates]
            peaks=[loads(c,app,p,True) for p in candidates]
            for site in c['sites']['sites']:
                sid=site['id']; cap=c['capacity']['site_overrides'].get(sid,c['capacity']['default_residual_per_site'])
                for resource in RESOURCES:
                    for kind,values in [('reservation',reservations),('simultaneous_peak',peaks)]:
                        model.addConstr(gp.quicksum(values[i].get(sid,{}).get(resource,0)*x[i] for i in x)<=cap[resource],name=f'{kind}_{sid}_{resource}')
            if c['cost']['budget']['enabled']:
                model.addConstr(gp.quicksum(metrics[i]['tco']*x[i] for i in x)<=c['cost']['budget']['max_total_tco_usd'],name='hard_budget')
            scores,normalization=normalized_scores(c,metrics)
            strategy=c['objectives']['strategy']
            if strategy=='HIERARCHICAL':
                order=c['objectives']['hierarchical_order'][1:]
                for index,key in enumerate(order):
                    model.setObjectiveN(gp.quicksum(metrics[i][key]*x[i] for i in x),index,priority=len(order)-index,abstol=0,reltol=0,name=key)
            else:
                model.setObjective(gp.quicksum(scores[i]*x[i] for i in x),gp.GRB.MINIMIZE)
            model.update()
            model.write(str(folder/'reference_model.lp'))
            counts=guard(model,cfg)
            construction_seconds=perf_counter()-construction_start
            optimize_start=perf_counter()
            model.optimize()
            optimization_seconds=perf_counter()-optimize_start
            names={getattr(gp.GRB,n):n for n in ('LOADED','OPTIMAL','INFEASIBLE','INF_OR_UNBD','UNBOUNDED','CUTOFF','ITERATION_LIMIT','NODE_LIMIT','TIME_LIMIT','SOLUTION_LIMIT','INTERRUPTED','NUMERIC','SUBOPTIMAL','INPROGRESS','USER_OBJ_LIMIT','WORK_LIMIT','MEM_LIMIT') if hasattr(gp.GRB,n)}
            result=dict(status=names.get(model.Status,str(model.Status)),status_code=model.Status,
                        runtime_seconds=model.Runtime,solution_count=model.SolCount,model_counts=counts,
                        license='FREE_SIZE_LIMITED',license_verified_from_startup_log=True,
                        objective_strategy=strategy,normalization=normalization,
                        incumbent=None,best_bound=None,mip_gap=None,selected_index=None,
                        optimality_proven=model.Status==gp.GRB.OPTIMAL,
                        optimality_scope='Gurobi status under configured numerical and MIP tolerances')
            result['timings']=dict(model_construction=construction_seconds,gurobi_optimization=optimization_seconds)
            if strategy!='HIERARCHICAL' and model.Status not in (gp.GRB.INFEASIBLE,gp.GRB.INF_OR_UNBD):
                result['best_bound']=model.ObjBound if math.isfinite(model.ObjBound) else None
            if model.SolCount:
                result['selected_index']=next(i for i in x if x[i].X>0.5)
                result['incumbent']=model.ObjVal
                # Multiobjective bounds are not a single global scalar certificate.
                if strategy!='HIERARCHICAL':
                    result['best_bound']=model.ObjBound if math.isfinite(model.ObjBound) else None
                    result['mip_gap']=model.MIPGap if math.isfinite(model.MIPGap) else None
                else:
                    result['hierarchical_values']={}
                    for j,key in enumerate(c['objectives']['hierarchical_order'][1:]):
                        model.Params.ObjNumber=j
                        result['hierarchical_values'][key]=model.ObjNVal
            if strategy=='PARETO' and model.SolCount:
                feasible=[i for i in x if not c['cost']['budget']['enabled'] or metrics[i]['tco']<=c['cost']['budget']['max_total_tco_usd']]
                nondominated=[i for i in feasible if not any(all(metrics[j][k]<=metrics[i][k] for k in METRICS) and any(metrics[j][k]<metrics[i][k] for k in METRICS) for j in feasible)]
                result['pareto_indices']=sorted(nondominated,key=lambda i:(scores[i],i))[:c['objectives']['pareto']['max_candidates']]
                result['pareto_scope']='Finite screened complete assignments; no continuous frontier claim'
            if model.Status==gp.GRB.INFEASIBLE:
                model.computeIIS()
                model.write(str(folder/'infeasible.ilp'))
            return result
