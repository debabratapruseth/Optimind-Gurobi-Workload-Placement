"""Transparent candidate metrics, in original units, with no feasibility ranking of invalid results."""
from collections import Counter
from .feasibility import loads

METRICS=('tco','latency','concentration','blast_radius')

def measure(c, app, portfolio, placement):
    if isinstance(app,list):
        from .joint import measure_joint
        return measure_joint(c,app,portfolio,placement)
    usage=loads(c,app,placement)
    cost=c['cost']; horizon=cost['horizon_months']
    cpu=sum(v['cpu_vcpu']*cost['per_vcpu_monthly'][sid] for sid,v in usage.items())
    fixed=sum(cost['per_site_monthly_fixed'][sid] for sid in usage)
    lic=cost['license_monthly_per_application']; ops=cost['operations_monthly_per_application']
    demand=app['peak_demand'] if app['demand_mode']=='VARIABLE' and c['capacity']['reservation_mode']=='PEAK' else app['demand']
    dr_cpu=demand['cpu_vcpu']*app['dr']['cpu_ratio']*cost['per_vcpu_monthly'][placement['dr_site_id']]
    breakdown=dict(infrastructure_excluding_dr=(cpu-dr_cpu+fixed)*horizon,dr=dr_cpu*horizon,
                   licensing=lic*horizon,operations=ops*horizon,expansion=0.0)
    sites={s['id']:s for s in c['sites']['sites']}
    nodes={p['id']:p for p in portfolio}
    nodes[app['id']]=dict(app,site_id=placement['environments']['PROD'])
    critical={k for k,p in nodes.items() if p['criticality']=='CRITICAL'}
    counts={key:Counter(sites[nodes[k]['site_id']][key] for k in critical) for key in ('provider','country')}
    shares={key:{k:v/max(1,len(critical)) for k,v in cnt.items()} for key,cnt in counts.items()}
    hhi={key:sum(v*v for v in part.values()) for key,part in shares.items()}
    scenarios=[]
    for scenario in c['dependencies']['failure_scenarios']:
        initial={k for k,p in nodes.items() if p['site_id']==scenario['site_id']} if scenario['type']=='SITE' else {scenario['application_id']}
        impacted=set(initial)
        while True:
            added={k for k,p in nodes.items() if any(d['target'] in impacted for d in p.get('dependencies',[]))}
            if added<=impacted:
                break
            impacted|=added
        scenarios.append(dict(id=scenario['id'],type=scenario['type'],
                              infrastructure_exposed_critical=sorted(initial & critical) if scenario['type']=='SITE' else [],
                              directly_failed_critical=sorted(initial & critical),
                              residual_business_disruption_critical=sorted(impacted & critical),
                              critical_count=len(impacted & critical)))
    edges=[]
    for env,sid in placement['environments'].items():
        for dep in app['dependencies']:
            value=c['dependencies']['latency_matrix_ms'][sid][nodes[dep['target']]['site_id']]
            edges.append(dict(environment=env,source=app['id'],target=dep['target'],p95_ms=value,max_p95_ms=dep['max_p95_latency_ms']))
    headroom={sid:{r:c['capacity']['site_overrides'].get(sid,c['capacity']['default_residual_per_site'])[r]-v for r,v in values.items()} for sid,values in loads(c,app,placement,True).items()}
    return dict(tco=sum(breakdown.values()),latency=max((e['p95_ms'] for e in edges),default=0),
                concentration=sum(hhi.values())/2,blast_radius=max((s['critical_count'] for s in scenarios),default=0)/max(1,len(critical)),
                tco_breakdown=breakdown,concentration_shares=shares,concentration_hhi=hhi,
                failure_scenarios=scenarios,latency_edges=edges,simultaneous_peak_headroom=headroom,
                critical_application_count=len(critical))

def normalized_scores(c, metrics):
    limits={k:(min((m[k] for m in metrics),default=0),max((m[k] for m in metrics),default=0)) for k in METRICS}
    normalized=[{k:(m[k]-lo)/(hi-lo) if hi>lo else 0.0 for k,(lo,hi) in limits.items()} for m in metrics]
    total=sum(c['objectives']['weights'].values())
    scores=[sum(row[k]*c['objectives']['weights'][k]/total for k in METRICS) for row in normalized]
    return scores,dict(ranges=limits,normalized=normalized,weights=c['objectives']['weights'])
