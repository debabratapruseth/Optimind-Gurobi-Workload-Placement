"""Independent result audit: no use of feasibility filters, candidate loads or solver values."""
import math

def validate(c, app, portfolio, placement, reported_metrics=None):
    if isinstance(app,list):
        return validate_joint(c,app,portfolio,placement,reported_metrics)
    errors=[]; pending=[]
    if not isinstance(placement,dict):
        return dict(valid=False,status='REJECTED',reasons=['MISSING_PLACEMENT'])
    sites={s['id']:s for s in c['sites']['sites']}
    envs=placement.get('environments',{})
    if not isinstance(envs,dict) or any(not isinstance(v,str) for v in envs.values()):
        return dict(valid=False,status='REJECTED',reasons=['MALFORMED_ENVIRONMENTS'])
    if placement.get('application_id')!=app['id'] or set(envs)!=set(app['environments']):
        return dict(valid=False,status='REJECTED',reasons=['APPLICATION_OR_ENVIRONMENTS_MISMATCH'])
    if any(sid not in sites for sid in envs.values()) or 'PROD' not in envs:
        return dict(valid=False,status='REJECTED',reasons=errors+['UNKNOWN_OR_MISSING_SITE'])
    if not isinstance(placement.get('dr_site_id'),str):
        return dict(valid=False,status='REJECTED',reasons=['MALFORMED_DR_SITE'])
    primary=sites[envs['PROD']]; dr=sites.get(placement.get('dr_site_id'))
    if dr is None or dr['id']!=primary['id'] or (dr['provider'],dr['region'])!=(primary['provider'],primary['region']):
        errors.append('DR_SAME_SITE_PROVIDER_REGION_REQUIRED')
    if not primary['ha_verified'] or primary['independent_failure_domains']<2 or placement.get('failure_domain_contract')!='INDEPENDENT_LOCAL_DOMAINS':
        errors.append('INDEPENDENT_FAILURE_DOMAINS_REQUIRED')
    recovery=primary.get('recovery')
    if not recovery or not recovery['verified'] or recovery['rto_minutes']>app['dr']['rto_minutes'] or recovery['rpo_minutes']>app['dr']['rpo_minutes']:
        errors.append('RECOVERY_EVIDENCE_REQUIRED')
    if app['dr']['mode']=='REDUCED' and (not recovery or not recovery['scaling_verified']):
        errors.append('DR_SCALING_EVIDENCE_REQUIRED')
    approval=c['regulatory']['materiality'].get(app['materiality'])
    if approval is None:
        errors.append('MISSING_MATERIALITY_POLICY')
    elif approval['approval_required']:
        if approval['approval_status']=='DENIED':
            errors.append('APPROVAL_DENIED')
        elif approval['approval_status']!='APPROVED':
            pending.append('APPROVAL_PENDING')
    typical=app['demand']; peak=app['peak_demand'] if app['demand_mode']=='VARIABLE' else typical
    reservation=peak if c['capacity']['reservation_mode']=='PEAK' else typical
    reserved={}; simultaneous={}; targets={p['id']:p['site_id'] for p in portfolio}
    latency_values=[]
    for env,sid in envs.items():
        site=sites[sid]
        if not site['approved']:
            errors.append(f'SITE_NOT_APPROVED:{sid}')
        if env!='PROD' and site['country']!='HK':
            errors.append(f'NONPROD_REQUIRES_HK:{env}')
        for req in app['data_requirements']:
            matching=[p for p in c['regulatory']['policies'] if p['data_country']==req['data_country'] and p['classification']==req['classification']]
            if len(matching)!=1:
                errors.append('MISSING_OR_AMBIGUOUS_POLICY')
            else:
                policy=matching[0]
                if site['provider'] not in policy['approved_providers'] or site['country'] not in policy['approved_hosting_countries'] or (site['processing_country'] or site['country']) not in policy['approved_processing_countries']:
                    errors.append(f'POLICY_DENIAL:{env}:{sid}')
        if any(category not in c['sites']['service_category_overrides'].get(sid,c['sites']['service_categories_default']) for category in app['required_service_categories']):
            errors.append(f'MISSING_SERVICE:{sid}')
        if app['demand_mode']=='VARIABLE' and c['capacity']['reservation_mode']=='TYPICAL_WITH_SCALING' and (not site['recovery'] or not site['recovery']['scaling_verified']):
            errors.append(f'SCALING_EVIDENCE_REQUIRED:{sid}')
        for dep in app['dependencies']:
            value=c['dependencies']['latency_matrix_ms'].get(sid,{}).get(targets.get(dep['target']))
            if value is None or value>dep['max_p95_latency_ms']:
                errors.append(f'LATENCY_NOT_VALIDATED:{env}:{dep["target"]}')
            else:
                latency_values.append(value)
        reserved.setdefault(sid,{r:0.0 for r in typical})
        simultaneous.setdefault(sid,{r:0.0 for r in typical})
        for resource,ratio_key in [('cpu_vcpu','cpu_ratio'),('ram_gb','ram_ratio'),('gpu_count','gpu_ratio'),('storage_tb','storage_ratio')]:
            reserved[sid][resource]+=reservation[resource]*(1+app['dr'][ratio_key] if env=='PROD' else 1)
            simultaneous[sid][resource]+=peak[resource]*(2 if env=='PROD' else 1)
    for sid in reserved:
        cap=c['capacity']['site_overrides'].get(sid,c['capacity']['default_residual_per_site'])
        for resource in typical:
            if max(reserved[sid][resource],simultaneous[sid][resource])>cap[resource]+1e-9:
                errors.append(f'CAPACITY_EXCEEDED:{sid}:{resource}')
    cost=c['cost']
    tco=cost['horizon_months']*(sum(cost['per_site_monthly_fixed'][sid]+cost['per_vcpu_monthly'][sid]*values['cpu_vcpu'] for sid,values in reserved.items())+cost['license_monthly_per_application']+cost['operations_monthly_per_application'])
    if cost['budget']['enabled'] and tco>cost['budget']['max_total_tco_usd']+1e-6:
        errors.append('BUDGET_EXCEEDED')
    if reported_metrics is not None:
        if not isinstance(reported_metrics,dict) or any(
            not isinstance(reported_metrics.get(k),(int,float)) or isinstance(reported_metrics.get(k),bool)
            or not math.isfinite(reported_metrics[k]) for k in ('tco','latency','concentration','blast_radius')):
            return dict(valid=False,status='REJECTED',reasons=errors+['INVALID_REPORTED_METRICS'])
        if abs(reported_metrics['tco']-tco)>1e-6:
            errors.append('TCO_METRIC_MISMATCH')
        if abs(reported_metrics['latency']-max(latency_values,default=0))>1e-6:
            errors.append('LATENCY_METRIC_MISMATCH')
    # Recompute even without supplied metrics: this is also the exhaustive oracle's
    # independent metric implementation, not a call into the production metrics.
    inventory={p['id']:p for p in portfolio}
    inventory[app['id']]=dict(app,site_id=envs['PROD'])
    critical=[p for p in inventory.values() if p['criticality']=='CRITICAL']
    n=max(1,len(critical))
    concentration=0.0
    for dimension in ('provider','country'):
        groups={sites[p['site_id']][dimension] for p in critical}
        concentration+=sum((sum(sites[p['site_id']][dimension]==group for p in critical)/n)**2 for group in groups)/2
    worst=0
    for scenario in c['dependencies']['failure_scenarios']:
        failed={p['id'] for p in inventory.values() if p['site_id']==scenario['site_id']} if scenario['type']=='SITE' else {scenario['application_id']}
        def disrupted(key,seen):
            if key in failed:
                return True
            if key in seen:
                return False
            return any(disrupted(d['target'],seen|{key}) for d in inventory[key].get('dependencies',[]))
        worst=max(worst,sum(disrupted(p['id'],set()) for p in critical))
    if reported_metrics is not None and (abs(reported_metrics['concentration']-concentration)>1e-9 or abs(reported_metrics['blast_radius']-worst/n)>1e-9):
        errors.append('EXPOSURE_METRIC_MISMATCH')
    return dict(valid=not errors,status='REJECTED' if errors else 'CONDITIONAL' if pending else 'DEPLOYABLE',
                reasons=sorted(set(errors+pending)),independent_tco=tco,reserved_capacity=reserved,simultaneous_peak_capacity=simultaneous,
                independent_metrics=dict(tco=tco,latency=max(latency_values,default=0),concentration=concentration,blast_radius=worst/n))


