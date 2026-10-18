# Input files and supported constraints

`config/scenario.yaml` is an existing strict `Experiment` document. `paths` selects inputs; paths resolve against scenario-file ancestors. No application folder is hardcoded. Use a new scenario file for separate cases and keep its input references explicit.

| Input | Actual supported settings and effect |
| --- | --- |
| `config/application.yaml` | `version: 1`, one `applications` entry; ID, domain, criticality, materiality, data requirements, environments, service categories, demand, DR, dependencies. |
| `config/infrastructure/sites.yaml` | Exactly ten `sites`; provider/region/country, hosting, approval, HA, independent domains, optional processing country, recovery; service defaults and overrides. |
| `config/infrastructure/capacity.yaml` | Residual resource defaults/complete site overrides, PEAK or TYPICAL_WITH_SCALING reservations, shared/dedicated allocation, full simultaneous-peak enforcement, conditional expansion proposal settings. |
| `config/infrastructure/costs.yaml` | USD horizon, per-site monthly fixed and per-vCPU costs for every site, licensing/operations per application, mandatory DR inclusion, optional budget. FX metadata is not used for currency conversion. |
| `config/infrastructure/portfolio.yaml` | Explicit fixed applications with unique IDs, `site_id`, demands, optional service type and dependencies. These applications are not decision variables. |
| `config/policies/regulatory.yaml` | Policy matching by data-country/classification; allowed providers and hosting/processing countries; materiality approvals. Missing policies block placement. |
| `config/policies/dependencies.yaml` | Directional `latency_matrix_ms`; P95_MS; missing edges block placement; SITE and SHARED_SERVICE failure scenarios. |
| `config/optimization/objectives.yaml` | WEIGHTED strategy, nonnegative weights with positive sum, MIN_MAX normalization over prebudget feasible extrema, remediation flags. |
| `config/optimization/solver.yaml` | Gurobi restricted mode, hard/safety model limits, no quadratic models, time limit, relative gap, threads, seed. |
| `config/optimind.yaml` | Pinned checkpoint and Transformers text inference settings, one attempt/no repair, structured output, equivalence limits. |
| `config/runtime/` | Internal compatibility settings: disabled baseline AI, fixed-inventory generator metadata, verification limits, and a backend reference launcher. Users normally leave these unchanged. |

## Editing the application

Edit existing keys in the supplied full card. `demand` values apply to every environment. `demand_mode: VARIABLE` additionally requires `peak_demand` with the same four resource keys and values at least as large as typical demand. Unknown fields are rejected. PROD is required; all other environment labels are nonproduction and must run in HK. The compact specification accepts at most sixteen environment labels, but exhaustive verification and model-size limits can be reached much earlier.

Data country is a classification/policy lookup input, not a direct hosting-country equality. The supplied SG policy allows AWS in SG or HK. Changing data requirements requires matching regulatory records and sufficient eligible infrastructure.

Dependencies target an explicit fixed application ID. Latency limits apply from every environment to the target site; the aggregate latency metric is the maximum direct-edge latency, not an average or a transitive path sum.

DR remains local to PROD. DEDICATED requires all four ratios to equal 1. REDUCED permits ratios in (0, 1] and requires verified scaling. Full simultaneous-peak recovery capacity is still checked. Site recovery RTO/RPO must not exceed the application's targets. Synthetic flags in the supplied inventory are illustrative evidence, not provider certification.

## Fixed inventory

Keep `portfolio_size` equal to the explicit inventory length. If changing it, also include that length in `config/runtime/generator.yaml` under `portfolio_sizes`; the shared loader requires consistency, but the public pipeline never generates additional fixed applications. Configure residual capacity after that inventory. No automatic conversion of an existing application into a movable workload occurs.

## Verify edits

From the repository root:

```bash
python -c "from src.pipeline import load_problem; load_problem('config/scenario.yaml'); print('Inputs valid')"
python -m src.pipeline --config config/scenario.yaml --mode REFERENCE_FALLBACK --output results/placement
```

The first command validates schemas, references, scope, and the problem contract. Only the second solves and independently checks feasibility. Inspect eligibility reasons for infeasible runs. Do not relax a policy merely to obtain a result.

New mathematical constraint types require deliberate changes to the schema/contract, deterministic compiler, independent validator, and tests. A prompt change alone cannot add supported constraints.
