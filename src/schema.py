"""Strict input contracts. Unsupported modes fail explicitly, never fall back."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)

class Versioned(Strict):
    version: Literal[1]

class Resources(Strict):
    cpu_vcpu: float = Field(ge=0)
    ram_gb: float = Field(ge=0)
    gpu_count: float = Field(ge=0)
    storage_tb: float = Field(ge=0)

class DataRequirement(Strict):
    data_country: str
    classification: str

class Dependency(Strict):
    target: str
    max_p95_latency_ms: float = Field(ge=0)

class DR(Strict):
    mode: Literal['DEDICATED', 'REDUCED']
    cpu_ratio: float = Field(gt=0, le=1)
    ram_ratio: float = Field(gt=0, le=1)
    gpu_ratio: float = Field(gt=0, le=1)
    storage_ratio: float = Field(gt=0, le=1)
    rto_minutes: float = Field(ge=0)
    rpo_minutes: float = Field(ge=0)
    @model_validator(mode='after')
    def dedicated(self):
        if self.mode == 'DEDICATED' and any(getattr(self, r) != 1 for r in ('cpu_ratio','ram_ratio','gpu_ratio','storage_ratio')):
            raise ValueError('DEDICATED DR requires all reservation ratios = 1')
        return self

class Application(Strict):
    id: str
    business_domain: str
    criticality: Literal['CRITICAL','NON_CRITICAL']
    materiality: str
    data_requirements: list[DataRequirement] = Field(min_length=1)
    environments: list[str] = Field(min_length=1)
    required_service_categories: list[Literal['COMPUTE','DATABASE','STORAGE','MESSAGING','NETWORKING','AI_ML']] = Field(min_length=1)
    demand: Resources
    demand_mode: Literal['FIXED','VARIABLE'] = 'FIXED'
    peak_demand: Resources | None = None
    dr: DR
    dependencies: list[Dependency] = []
    @model_validator(mode='after')
    def consistent(self):
        if 'PROD' not in self.environments or len(set(self.environments)) != len(self.environments):
            raise ValueError('environments must be unique and contain PROD')
        if len(set(self.required_service_categories)) != len(self.required_service_categories):
            raise ValueError('duplicate required service category')
        if self.demand_mode == 'VARIABLE':
            if self.peak_demand is None or any(getattr(self.peak_demand,k) < v for k,v in self.demand.model_dump().items()):
                raise ValueError('VARIABLE requires peak_demand >= typical demand')
        return self

class Applications(Versioned):
    applications: list[Application]

class Existing(Strict):
    id: str
    business_domain: str
    criticality: Literal['CRITICAL','NON_CRITICAL']
    site_id: str
    service_type: str | None = None
    demand: Resources
    dependencies: list[Dependency] = []

class Portfolio(Versioned):
    synthetic: bool
    applications: list[Existing]

class Recovery(Strict):
    verified: bool
    rto_minutes: float = Field(ge=0)
    rpo_minutes: float = Field(ge=0)
    scaling_verified: bool = False

class Site(Strict):
    id: str
    provider: str
    region: str
    country: str
    hosting: Literal['CLOUD','ON_PREM']
    approved: bool
    ha_verified: bool
    independent_failure_domains: int = Field(ge=0)
    recovery: Recovery | None = None
    processing_country: str | None = None

class Sites(Versioned):
    synthetic: bool
    sites: list[Site] = Field(min_length=10, max_length=10)
    service_categories_default: list[str]
    service_category_overrides: dict[str,list[str]]
    cloud_az_selection_managed_by_provider: Literal[True]

class Policy(Strict):
    data_country: str
    classification: str
    approved_providers: list[str]
    approved_hosting_countries: list[str]
    approved_processing_countries: list[str]

class Approval(Strict):
    approval_required: bool
    approval_status: Literal['APPROVED','PENDING','DENIED'] | None = None
    lead_time_days: int = Field(default=0, ge=0)

class Regulatory(Versioned):
    synthetic_internal_bank_policy: bool
    missing_policy_action: Literal['BLOCK']
    policies: list[Policy]
    materiality: dict[str,Approval]

class Pool(Strict):
    oversubscription: Resources
    require_simultaneous_peak_check: Literal[True]

class Expansion(Strict):
    allow_conditional_proposal: bool
    default_lead_time_days: int = Field(ge=0)
    cost_per_cpu_vcpu: float = Field(ge=0)

class Capacity(Versioned):
    mode: Literal['RESIDUAL_SHARED']
    allocation_mode: Literal['DEDICATED','SHARED_POOL']
    reservation_mode: Literal['PEAK','TYPICAL_WITH_SCALING']
    default_residual_per_site: Resources
    site_overrides: dict[str,Resources]
    shared_pool: Pool
    capacity_expansion: Expansion

class Budget(Strict):
    enabled: bool
    max_total_tco_usd: float | None = Field(default=None, ge=0)
    @model_validator(mode='after')
    def limit(self):
        if self.enabled and self.max_total_tco_usd is None:
            raise ValueError('enabled budget requires max_total_tco_usd')
        return self

class Cost(Versioned):
    synthetic: bool
    currency: Literal['USD']
    horizon_months: int = Field(gt=0)
    fx_rates_to_usd: dict[str,float]
    per_site_monthly_fixed: dict[str,float]
    per_vcpu_monthly: dict[str,float]
    license_monthly_per_application: float = Field(ge=0)
    operations_monthly_per_application: float = Field(ge=0)
    include_dr_cost: Literal[True]
    budget: Budget

class Failure(Strict):
    id: str
    type: Literal['SITE','SHARED_SERVICE']
    site_id: str | None = None
    application_id: str | None = None

class Dependencies(Versioned):
    synthetic: bool
    metric: Literal['P95_MS']
    missing_latency_action: Literal['BLOCK']
    latency_matrix_ms: dict[str,dict[str,float]]
    failure_scenarios: list[Failure]

class Limits(Strict):
    max_variables: int = Field(gt=0, le=2000)
    max_linear_constraints: int = Field(gt=0, le=2000)

class Solver(Versioned):
    engine: Literal['GUROBI']
    license: Literal['FREE_SIZE_LIMITED']
    hard_limits: Limits
    safety_limits: Limits
    allow_quadratic_models: Literal[False]
    on_limit_exceeded: Literal['REJECT_MODEL']
    time_limit_seconds: float = Field(gt=0)
    relative_mip_gap: float = Field(ge=0, le=1)
    threads: int = Field(gt=0)
    seed: int = Field(ge=0)
    @model_validator(mode='after')
    def safe(self):
        for k,v in self.safety_limits.model_dump().items():
            if v > min(1800,getattr(self.hard_limits,k)):
                raise ValueError('safety limits cannot exceed 1800 or hard limits')
        return self

class Weights(Strict):
    tco: float = Field(ge=0)
    latency: float = Field(ge=0)
    concentration: float = Field(ge=0)
    blast_radius: float = Field(ge=0)

class Pareto(Strict):
    enabled: bool
    max_candidates: int = Field(gt=0)

class Infeasibility(Strict):
    strict_first: Literal[True]
    remediation_analysis: bool
    allow_regulatory_relaxation: Literal[False]

class Objectives(Versioned):
    strategy: Literal['WEIGHTED','HIERARCHICAL','PARETO']
    weights: Weights
    normalization: Literal['MIN_MAX']
    hierarchical_order: list[str]
    pareto: Pareto
    infeasibility: Infeasibility

class Split(Strict):
    seed: int
    allow_tuning: bool

class Template(Strict):
    business_domain: str
    data_requirements: list[DataRequirement] = Field(min_length=1)
    demand: Resources

class Generator(Versioned):
    synthetic: Literal[True]
    portfolio_sizes: list[int]
    critical_ratio: float = Field(ge=0, le=1)
    application_types: list[str]
    distributions: list[str]
    splits: dict[str,Split]
    ensure_generated_portfolio_policy_feasible: Literal[True]
    templates: list[Template] = []
    distribution_site_weights: dict[str,dict[str,float]] = {}

class Generation(Strict):
    attempt_modes: list[str]
    reliability_attempts: int
class Repair(Strict):
    modes: list[str]
    max_repair_attempts: int
    expose_reference_solution: Literal[False]
class Security(Strict):
    execute_untrusted_python: Literal[False]
    require_structured_ir_or_isolated_sandbox: Literal[True]
class AI(Versioned):
    enabled: Literal[False]
    model: str
    backend: str
    modes: list[str]
    generation: Generation
    repair: Repair
    security: Security
class Persistence(Strict):
    save_input_snapshot: Literal[True]
    save_generated_formulations: Literal[True]
    save_solver_logs: Literal[True]
    save_validation_results: Literal[True]
    save_metrics_csv: Literal[True]
    unique_run_folder: Literal[True]
class Paths(Strict):
    sites: str
    regulatory: str
    applications: str
    existing_portfolio: str
    capacity: str
    cost: str
    dependencies: str
    objectives: str
    solver: str
    ai: str
    dataset_generator: str
class Formulation(Strict):
    method: Literal['ENUMERATION_MILP','DIRECT_ASSIGNMENT_MILP']
class Optimization(Strict):
    formulation: Formulation
class Experiment(Versioned):
    experiment_id: str
    execution_mode: Literal['INTERACTIVE','BATCH']
    scope: Literal['SINGLE_NEW_APPLICATION','MULTIPLE_NEW_APPLICATIONS']
    selected_application_ids: list[str] = Field(min_length=1)
    dataset: str
    portfolio_size: int = Field(ge=0)
    distribution: str
    formulation_method: Literal['REFERENCE_MILP','ENUMERATION_MILP','DIRECT_ASSIGNMENT_MILP'] | None = None
    optimization: Optimization | None = None
    optimization_strategy: Literal['WEIGHTED','HIERARCHICAL','PARETO']
    paths: Paths
    persistence: Persistence
    @model_validator(mode='after')
    def selected_scope(self):
        legacy='ENUMERATION_MILP' if self.formulation_method=='REFERENCE_MILP' else self.formulation_method
        if self.optimization is None and legacy is None:
            raise ValueError('optimization.formulation.method is required (legacy formulation_method accepted)')
        if self.optimization is not None and legacy is not None and legacy!=self.optimization.formulation.method:
            raise ValueError('conflicting formulation methods')
        if len(set(self.selected_application_ids)) != len(self.selected_application_ids):
            raise ValueError('selected application IDs must be unique')
        if (self.scope == 'SINGLE_NEW_APPLICATION') != (len(self.selected_application_ids) == 1):
            raise ValueError('scope must agree with selected application count')
        return self
