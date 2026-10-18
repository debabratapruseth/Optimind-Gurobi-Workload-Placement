"""Exact direct assignment MILP. No complete-placement enumeration imports.

Public build() supports independent fixed-assignment verification. All nonlinear
metrics have explicit linear equalities/inequalities and binary auxiliaries.
"""
from collections import Counter, defaultdict
from pathlib import Path
from time import perf_counter
import math
import gurobipy as gp
from .feasibility import site_reasons, RESOURCES, RATIOS
from .solver import guard

METRICS=('tco','latency','concentration','blast_radius')

from .errors import UnsupportedDirect


def preprocess(c, apps, portfolio):
    selected={a['id'] for a in apps}
    domains={}; screening={}; pending=False; global_reasons=set()
    for a in apps:
        approval=c['regulatory']['materiality'].get(a['materiality'])
        blocked=approval is None or (approval['approval_required'] and approval['approval_status']=='DENIED')
        conditional=bool(approval and approval['approval_required'] and approval['approval_status'] not in ('APPROVED','DENIED'))
        if approval is None:
            global_reasons.add('MISSING_MATERIALITY_POLICY')
        elif blocked:
            global_reasons.add('APPROVAL_DENIED')
        if conditional:
            global_reasons.add('APPROVAL_PENDING')
        pending |= conditional
        blocked |= conditional and not c['objectives']['infeasibility']['remediation_analysis']
        local=dict(a,dependencies=[d for d in a['dependencies'] if d['target'] not in selected])
        for e in a['environments']:
            domains[a['id'],e]=[]; screening[f'{a["id"]}:{e}']={}
            for s in c['sites']['sites']:
                reasons=site_reasons(c,local,s,e,portfolio)
                cap=c['capacity']['site_overrides'].get(s['id'],c['capacity']['default_residual_per_site'])
                for peak in (False,True):
                    for resource,amount in coefficients(c,a,e,peak).items():
                        if amount>cap[resource]+1e-9:
                            reasons.append(f'UNARY_CAPACITY:{resource}:{"PEAK" if peak else "RESERVED"}')
                if blocked:
                    reasons.append('APPROVAL_NOT_DEPLOYABLE')
                screening[f'{a["id"]}:{e}'][s['id']]=reasons
                if not reasons:
                    domains[a['id'],e].append(s['id'])
    return domains,dict(sites=screening,global_reasons=sorted(global_reasons),capacity_rejections=[]),pending


def coefficients(c, app, environment, peak=False):
    demand=app['peak_demand'] if app['demand_mode']=='VARIABLE' and (peak or c['capacity']['reservation_mode']=='PEAK') else app['demand']
    return {r:demand[r]*(1+(1 if peak else app['dr'][RATIOS[r]]) if environment=='PROD' else 1) for r in RESOURCES}


def upstream(nodes, app_id):
    """Static reachability, including self, cycle-safe. Edges source depends on target."""
    seen=set(); stack=[app_id]
    while stack:
        node=stack.pop()
        if node not in seen:
            seen.add(node)
            stack.extend(d['target'] for d in nodes[node].get('dependencies',[]))
    return seen


def exact_max(m, expressions, upper, name):
    if not expressions:
        return gp.LinExpr(0.0)
    value=m.addVar(lb=0,ub=upper,name=name)
    witness=m.addVars(len(expressions),vtype=gp.GRB.BINARY,name=name+'_witness')
    m.addConstr(gp.quicksum(witness.values())==1,name=name+'_one_witness')
    for j,expression in enumerate(expressions):
        m.addConstr(value>=expression,name=f'{name}_lower[{j}]')
        m.addConstr(value<=expression+upper*(1-witness[j]),name=f'{name}_upper[{j}]')
    return gp.LinExpr(value)


