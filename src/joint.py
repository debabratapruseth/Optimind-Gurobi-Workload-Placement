"""Small joint-instance extension of the existing complete-assignment formulation.

No sequential optimization: all selected apps share one assignment binary and
one residual capacity system. New dependency targets refer to their PROD site,
consistent with the application-level fixed-target contract of Phase 1.
"""
from collections import Counter
from itertools import product
from time import perf_counter
from .feasibility import enumerate_candidates, site_reasons, loads, RESOURCES
from .metrics import measure


def aggregate_loads(c, apps, placement, peak=False):
    totals={}
    for app in apps:
        for sid,values in loads(c,app,placement['applications'][app['id']],peak).items():
            totals.setdefault(sid,dict.fromkeys(RESOURCES,0.0))
            for resource,amount in values.items():
                totals[sid][resource]+=amount
    return totals


def enumerate_joint(c, apps, portfolio, timings=None):
    ids={a['id'] for a in apps}
    options=[]; screening={}; rejected=[]
    for app in apps:
        # Only defer unresolved NEW-target latency. It is checked for every
        # complete joint assignment below; fixed-target checks stay in place.
        local=dict(app,dependencies=[d for d in app['dependencies'] if d['target'] not in ids])
        candidates,reasons=enumerate_candidates(c,local,portfolio,timings)
        options.append(candidates); screening[app['id']]=reasons
    sites={s['id']:s for s in c['sites']['sites']}
    accepted=[]
    started=perf_counter()
    for choices in product(*options):
        assignment=dict(applications={a['id']:p for a,p in zip(apps,choices)},
                        approval_pending=any(p['approval_pending'] for p in choices))
        targets=portfolio+[dict(a,site_id=assignment['applications'][a['id']]['environments']['PROD']) for a in apps]
        reasons=[]
        for app in apps:
            p=assignment['applications'][app['id']]
            for env,sid in p['environments'].items():
                reasons.extend(f'{app["id"]}:{env}:{r}' for r in site_reasons(c,app,sites[sid],env,targets))
        for peak in (False,True):
            for sid,values in aggregate_loads(c,apps,assignment,peak).items():
                cap=c['capacity']['site_overrides'].get(sid,c['capacity']['default_residual_per_site'])
                for r,v in values.items():
                    if v>cap[r]+1e-9:
                        reasons.append(f'JOINT_CAPACITY:{sid}:{r}:{"PEAK" if peak else "RESERVED"}')
        if reasons:
            rejected.append(dict(placement=assignment,reasons=sorted(set(reasons))))
        else:
            accepted.append(assignment)
    if timings is not None:
        timings['candidate_enumeration']+=perf_counter()-started
    return accepted,dict(applications=screening,
                         sites={f'{a}:{e}':v for a,s in screening.items() for e,v in s['sites'].items()},
                         global_reasons=sorted({r for s in screening.values() for r in s['global_reasons']}),
                         capacity_rejections=rejected,
                         individual_candidate_counts=[len(o) for o in options])


def measure_joint(c, apps, portfolio, placement):
    nodes=[dict(a,site_id=placement['applications'][a['id']]['environments']['PROD']) for a in apps]
    parts=[measure(c,a,portfolio+[n for n in nodes if n['id']!=a['id']],placement['applications'][a['id']]) for a in apps]
    occupied=Counter(sid for a in apps for sid in set(placement['applications'][a['id']]['environments'].values()))
    duplicate_fixed=sum((count-1)*c['cost']['per_site_monthly_fixed'][sid]*c['cost']['horizon_months'] for sid,count in occupied.items())
    breakdown={k:sum(p['tco_breakdown'][k] for p in parts) for k in parts[0]['tco_breakdown']}
    breakdown['infrastructure_excluding_dr']-=duplicate_fixed
    result=dict(parts[0])  # Each part sees the same entire critical-app inventory.
    result.update(tco=sum(breakdown.values()),tco_breakdown=breakdown,
                  latency=max(p['latency'] for p in parts),
                  latency_edges=[edge for p in parts for edge in p['latency_edges']],
                  simultaneous_peak_headroom={sid:{r:c['capacity']['site_overrides'].get(sid,c['capacity']['default_residual_per_site'])[r]-v for r,v in values.items()} for sid,values in aggregate_loads(c,apps,placement,True).items()})
    return result
