"""Seeded fixed synthetic exposure inventory; never subtract it twice from residual capacity."""
from copy import deepcopy
import random

def generate(c):
    gen, exp = c['dataset_generator'], c['experiment']
    result = deepcopy(c['existing_portfolio']['applications'])
    count = exp['portfolio_size'] - len(result)
    if not count:
        return result
    if not gen['templates'] or exp['distribution'] not in gen['distribution_site_weights']:
        raise ValueError('synthetic generation requires YAML templates and distribution_site_weights')
    rng = random.Random(gen['splits'][exp['dataset']]['seed'])
    policies = {(p['data_country'],p['classification']):p for p in c['regulatory']['policies']}
    for index in range(count):
        template = rng.choice(gen['templates'])
        eligible, weights = [], []
        for site in c['sites']['sites']:
            ok = site['approved']
            for req in template['data_requirements']:
                p = policies.get((req['data_country'],req['classification']))
                ok = ok and p is not None and site['provider'] in p['approved_providers'] and site['country'] in p['approved_hosting_countries'] and (site['processing_country'] or site['country']) in p['approved_processing_countries']
            weight = gen['distribution_site_weights'][exp['distribution']].get(site['id'],0)
            if ok and weight > 0:
                eligible.append(site['id']); weights.append(weight)
        if not eligible:
            raise ValueError('no policy-feasible positive-weight synthetic template site')
        app_id = f'SYN-{exp["dataset"]}-{index:05d}'
        if any(a['id']==app_id for a in result):
            raise ValueError(f'generated ID collision: {app_id}')
        result.append(dict(id=app_id, business_domain=template['business_domain'],
                           criticality='CRITICAL' if rng.random()<gen['critical_ratio'] else 'NON_CRITICAL',
                           site_id=rng.choices(eligible,weights=weights,k=1)[0],
                           demand=deepcopy(template['demand']), dependencies=[],
                           data_requirements=deepcopy(template['data_requirements']), synthetic_generated=True))
    return result