def build(c, apps, portfolio, env, domains=None, include_budget=True):
    """Construct the complete model without solving or enumerating joint choices."""
    if domains is None:
        domains,_,_=preprocess(c,apps,portfolio)
    m=gp.Model('direct_assignment',env=env)
    for param,key in [('TimeLimit','time_limit_seconds'),('MIPGap','relative_mip_gap'),('Threads','threads'),('Seed','seed')]:
        m.setParam(param,c['solver'][key])
    m.Params.FeasibilityTol=1e-9
    m.Params.IntFeasTol=1e-9
    # Exact certification sub-solves below additionally set MIPGap/Abs to zero.
    x=m.addVars([(a['id'],e,s) for a in apps for e in a['environments'] for s in domains[a['id'],e]],vtype=gp.GRB.BINARY,name='x')
    for a in apps:
        for e in a['environments']:
            m.addConstr(gp.quicksum(x[a['id'],e,s] for s in domains[a['id'],e])==1,name=f'complete[{a["id"]},{e}]')
    for site in c['sites']['sites']:
        sid=site['id']; cap=c['capacity']['site_overrides'].get(sid,c['capacity']['default_residual_per_site'])
        for peak in (False,True):
            for r in RESOURCES:
                terms=[coefficients(c,a,e,peak)[r]*x[a['id'],e,sid] for a in apps for e in a['environments'] if (a['id'],e,sid) in x]
                m.addConstr(gp.quicksum(terms)<=cap[r],name=f'{"peak" if peak else "reserved"}[{sid},{r}]')
    occupied={}
    for site in c['sites']['sites']:
        sid=site['id']; used=[v for (a,e,s),v in x.items() if s==sid]
        if used:
            z=m.addVar(vtype=gp.GRB.BINARY,name=f'occupied[{sid}]'); occupied[sid]=z
            for i,v in enumerate(used):
                m.addConstr(z>=v,name=f'occupied_lower[{sid},{i}]')
            m.addConstr(z<=gp.quicksum(used),name=f'occupied_upper[{sid}]')
    cost=c['cost']; horizon=cost['horizon_months']
    tco=horizon*(gp.quicksum(coefficients(c,a,e)['cpu_vcpu']*cost['per_vcpu_monthly'][s]*x[a['id'],e,s] for a in apps for e in a['environments'] for s in domains[a['id'],e])+gp.quicksum(cost['per_site_monthly_fixed'][s]*z for s,z in occupied.items())+len(apps)*(cost['license_monthly_per_application']+cost['operations_monthly_per_application']))
    budget=None
    if include_budget and cost['budget']['enabled']:
        budget=m.addConstr(tco<=cost['budget']['max_total_tco_usd'],name='hard_budget')
    # One exact latency expression per direct edge/source environment. A transport
    # table y has row/column marginals x and therefore equals x_source*x_target.
    selected={a['id'] for a in apps}; fixed={a['id']:a for a in portfolio}
    edge_values=[]; max_latency=0.0
    matrix=c['dependencies']['latency_matrix_ms']
    for a in apps:
        for e in a['environments']:
            for di,dep in enumerate(a['dependencies']):
                aid=a['id']; target=dep['target']; terms=[]
                if target in selected:
                    y={}
                    for s in domains[aid,e]:
                        for t in domains[target,'PROD']:
                            latency=matrix.get(s,{}).get(t)
                            if latency is None or latency>dep['max_p95_latency_ms']:
                                m.addConstr(x[aid,e,s]+x[target,'PROD',t]<=1,name=f'latency_forbidden[{aid},{e},{di},{s},{t}]')
                            else:
                                pair=m.addVar(lb=0,ub=1,name=f'edge_pair[{aid},{e},{di},{s},{t}]')
                                y[s,t]=pair;terms.append(latency*pair);max_latency=max(max_latency,latency)
                    for s in domains[aid,e]:
                        m.addConstr(gp.quicksum(v for (ss,t),v in y.items() if ss==s)==x[aid,e,s],name=f'edge_row[{aid},{e},{di},{s}]')
                    for t in domains[target,'PROD']:
                        m.addConstr(gp.quicksum(v for (s,tt),v in y.items() if tt==t)==x[target,'PROD',t],name=f'edge_col[{aid},{e},{di},{t}]')
                else:
                    for s in domains[aid,e]:
                        latency=matrix[s][fixed[target]['site_id']]
                        terms.append(latency*x[aid,e,s]);max_latency=max(max_latency,latency)
                edge_values.append(gp.quicksum(terms))
    latency=exact_max(m,edge_values,max_latency,'max_latency')
    sites={s['id']:s for s in c['sites']['sites']}
    nodes={a['id']:a for a in portfolio+apps}
    critical=[a for a in portfolio+apps if a['criticality']=='CRITICAL']
    newcritical=[a for a in apps if a['criticality']=='CRITICAL']; N=max(1,len(critical))
    # Exact count-square via one-hot encoding: no quadratic expressions.
    concentration=gp.LinExpr()
    for dimension in ('provider','country'):
        groups=sorted({s[dimension] for s in sites.values()})
        for group in groups:
            baseline=sum(a['criticality']=='CRITICAL' and sites[a['site_id']][dimension]==group for a in portfolio)
            terms=[x[a['id'],'PROD',s] for a in newcritical for s in domains[a['id'],'PROD'] if sites[s][dimension]==group]
            eligible=sum(any(sites[s][dimension]==group for s in domains[a['id'],'PROD']) for a in newcritical)
            if not terms:
                concentration+=baseline**2/(2*N*N)
                continue
            z=m.addVars(eligible+1,vtype=gp.GRB.BINARY,name=f'count[{dimension},{group}]')
            m.addConstr(gp.quicksum(z.values())==1,name=f'count_one[{dimension},{group}]')
            m.addConstr(gp.quicksum(k*z[k] for k in z)==gp.quicksum(terms),name=f'count_link[{dimension},{group}]')
            concentration+=gp.quicksum((baseline+k)**2/(2*N*N)*z[k] for k in z)
    scenario_counts=[]; infrastructure={}; disruption={}
    for scenario in c['dependencies']['failure_scenarios']:
        fid=scenario['id']; exposed=[]; affected=[]
        for a in critical:
            ancestors=upstream(nodes,a['id'])
            if scenario['type']=='SHARED_SERVICE':
                term=float(scenario['application_id'] in ancestors)
            else:
                sid=scenario['site_id']
                exposed.append(float(a.get('site_id')==sid) if a['id'] in fixed else x.get((a['id'],'PROD',sid),0.0))
                certain=any(k in fixed and fixed[k]['site_id']==sid for k in ancestors)
                causes=[x[k,'PROD',sid] for k in sorted(ancestors) if (k,'PROD',sid) in x]
                if certain:
                    term=1.0
                elif not causes:
                    term=0.0
                else:
                    term=m.addVar(vtype=gp.GRB.BINARY,name=f'disrupted[{fid},{a["id"]}]')
                    for i,cause in enumerate(causes):
                        m.addConstr(term>=cause,name=f'failure_lower[{fid},{a["id"]},{i}]')
                    m.addConstr(term<=gp.quicksum(causes),name=f'failure_upper[{fid},{a["id"]}]')
            affected.append(term)
        infrastructure[fid]=gp.quicksum(exposed)
        disruption[fid]=gp.quicksum(affected)
        scenario_counts.append(disruption[fid])
    blast=exact_max(m,scenario_counts,len(critical),'worst_disruption')/N
    metrics=dict(tco=gp.LinExpr(tco),latency=latency,concentration=concentration,blast_radius=blast)
    m.update()
    return dict(model=m,x=x,metrics=metrics,domains=domains,budget=budget,infrastructure=infrastructure,disruption=disruption,critical_count=N)