def validate_joint(c, apps, portfolio, placement, reported_metrics=None):
    """Audit all apps, then independently sum shared loads and joint TCO.

    Deliberately does not import joint.py, feasibility.py or metrics.py.
    """
    errors=[]
    if not isinstance(placement,dict) or not isinstance(placement.get('applications'),dict):
        return dict(valid=False,status='REJECTED',reasons=['MISSING_JOINT_PLACEMENT'])
    chosen=placement['applications']
    if set(chosen)!={a['id'] for a in apps}:
        return dict(valid=False,status='REJECTED',reasons=['JOINT_APPLICATION_SET_MISMATCH'])
    sites={s['id'] for s in c['sites']['sites']}
    for a in apps:
        p=chosen[a['id']]
        if not isinstance(p,dict) or not isinstance(p.get('environments'),dict) or not isinstance(p['environments'].get('PROD'),str) or p['environments']['PROD'] not in sites:
            return dict(valid=False,status='REJECTED',reasons=['MALFORMED_JOINT_PLACEMENT'])
    nodes=[dict(a,site_id=chosen[a['id']]['environments']['PROD']) for a in apps]
    # The hard budget applies once to the joint deployment, below.
    local=dict(c,cost=dict(c['cost'],budget=dict(enabled=False,max_total_tco_usd=None)))
    checks={a['id']:validate(local,a,portfolio+[n for n in nodes if n['id']!=a['id']],chosen[a['id']]) for a in apps}
    if any('independent_metrics' not in v for v in checks.values()):
        return dict(valid=False,status='REJECTED',reasons=['INVALID_APPLICATION_PLACEMENT'],applications=checks)
    reserved={}; peak={}
    for app_id,audit in checks.items():
        if not audit['valid']:
            errors.extend(f'{app_id}:{r}' for r in audit['reasons'])
        for source,total in [('reserved_capacity',reserved),('simultaneous_peak_capacity',peak)]:
            for sid,values in audit[source].items():
                total.setdefault(sid,{r:0.0 for r in values})
                for r,v in values.items():
                    total[sid][r]+=v
    for sid,values in peak.items():
        cap=c['capacity']['site_overrides'].get(sid,c['capacity']['default_residual_per_site'])
        for r,v in values.items():
            if v>cap[r]+1e-9 or reserved[sid][r]>cap[r]+1e-9:
                errors.append(f'JOINT_CAPACITY_EXCEEDED:{sid}:{r}')
    cost=c['cost']
    tco=cost['horizon_months']*(sum(cost['per_site_monthly_fixed'][sid]+cost['per_vcpu_monthly'][sid]*v['cpu_vcpu'] for sid,v in reserved.items())+len(apps)*(cost['license_monthly_per_application']+cost['operations_monthly_per_application']))
    if cost['budget']['enabled'] and tco>cost['budget']['max_total_tco_usd']+1e-6:
        errors.append('JOINT_BUDGET_EXCEEDED')
    first=next(iter(checks.values()))['independent_metrics']
    metrics=dict(tco=tco,latency=max(a['independent_metrics']['latency'] for a in checks.values()),
                 concentration=first['concentration'],blast_radius=first['blast_radius'])
    if reported_metrics is not None:
        for k,v in metrics.items():
            actual=reported_metrics.get(k) if isinstance(reported_metrics,dict) else None
            if not isinstance(actual,(int,float)) or isinstance(actual,bool) or not math.isfinite(actual) or abs(actual-v)>1e-6:
                errors.append(f'METRIC_MISMATCH:{k}')
    pending=any(a['status']=='CONDITIONAL' for a in checks.values())
    return dict(valid=not errors,status='REJECTED' if errors else 'CONDITIONAL' if pending else 'DEPLOYABLE',
                reasons=sorted(set(errors+(['APPROVAL_PENDING'] if pending else []))),applications=checks,
                independent_metrics=metrics,independent_tco=tco,reserved_capacity=reserved,simultaneous_peak_capacity=peak)
