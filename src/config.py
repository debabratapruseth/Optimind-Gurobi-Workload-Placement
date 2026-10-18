"""Load all inputs once, preserving exact source bytes for reproducibility."""
from pathlib import Path
import hashlib
import yaml
from . import schema as s

class UniqueLoader(yaml.SafeLoader):
    pass

def mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f'duplicate YAML key: {key}')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result
UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)

MODELS = dict(sites=s.Sites, regulatory=s.Regulatory, applications=s.Applications,
              existing_portfolio=s.Portfolio, capacity=s.Capacity, cost=s.Cost,
              dependencies=s.Dependencies, objectives=s.Objectives, solver=s.Solver,
              ai=s.AI, dataset_generator=s.Generator)

def load(path, on_source=None):
    path = Path(path).resolve()
    sources = {}
    def read(p, key, model):
        raw = p.read_bytes()
        sources[key] = {'path':str(p), 'sha256':hashlib.sha256(raw).hexdigest(), 'text':raw.decode()}
        if on_source is not None:
            on_source(key, sources[key])
        try:
            return model.model_validate(yaml.load(raw, Loader=UniqueLoader)).model_dump()
        except Exception as exc:
            raise ValueError(f'{p}: {exc}') from exc
    cfg = {'experiment':read(path,'experiment',s.Experiment)}
    # Relative paths are project-root relative, found from the experiment ancestors.
    for key, value in cfg['experiment']['paths'].items():
        p = Path(value)
        if not p.is_absolute():
            matches = [parent / p for parent in path.parents if (parent / p).is_file()]
            if not matches:
                raise ValueError(f'{key}: cannot resolve {value} relative to experiment ancestors')
            p = matches[0]
        cfg[key] = read(p,key,MODELS[key])
    cross_validate(cfg)
    return cfg, sources

def cross_validate(c):
    def unique(items, label):
        if len(items) != len(set(items)):
            raise ValueError(f'duplicate {label}')
    sites = {x['id'] for x in c['sites']['sites']}
    unique([x['id'] for x in c['sites']['sites']], 'site id')
    new = [x['id'] for x in c['applications']['applications']]
    old = [x['id'] for x in c['existing_portfolio']['applications']]
    unique(new+old, 'application id')
    unique([(x['data_country'],x['classification']) for x in c['regulatory']['policies']], 'policy')
    if not set(c['experiment']['selected_application_ids']) <= set(new):
        raise ValueError('selected application does not exist')
    for app in c['existing_portfolio']['applications']:
        if app['site_id'] not in sites:
            raise ValueError(f"unknown portfolio site: {app['site_id']}")
    for app in c['applications']['applications']+c['existing_portfolio']['applications']:
        for dep in app['dependencies']:
            permitted=set(old)
            if app['id'] in c['experiment']['selected_application_ids']:
                permitted.update(c['experiment']['selected_application_ids'])
            if dep['target'] not in permitted or dep['target']==app['id']:
                raise ValueError('dependencies require a distinct fixed or selected application target')
    for key in ('per_site_monthly_fixed','per_vcpu_monthly'):
        if set(c['cost'][key]) != sites or any(v < 0 for v in c['cost'][key].values()):
            raise ValueError(f'{key}: require nonnegative cost for every site, no unknown sites')
    for values in (c['capacity']['site_overrides'],c['sites']['service_category_overrides']):
        if not set(values) <= sites:
            raise ValueError('unknown site override')
    for source,row in c['dependencies']['latency_matrix_ms'].items():
        if source not in sites or not set(row) <= sites or any(v < 0 for v in row.values()):
            raise ValueError('invalid latency matrix site or negative latency')
    unique([x['id'] for x in c['dependencies']['failure_scenarios']], 'failure scenario')
    if {f['type'] for f in c['dependencies']['failure_scenarios']} != {'SITE','SHARED_SERVICE'}:
        raise ValueError('both SITE and SHARED_SERVICE failure scenarios are required')
    for f in c['dependencies']['failure_scenarios']:
        if (f['type']=='SITE' and (f['site_id'] not in sites or f['application_id'] is not None)) or (f['type']=='SHARED_SERVICE' and (f['application_id'] not in old or f['site_id'] is not None)):
            raise ValueError('failure scenario must reference exactly one valid site or fixed application')
    exp, gen, obj = c['experiment'], c['dataset_generator'], c['objectives']
    if exp['dataset'] not in gen['splits'] or exp['distribution'] not in gen['distributions']:
        raise ValueError('unknown dataset split or distribution')
    if len({v['seed'] for v in gen['splits'].values()}) != len(gen['splits']):
        raise ValueError('dataset splits must use independent seeds')
    if gen['splits'].get('HELD_OUT_TEST',{}).get('allow_tuning',False):
        raise ValueError('held-out tuning forbidden')
    if exp['portfolio_size'] < len(old):
        raise ValueError('cannot truncate fixed portfolio to requested size')
    if exp['portfolio_size'] not in gen['portfolio_sizes']:
        raise ValueError('portfolio_size not in configured generator sizes')
    if exp['optimization_strategy'] != obj['strategy']:
        raise ValueError('experiment and objective strategies disagree')
    if sum(obj['weights'].values()) <= 0:
        raise ValueError('objective weights must have positive total')
    if obj['hierarchical_order'][0:1] != ['feasibility'] or set(obj['hierarchical_order'][1:]) != set(obj['weights']) or len(obj['hierarchical_order']) != 5:
        raise ValueError('hierarchical order requires feasibility followed by each metric exactly once')
    if (obj['strategy']=='PARETO') != obj['pareto']['enabled']:
        raise ValueError('PARETO strategy and pareto.enabled must agree')
    for weights in gen['distribution_site_weights'].values():
        if not set(weights) <= sites or any(v < 0 for v in weights.values()):
            raise ValueError('invalid generator site weights')
    if any(t['business_domain'] not in gen['application_types'] for t in gen['templates']):
        raise ValueError('generator template domain not in application_types')
    if any(v < 1 for v in c['capacity']['shared_pool']['oversubscription'].values()):
        raise ValueError('oversubscription must be >= 1; physical simultaneous peak is always enforced')


def formulation_method(c):
    setting=c['experiment'].get('optimization')
    if setting:
        return setting['formulation']['method']
    legacy=c['experiment']['formulation_method']
    return 'ENUMERATION_MILP' if legacy=='REFERENCE_MILP' else legacy