def extract(problem, apps):
    x=problem['x']; parts={}
    for a in apps:
        envs={e:next(s for s in problem['domains'][a['id'],e] if x[a['id'],e,s].X>.5) for e in a['environments']}
        parts[a['id']]=dict(application_id=a['id'],environments=envs,dr_site_id=envs['PROD'],failure_domain_contract='INDEPENDENT_LOCAL_DOMAINS')
    return next(iter(parts.values())) if len(apps)==1 else dict(applications=parts)


def certified_value(problem, key, c):
    """Evaluate attained discrete values, removing solver integrality roundoff.

    This does not change metric definitions or substitute approximate bounds.
    Range solves still require OPTIMAL with zero relative and absolute MIP gaps.
    """
    expression=problem['metrics'][key]; n=problem['critical_count']
    if key in ('tco','concentration'):
        value=math.fsum([expression.getConstant()]+[expression.getCoeff(i)*round(expression.getVar(i).X) for i in range(expression.size())])
        return round(value*2*n*n)/(2*n*n) if key=='concentration' else value
    value=expression.getValue()
    if key=='blast_radius':
        return round(value*n)/n
    levels={0.0}|{v for row in c['dependencies']['latency_matrix_ms'].values() for v in row.values()}
    return min(levels,key=lambda v:abs(v-value))


