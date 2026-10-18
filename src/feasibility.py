"""Deterministic pre-solver screening of all candidate environment assignments."""
from itertools import product
from time import perf_counter

RESOURCES = ('cpu_vcpu','ram_gb','gpu_count','storage_tb')
RATIOS = dict(zip(RESOURCES,('cpu_ratio','ram_ratio','gpu_ratio','storage_ratio')))

def site_reasons(c, app, site, env, portfolio):
    reasons=[]
    if not site['approved']:
        reasons.append('SITE_NOT_APPROVED')
    if env != 'PROD' and site['country'] != 'HK':
        reasons.append('NONPROD_REQUIRES_HK')
    for req in app['data_requirements']:
        p=next((p for p in c['regulatory']['policies'] if all(p[k]==req[k] for k in ('data_country','classification'))),None)
        if p is None:
            reasons.append('MISSING_POLICY')
        elif site['provider'] not in p['approved_providers'] or site['country'] not in p['approved_hosting_countries'] or (site['processing_country'] or site['country']) not in p['approved_processing_countries']:
            reasons.append('POLICY_DENIAL')
    services=c['sites']['service_category_overrides'].get(site['id'],c['sites']['service_categories_default'])
    if not set(app['required_service_categories']) <= set(services):
        reasons.append('MISSING_SERVICE')
    if env=='PROD':
        if not site['ha_verified'] or site['independent_failure_domains']<2:
            reasons.append('HA_INDEPENDENCE_UNVERIFIED')
        recovery=site['recovery']
        if not recovery or not recovery['verified']:
            reasons.append('MISSING_RECOVERY_EVIDENCE')
        elif recovery['rto_minutes']>app['dr']['rto_minutes'] or recovery['rpo_minutes']>app['dr']['rpo_minutes']:
            reasons.append('RECOVERY_TARGET_NOT_MET')
        if app['dr']['mode']=='REDUCED' and (not recovery or not recovery['scaling_verified']):
            reasons.append('DR_SCALING_UNVERIFIED')
    if app['demand_mode']=='VARIABLE' and c['capacity']['reservation_mode']=='TYPICAL_WITH_SCALING' and (not site['recovery'] or not site['recovery']['scaling_verified']):
        reasons.append('DEMAND_SCALING_UNVERIFIED')
    targets={p['id']:p for p in portfolio}
    for dep in app['dependencies']:
        target=targets.get(dep['target'])
        latency=c['dependencies']['latency_matrix_ms'].get(site['id'],{}).get(target['site_id']) if target else None
        if latency is None:
            reasons.append('MISSING_LATENCY_EVIDENCE')
        elif latency>dep['max_p95_latency_ms']:
            reasons.append('DEPENDENCY_LATENCY_EXCEEDED')
    return sorted(set(reasons))

def loads(c, app, placement, peak=False):
    if isinstance(app,list):
        from .joint import aggregate_loads
        return aggregate_loads(c,app,placement,peak)
    demand=app['peak_demand'] if app['demand_mode']=='VARIABLE' and (peak or c['capacity']['reservation_mode']=='PEAK') else app['demand']
    totals={}
    for env,sid in placement['environments'].items():
        totals.setdefault(sid,dict.fromkeys(RESOURCES,0.0))
        for r in RESOURCES:
            totals[sid][r]+=demand[r]
            if env=='PROD':
                # Simultaneous peak conservatively includes full DR recovery reservation.
                ratio=1 if peak else app['dr'][RATIOS[r]]
                totals[sid][r]+=demand[r]*ratio
    return totals

def capacity_reasons(c, app, placement):
    reasons=[]
    for label, usage in [('RESERVATION',loads(c,app,placement)),('SIMULTANEOUS_PEAK',loads(c,app,placement,True))]:
        for sid,resources in usage.items():
            available=c['capacity']['site_overrides'].get(sid,c['capacity']['default_residual_per_site'])
            for resource,amount in resources.items():
                if amount>available[resource]+1e-9:
                    reasons.append(f'CAPACITY_{label}:{sid}:{resource}')
    return reasons

def enumerate_candidates(c, app, portfolio, timings=None):
    if isinstance(app,list):
        from .joint import enumerate_joint
        return enumerate_joint(c,app,portfolio,timings)
    started=perf_counter()
    eligible={}; screening={}
    for env in app['environments']:
        eligible[env]=[]; screening[env]={}
        for site in c['sites']['sites']:
            reasons=site_reasons(c,app,site,env,portfolio)
            screening[env][site['id']]=reasons
            if not reasons:
                eligible[env].append(site['id'])
    approval=c['regulatory']['materiality'].get(app['materiality'])
    if timings is not None:
        timings['feasibility_preprocessing']+=perf_counter()-started
    if approval is None or (approval['approval_required'] and approval['approval_status']=='DENIED'):
        return [],dict(sites=screening,global_reasons=['MISSING_MATERIALITY_POLICY' if approval is None else 'APPROVAL_DENIED'])
    conditional=approval['approval_required'] and approval['approval_status']!='APPROVED'
    started=perf_counter()
    candidates=[]; rejected=[]
    for values in product(*(eligible[e] for e in app['environments'])):
        envs=dict(zip(app['environments'],values))
        p=dict(application_id=app['id'],environments=envs,dr_site_id=envs['PROD'],
               failure_domain_contract='INDEPENDENT_LOCAL_DOMAINS',approval_pending=conditional)
        reasons=capacity_reasons(c,app,p)
        if reasons:
            rejected.append(dict(placement=p,reasons=reasons))
        else:
            candidates.append(p)
    if timings is not None:
        timings['candidate_enumeration']+=perf_counter()-started
    return candidates,dict(sites=screening,global_reasons=['APPROVAL_PENDING'] if conditional else [],capacity_rejections=rejected)
