"""Deterministic modeled-policy evidence. Never generates regulatory advice or AI prose."""
import json
from .validation import validate


def build(c, app, portfolio, result, mode):
    e = result.explanation
    report = dict(version=1, status=result.status, scope='Configured synthetic policy only; not external regulatory approval.',
        selected=[], constraints=[], objective={}, alternatives={},
        ai=dict(mode=mode, source=result.source, genuine_optimind_inference=result.genuine_inference,
                invocation_evidence='Recorded genuine generation' if result.genuine_inference else 'No genuine inference recorded',
                model=result.model, formulation=e.get('formulation'), fallback_used=result.fallback_used,
                fallback_reason=result.fallback_reason), solver=result.solver,
        independent_validation=result.independent_validation, input_hashes=result.input_hashes)
    p = result.placement
    if p is None:
        report['unavailable_reason'] = 'No accepted placement; constraints are not reported as passed.'
        return report
    audit = validate(c, app, portfolio, p, result.metrics)
    if not audit['valid'] or audit['status'] != 'DEPLOYABLE':
        raise ValueError('EXPLANATION_INDEPENDENT_AUDIT_FAILED')
    report['independent_validation'] = audit
    sites = {s['id']: s for s in c['sites']['sites']}
    targets = {a['id']: a['site_id'] for a in portfolio}

    def check(name, scope, requirement, actual, rule, ok, source):
        report['constraints'].append(dict(constraint=name, scope=scope, requirement=requirement,
            actual=actual, configured_rule=rule, status='NOT_APPLICABLE' if ok is None else 'PASS' if ok else 'FAIL',
            evidence_source=source))

    for env, sid in dict(p['environments'], DR=p['dr_site_id']).items():
        s = sites[sid]
        report['selected'].append(dict(application=app['id'], environment=env, site=sid,
            country=s['country'], provider=s['provider'], region=s['region']))
        check('site_approval', env, True, s['approved'], 'Site must be approved', s['approved'], 'input_snapshot/sites.yaml')
        if env not in ('PROD', 'DR'):
            check('environment', env, 'HK', s['country'], 'Nonproduction requires HK', s['country']=='HK', 'src/validation.py:validate')
        for req in app['data_requirements']:
            matches = [r for r in c['regulatory']['policies'] if all(r[k]==req[k] for k in ('data_country','classification'))]
            rule = matches[0] if len(matches)==1 else {}
            actual = dict(provider=s['provider'], hosting_country=s['country'], processing_country=s['processing_country'] or s['country'],
                          processing_country_defaulted=s['processing_country'] is None)
            ok = bool(rule) and actual['provider'] in rule['approved_providers'] and actual['hosting_country'] in rule['approved_hosting_countries'] and actual['processing_country'] in rule['approved_processing_countries']
            check('residency_and_policy', env, req, actual, rule, ok, ['input_snapshot/applications.yaml','input_snapshot/regulatory.yaml','input_snapshot/sites.yaml'])
        services = c['sites']['service_category_overrides'].get(sid,c['sites']['service_categories_default'])
        check('services', env, app['required_service_categories'], services, 'All required services available', set(app['required_service_categories'])<=set(services), 'input_snapshot/sites.yaml')
        for dep in app['dependencies']:
            target = targets.get(dep['target'])
            value = c['dependencies']['latency_matrix_ms'].get(sid,{}).get(target)
            check('dependency_latency', env, dep, dict(target_site=target,p95_ms=value), 'Configured edge exists and p95 <= maximum', value is not None and value<=dep['max_p95_latency_ms'], ['input_snapshot/dependencies.yaml','input_snapshot/existing_portfolio.yaml'])
    for sid, usage in audit['reserved_capacity'].items():
        cap = c['capacity']['site_overrides'].get(sid,c['capacity']['default_residual_per_site'])
        for resource, reserved in usage.items():
            peak = audit['simultaneous_peak_capacity'][sid][resource]
            check('capacity', sid+':'+resource, dict(reserved=reserved,simultaneous_peak=peak), cap[resource], 'Both aggregate loads <= residual capacity (includes DR)', max(reserved,peak)<=cap[resource]+1e-9, ['input_snapshot/capacity.yaml','recommendation.json#independent_validation'])
    primary = sites[p['environments']['PROD']]
    recovery = primary['recovery']
    check('dedicated_local_dr', 'DR', app['dr'], dict(site=p['dr_site_id'],failure_domain_contract=p['failure_domain_contract'],ha_verified=primary['ha_verified'],independent_failure_domains=primary['independent_failure_domains']), 'Same site/provider/region, independent local domains; DR loads included in capacity', p['dr_site_id']==primary['id'] and primary['ha_verified'] and primary['independent_failure_domains']>=2 and p['failure_domain_contract']=='INDEPENDENT_LOCAL_DOMAINS', ['input_snapshot/applications.yaml','input_snapshot/sites.yaml'])
    check('recovery', 'PROD/DR', app['dr'], recovery, 'Verified RTO/RPO <= requested; reduced DR requires verified scaling', bool(recovery) and recovery['verified'] and recovery['rto_minutes']<=app['dr']['rto_minutes'] and recovery['rpo_minutes']<=app['dr']['rpo_minutes'] and (app['dr']['mode']!='REDUCED' or recovery['scaling_verified']), 'input_snapshot/sites.yaml')
    approval = c['regulatory']['materiality'].get(app['materiality'])
    check('materiality_approval', app['id'], app['materiality'], approval, 'Required approval must be APPROVED', bool(approval) and (not approval['approval_required'] or approval['approval_status']=='APPROVED'), 'input_snapshot/regulatory.yaml')
    budget = c['cost']['budget']
    check('budget', app['id'], budget, audit['independent_tco'], 'TCO <= enabled budget', audit['independent_tco']<=budget['max_total_tco_usd']+1e-6 if budget['enabled'] else None, 'input_snapshot/cost.yaml')
    ranges = e.get('normalization_ranges') or result.solver.get('normalization',{}).get('ranges')
    weights = c['objectives']['weights']
    objective = dict(metrics=audit['independent_metrics'],weights=weights,ranges=ranges,normalization_basis='Pre-budget feasible extrema; constant components normalize to zero',components={},score=None)
    if ranges:
        for key, value in audit['independent_metrics'].items():
            lo,hi = ranges[key]
            normalized = (value-lo)/(hi-lo) if hi>lo else 0.0
            objective['components'][key] = dict(normalized=normalized,contribution=normalized*weights[key]/sum(weights.values()))
        objective['score'] = sum(v['contribution'] for v in objective['components'].values())
    report['objective'] = objective
    alternatives = []
    for row in e.get('alternatives',[]):
        delta = None if objective['score'] is None else row['normalized_objective']-objective['score']
        alternatives.append(dict(row,score_delta=delta,classification='FEASIBLE_SCORE_UNCOMPARED' if delta is None else 'FEASIBLE_TIED' if abs(delta)<1e-8 else 'FEASIBLE_LOWER_RANKED' if delta>0 else 'INCONSISTENT_BETTER_ALTERNATIVE'))
    report['alternatives'] = dict(enumeration_complete='normalization_ranges' in e,
        not_evaluated_reason=e.get('alternatives_unavailable'), feasible_count_including_selected=e.get('deployable_alternatives_count'),
        displayed_alternatives=alternatives, display_limit_applies=True,
        site_screening=[dict(environment=env,site=sid,reasons=reasons,classification='HARD_INFEASIBLE' if reasons else 'LOCAL_CHECKS_PASSED_NOT_A_COMPLETE_PLACEMENT') for env, rows in e.get('eligibility',{}).items() for sid,reasons in rows.items()],
        global_rejections=e.get('global_rejections',[]),capacity_rejection_count=e.get('capacity_rejection_count'),
        capacity_rejection_examples=e.get('capacity_rejection_examples',[]),budget_rejection_count=e.get('budget_rejection_count'),
        scope='Site screening is not full-placement ranking. Examples may be truncated; unlisted combinations have no invented rejection reason.')
    return report