def solve_direct(c, apps, portfolio, folder):
    """Exact range solves and strategy solve; returns placements, never candidate input."""
    folder=Path(folder); start=perf_counter()
    domains,screening,pending=preprocess(c,apps,portfolio)
    timings=dict(feasibility_preprocessing=perf_counter()-start,candidate_enumeration=0.0,model_construction=0.0,gurobi_optimization=0.0)
    cfg=c['solver']; log=folder/'solver.log'; calls=[]
    with gp.Env(empty=True) as env:
        env.setParam('LogFile',str(log));env.start()
        if 'Restricted license - for non-production use only' not in log.read_text():
            raise RuntimeError('FREE_LICENSE_NOT_VERIFIED')
        started=perf_counter(); problem=build(c,apps,portfolio,env,domains)
        m=problem['model']; metrics=problem['metrics']
        try:
            m.write(str(folder/'direct_model.lp'))
            counts=guard(m,cfg)
            timings['model_construction']+=perf_counter()-started
            def optimize(label):
                counts_now=guard(m,cfg)
                begun=perf_counter();m.optimize();wall=perf_counter()-begun
                timings['gurobi_optimization']+=wall
                calls.append(dict(stage=label,status_code=m.Status,runtime_seconds=m.Runtime,wall_seconds=wall,model_counts=counts_now))
                return m.Status
            result=dict(status=None,selected_index=None,solution_count=0,model_counts=counts,
                        incumbent=None,best_bound=None,mip_gap=None,optimality_proven=False,
                        license='FREE_SIZE_LIMITED',license_verified_from_startup_log=True,
                        objective_strategy=c['objectives']['strategy'],formulation_method='DIRECT_ASSIGNMENT_MILP',
                        stage='CONDITIONAL_ANALYSIS' if pending and c['objectives']['infeasibility']['remediation_analysis'] else 'STRICT',
                        timings=timings,solve_calls=calls)
            # Preserve enumeration's prebudget normalization domain exactly. The
            # complete budget constraint remains in the model; only its RHS is
            # temporarily made unbounded for these explicitly labelled sub-solves.
            if problem['budget'] is not None:
                problem['budget'].RHS=gp.GRB.INFINITY
            m.Params.MIPGap=0; m.Params.MIPGapAbs=0
            ranges={}
            for key in METRICS:
                values=[]
                for sense,label in [(gp.GRB.MINIMIZE,'min'),(gp.GRB.MAXIMIZE,'max')]:
                    m.setObjective(metrics[key],sense)
                    status=optimize(f'normalization_{key}_{label}')
                    if status==gp.GRB.INFEASIBLE:
                        result.update(status='INFEASIBLE',runtime_seconds=sum(v['runtime_seconds'] for v in calls))
                        m.computeIIS();m.write(str(folder/'infeasible.ilp'))
                        return result,screening,[]
                    if status!=gp.GRB.OPTIMAL:
                        raise UnsupportedDirect(f'NORMALIZATION_NOT_CERTIFIED:{key}:{label}:status={status}')
                    values.append(certified_value(problem,key,c))
                lo,hi=values
                if hi<lo or 0<hi-lo<1e-8:
                    raise UnsupportedDirect(f'NORMALIZATION_NUMERIC_RANGE_UNSUPPORTED:{key}:{lo}:{hi}')
                ranges[key]=(lo,hi)
            if problem['budget'] is not None:
                problem['budget'].RHS=c['cost']['budget']['max_total_tco_usd']
            normalized={k:(metrics[k]-lo)/(hi-lo) if hi>lo else gp.LinExpr(0.0) for k,(lo,hi) in ranges.items()}
            weights=c['objectives']['weights']; score=gp.quicksum(weights[k]*normalized[k] for k in METRICS)/sum(weights.values())
            result['normalization']=dict(ranges=ranges,weights=weights,method='certified_direct_MILP_extrema_prebudget')
            strategy=c['objectives']['strategy']; found=[]
            m.Params.MIPGap=0 if c['objectives']['strategy']=='PARETO' else cfg['relative_mip_gap']
            if strategy=='HIERARCHICAL':
                m.ModelSense=gp.GRB.MINIMIZE
                for j,k in enumerate(c['objectives']['hierarchical_order'][1:]):
                    m.setObjectiveN(metrics[k],j,priority=4-j,abstol=0,reltol=0,name=k)
            else:
                m.setObjective(score,gp.GRB.MINIMIZE)
            m.write(str(folder/'direct_model.lp'))
            status=optimize('primary')
            names={getattr(gp.GRB,n):n for n in ('OPTIMAL','INFEASIBLE','TIME_LIMIT','SUBOPTIMAL','INTERRUPTED','NUMERIC','INF_OR_UNBD','UNBOUNDED')}
            result.update(status=names.get(status,str(status)),solution_count=m.SolCount,optimality_proven=status==gp.GRB.OPTIMAL)
            if strategy!='HIERARCHICAL':
                if status not in (gp.GRB.INFEASIBLE,gp.GRB.INF_OR_UNBD):
                    result['best_bound']=m.ObjBound if math.isfinite(m.ObjBound) else None
                if m.SolCount:
                    result.update(incumbent=m.ObjVal,mip_gap=m.MIPGap if math.isfinite(m.MIPGap) else None)
            elif m.SolCount:
                result['hierarchical_values']={k:expr.getValue() for k,expr in metrics.items()}
                result['incumbent']=m.ObjVal
            if m.SolCount:
                found=[dict(placement=extract(problem,apps),metrics={k:expr.getValue() for k,expr in metrics.items()})]
            if strategy=='PARETO' and m.SolCount:
                found=pareto_solve(c,apps,problem,score,normalized,ranges,optimize,status)
                result['pareto_scope']='Up to max_candidates distinct nondominated metric vectors, weighted order; no entire frontier guarantee'
            if status==gp.GRB.INFEASIBLE:
                m.computeIIS();m.write(str(folder/'infeasible.ilp'))
            if found:
                for row in found:
                    row['placement']['approval_pending']=pending
                result['selected_index']=0
            result['model_counts']=guard(m,cfg)
            result['maximum_model_counts']={key:max(call['model_counts'][key] for call in calls) for key in counts}
            m.write(str(folder/'direct_model_final.lp'))
            result['runtime_seconds']=sum(v['runtime_seconds'] for v in calls)
            return result,screening,found
        except UnsupportedDirect as exc:
            exc.details=dict(status='UNSUPPORTED',reason=str(exc),model_counts=guard(m,cfg),solve_calls=calls,timings=timings)
            raise
        finally:
            m.dispose()


