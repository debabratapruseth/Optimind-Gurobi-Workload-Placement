"""Versioned model-neutral, realized inputs. No solver source or solution data."""
import hashlib
import json
from typing import Literal
from pydantic import Field, model_validator
from . import schema as s


def canonical_bytes(value):
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json')
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


class Semantics(s.Strict):
    resources: Literal['cpu_vcpu,ram_GB,gpu_count,storage_TB'] = 'cpu_vcpu,ram_GB,gpu_count,storage_TB'
    cost: Literal['USD; rates per month; horizon in months'] = 'USD; rates per month; horizon in months'
    time: Literal['dependency p95 milliseconds; RTO/RPO minutes'] = 'dependency p95 milliseconds; RTO/RPO minutes'
    reservations: Literal['per environment; PROD plus local DR; residual after fixed portfolio; full simultaneous peak'] = 'per environment; PROD plus local DR; residual after fixed portfolio; full simultaneous peak'
    resilience: Literal['same site primary/DR; independent verified local domains; NONPROD in HK'] = 'same site primary/DR; independent verified local domains; NONPROD in HK'
    concentration: Literal['mean provider/country HHI; critical apps once by PROD; empty population zero'] = 'mean provider/country HHI; critical apps once by PROD; empty population zero'
    blast_radius: Literal['maximum transitive critical disruption fraction; deduplicate apps; source depends on target'] = 'maximum transitive critical disruption fraction; deduplicate apps; source depends on target'
    latency: Literal['maximum direct-edge p95 across new application environments'] = 'maximum direct-edge p95 across new application environments'
    tco: Literal['reserved CPU plus occupied-site overhead plus license/operations per new app, times horizon; no expansion'] = 'reserved CPU plus occupied-site overhead plus license/operations per new app, times horizon; no expansion'
    normalization: Literal['prebudget feasible extrema; constant metric zero; weights divided by sum'] = 'prebudget feasible extrema; constant metric zero; weights divided by sum'
    approval: Literal['pending only conditional when remediation enabled; never deployable'] = 'pending only conditional when remediation enabled; never deployable'


REQUIREMENT_IDS = ('regulatory', 'services', 'recovery_resilience', 'approvals', 'placement', 'capacity', 'dr', 'dependency_latency', 'tco', 'budget', 'concentration', 'blast_radius', 'objective')


class ProblemContract(s.Strict):
    contract_version: Literal['1.0'] = '1.0'
    requirement_ids: list[str] = Field(default_factory=lambda: list(REQUIREMENT_IDS))
    applications: list[s.Application] = Field(min_length=1)
    fixed_portfolio: list[s.Existing]
    sites: s.Sites
    regulatory: s.Regulatory
    capacity: s.Capacity
    cost: s.Cost
    dependencies: s.Dependencies
    objectives: s.Objectives
    solver: s.Solver
    semantics: Semantics = Field(default_factory=Semantics)

    @model_validator(mode='after')
    def references(self):
        if self.requirement_ids != list(REQUIREMENT_IDS):
            raise ValueError('requirement inventory must match contract version')
        sites = {x.id for x in self.sites.sites}
        old = {x.id for x in self.fixed_portfolio}
        new = {x.id for x in self.applications}
        if len(sites) != len(self.sites.sites) or len(old | new) != len(self.fixed_portfolio) + len(self.applications):
            raise ValueError('duplicate site/application ID')
        if any(a.site_id not in sites for a in self.fixed_portfolio):
            raise ValueError('unknown fixed placement')
        for a in self.applications + self.fixed_portfolio:
            permitted = old | new if a.id in new else old
            if any(d.target not in permitted or d.target == a.id for d in a.dependencies):
                raise ValueError('unknown/self dependency')
        for costs in (self.cost.per_site_monthly_fixed, self.cost.per_vcpu_monthly):
            if set(costs) != sites or any(v < 0 for v in costs.values()):
                raise ValueError('invalid site cost coverage')
        if not set(self.capacity.site_overrides) <= sites or not set(self.sites.service_category_overrides) <= sites:
            raise ValueError('unknown site override')
        for source, row in self.dependencies.latency_matrix_ms.items():
            if source not in sites or not set(row) <= sites or any(v < 0 for v in row.values()):
                raise ValueError('invalid latency matrix')
        scenarios = self.dependencies.failure_scenarios
        if len({f.id for f in scenarios}) != len(scenarios) or {f.type for f in scenarios} != {'SITE', 'SHARED_SERVICE'}:
            raise ValueError('invalid scenario coverage')
        for f in scenarios:
            if (f.type == 'SITE' and (f.site_id not in sites or f.application_id is not None)) or (f.type == 'SHARED_SERVICE' and (f.application_id not in old or f.site_id is not None)):
                raise ValueError('invalid failure reference')
        policies = [(p.data_country, p.classification) for p in self.regulatory.policies]
        if len(set(policies)) != len(policies):
            raise ValueError('duplicate policy')
        if sum(self.objectives.weights.model_dump().values()) <= 0:
            raise ValueError('zero objective weights')
        order = self.objectives.hierarchical_order
        if len(order) != 5 or order[0] != 'feasibility' or set(order[1:]) != {'tco', 'latency', 'concentration', 'blast_radius'}:
            raise ValueError('invalid hierarchy')
        if (self.objectives.strategy == 'PARETO') != self.objectives.pareto.enabled:
            raise ValueError('inconsistent Pareto configuration')
        if any(v < 1 for v in self.capacity.shared_pool.oversubscription.model_dump().values()):
            raise ValueError('invalid oversubscription')
        return self


def from_config(c, portfolio):
    selected = c['experiment']['selected_application_ids']
    values = {k: c[k] for k in ('sites', 'regulatory', 'capacity', 'cost', 'dependencies', 'objectives', 'solver')}
    values.update(applications=[a for aid in selected for a in c['applications']['applications'] if a['id'] == aid], fixed_portfolio=portfolio)
    return ProblemContract.model_validate(values)


def inputs(contract):
    contract = ProblemContract.model_validate(contract.model_dump() if isinstance(contract, ProblemContract) else contract)
    c = contract.model_dump()
    apps, portfolio = c.pop('applications'), c.pop('fixed_portfolio')
    return c, apps, portfolio