def render(report):
    def cell(value):
        return json.dumps(value,sort_keys=True,ensure_ascii=False).replace('|','\\|').replace('\n',' ')
    lines = ['# Placement explanation', '', report['scope'], '', 'Status: '+report['status'], '', '## A. Selected placement', '', '| Application | Environment | Site | Country | Provider |', '|---|---|---|---|---|']
    for row in report['selected']:
        lines.append('| '+' | '.join(str(row[k]) for k in ('application','environment','site','country','provider'))+' |')
    if report.get('unavailable_reason'): lines.extend(['',report['unavailable_reason']])
    lines.extend(['','## B. Modeled constraints','','| Constraint / scope | Requirement | Actual | Rule | Status | Evidence |','|---|---|---|---|---|---|'])
    for row in report['constraints']:
        lines.append('| '+' | '.join(cell(v) for v in (row['constraint']+' / '+row['scope'],row['requirement'],row['actual'],row['configured_rule'],row['status'],row['evidence_source']))+' |')
    for title,key in [('C. Objective and selection','objective'),('D. Alternatives and screening','alternatives'),('E. AI provenance','ai'),('F. Independent validation','independent_validation'),('Solver certificate','solver')]:
        lines.extend(['','## '+title,'','```json',json.dumps(report[key],indent=2,sort_keys=True),'```'])
    lines.extend(['','Optimality applies only to the implemented model and solver tolerances. Independent validation checks configured modeled requirements, not real-world compliance.',''])
    return '\n'.join(lines)