def pareto_solve(c, apps, problem, score, normalized, ranges, optimize, initial_status):
    """Epsilon/dominance cuts on explicit metric lattices; no placement enumeration."""
    m=problem['model']; metrics=problem['metrics']
    # Finite lattice needed for strict dominance with linear inequalities. Exact
    # cent-valued cost and millisecond-thousandth latency only, otherwise reject.
    for i in range(metrics['tco'].size()):
        coef=metrics['tco'].getCoeff(i)
        if abs(coef*100-round(coef*100))>1e-6:
            raise UnsupportedDirect('PARETO_UNSUPPORTED: TCO coefficients must be exact cents')
    if abs(metrics['tco'].getConstant()*100-round(metrics['tco'].getConstant()*100))>1e-6:
        raise UnsupportedDirect('PARETO_UNSUPPORTED: TCO constant must be exact cents')
    matrix=c['dependencies']['latency_matrix_ms']
    if any(abs(v*1000-round(v*1000))>1e-6 for row in matrix.values() for v in row.values()):
        raise UnsupportedDirect('PARETO_UNSUPPORTED: latency requires 0.001 ms lattice')
    N=problem['critical_count']
    steps=dict(tco=.01,latency=.001,concentration=1/(2*N*N),blast_radius=1/N)
    if min(steps.values())<=100*m.Params.FeasibilityTol:
        raise UnsupportedDirect('PARETO_UNSUPPORTED: metric lattice too fine for certified strict dominance cuts')
    found=[]; status=initial_status
    m.Params.MIPGap=0;m.Params.MIPGapAbs=0
    for iteration in range(c['objectives']['pareto']['max_candidates']):
        if iteration:
            m.setObjective(score,gp.GRB.MINIMIZE);status=optimize(f'pareto_{iteration}_weighted')
        if status==gp.GRB.INFEASIBLE:
            break
        if status!=gp.GRB.OPTIMAL:
            raise UnsupportedDirect('PARETO_NOT_CERTIFIED: all stages require optimality')
        # Lexicographic tie-break with every varying metric positive prevents weakly
        # dominated points when a configured WEIGHTED coefficient is zero.
        best=score.getValue();hold=m.addConstr(score<=best+1e-9,name=f'pareto_score_hold[{iteration}]')
        m.setObjective(gp.quicksum(normalized.values()),gp.GRB.MINIMIZE)
        if optimize(f'pareto_{iteration}_nondominance')!=gp.GRB.OPTIMAL:
            raise UnsupportedDirect('PARETO_NOT_CERTIFIED: tie break')
        values={k:expr.getValue() for k,expr in metrics.items()}
        found.append(dict(placement=extract(problem,apps),metrics=values))
        m.remove(hold);m.update()
        if iteration+1==c['objectives']['pareto']['max_candidates']:
            break
        varying=[k for k,(lo,hi) in ranges.items() if hi>lo]
        improve=m.addVars(varying,vtype=gp.GRB.BINARY,name=f'pareto_improve[{iteration}]')
        m.addConstr(gp.quicksum(improve.values())>=1,name=f'pareto_exclude_dominated[{iteration}]')
        for k in varying:
            lo,hi=ranges[k];step=steps[k]
            value=round(values[k]/step)*step
            m.addConstr(metrics[k]<=value-step+(hi-lo+step)*(1-improve[k]),name=f'pareto_improvement[{iteration},{k}]')
    return found
