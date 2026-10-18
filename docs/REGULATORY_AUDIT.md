# BANK-PAY-001 modeled-policy and explanation audit

Audit date: 2026-10-17. Scope: configured synthetic internal policy, not interpretation of Singapore or Hong Kong law. Policy behavior and historical evidence were not changed. No GitHub push was performed.

## Finding and intended semantics

**AWS_HK is explicitly permitted by the current configuration.** `data_country: SG` is a policy lookup key paired with `classification: CONFIDENTIAL_PII`; it is not an equality constraint requiring physical hosting in Singapore. The matching policy permits AWS hosting and processing in both SG and HK. No exception or waiver mechanism exists. Unknown schema fields are rejected; missing or duplicate policies fail closed.

The user explicitly confirmed: “Keep the configured SG/HK permissions.” The implementation therefore matches the confirmed intended jurisdiction allowlists. Physical SG-only hosting/processing would be a different policy, which the current configuration does not express. Furthermore, SG-only would make the current four-environment application infeasible because nonproduction is independently required to run in HK. Tests demonstrate this conflict without weakening either constraint.

## Application and site facts

`config/application.yaml:3` defines BANK-PAY-001, PAYMENTS, CRITICAL, MATERIAL, SG CONFIDENTIAL_PII, PROD/DEV/SIT/UAT. Each environment needs 32 vCPU, 128 GB RAM, 0 GPU and 2 TB storage; required services are COMPUTE, DATABASE, STORAGE, MESSAGING and NETWORKING. Dedicated local DR has all ratios 1.0, RTO <=60 minutes and RPO <=15 minutes. SHARED-ID-001 has a maximum p95 dependency latency of 30 ms.

`config/policies/regulatory.yaml:6` matches the requirement; lines 8–10 permit AWS and SG/HK hosting/processing. MATERIAL approval is configured APPROVED at line 19. These are illustrative inputs, not evidence of actual organizational approval.

`config/infrastructure/sites.yaml:32` defines AWS_HK: provider AWS, region/country HK, approved, verified HA, two independent failure domains, verified recovery RTO 30/RPO 5 minutes and scaling. The default service list supplies all required categories. Processing country is omitted: the documented implementation defaults it to hosting country (HK). No hidden SG processing assumption is used.

`config/infrastructure/capacity.yaml:6` gives residual capacity 512 vCPU, 2048 GB RAM, 8 GPU, 100 TB. Aggregate four-environment plus dedicated-DR usage is 160 vCPU, 640 GB RAM, 0 GPU, 10 TB. Both reserved and simultaneous peak loads fit. These are modeled residual values, not live capacity measurements.

`config/infrastructure/costs.yaml` supplies AWS_HK fixed USD 190/month and USD 15/vCPU-month, licensing 100/month and operations 150/month. With DR included, `(160*15+190+100+150)*36 = USD 102,240`. Budget is disabled. AWS_SG has fixed 200/month and CPU 16/month. `config/policies/dependencies.yaml` places the identity dependency at AWS_HK through the explicit portfolio: HK→HK is 5 ms; SG→HK is 25 ms. Both meet 30 ms.

## Enforcement trace

Line references below identify the current implementation; functions provide stable anchors.

| Requirement | Config / parsed field | Compiler or filter | Independent check | Failure |
|---|---|---|---|---|
| Residency / regulatory eligibility | application data_requirements, regulatory policies; `schema.py:17` DataRequirement, `schema.py:104` Policy | `feasibility.py:8` site_reasons matches country + classification at 14–19; `direct.py:19` preprocess removes disallowed domains; build at 90 creates variables only for eligible sites | `validation.py:4` validate, lines 48–55 independently finds exactly one policy and checks provider, hosting and effective processing country | POLICY_DENIAL or missing-policy reason; excluded variable; infeasible if no complete assignment |
| Complete environment placement | Application.environments (`schema.py:39`) | `direct.py:93` complete exactly-one constraint; `feasibility.py:12` nonproduction HK | `validation.py:14` exact environment set; 46–47 nonproduction HK | Mismatch or NONPROD_REQUIRES_HK |
| Residual capacity | Capacity reservation mode/default/overrides; Application demand/peak/DR ratios | `direct.py:52` coefficients; 95–99 aggregate reserved and peak constraints | `validation.py:38` reservation choice; 66–75 independently aggregates and bounds usage | CAPACITY_EXCEEDED; infeasible |
| Recovery / local DR | Application.dr and Site.recovery/HA/domains (`schema.py:25` DR) | `feasibility.py:23` PROD HA/recovery/scaling filter; `direct.py:196` extract ties DR to PROD; coefficients include DR | `validation.py:20` same site/provider/region, 23–29 HA/recovery/scaling, 68–69 DR capacity | DR_SAME_SITE_PROVIDER_REGION_REQUIRED, RECOVERY_EVIDENCE_REQUIRED, domain/scaling failure |
| Services | required_service_categories and site defaults/overrides | `feasibility.py:20` subset filter | `validation.py:56` subset check | MISSING_SERVICE |
| Dependencies and latency | Application.dependencies, explicit portfolio, latency matrix | `config.py:65` reference validation; `feasibility.py:35` fixed-target matrix and upper bound; `direct.py:128` selected-pair constraints, 137 objective latency | `validation.py:60` target lookup and edge bound in every environment | Missing evidence / LATENCY_NOT_VALIDATED |
| Materiality approval | Regulatory.materiality (`schema.py:116`) | `direct.py:23` preprocessing blocks denied/missing; pending can only be conditional remediation | `validation.py:30` independent approval check | DENIED/missing rejected; pending CONDITIONAL, not recommended |
| Budget | Cost.budget | `direct.py:109` TCO, 112 hard_budget | `validation.py:76` independently computes TCO; 78 upper bound | BUDGET_EXCEEDED; infeasible |

`config.py:25` load hashes raw inputs and parses strict schema models; `config.py:50` cross_validate rejects duplicate policy keys at 59. `schema.py:5` Strict forbids unknown fields. There is no environment-specific residency exemption. Every environment receives every application data requirement. DR inherits the PROD site; moving DR elsewhere is rejected independently. The validator does not import the eligibility filter or compiler, and its country/provider membership tests are equivalent for schema-valid configurations.

AI compact specifications pass through `demo_spec.py:68` compile_spec to the trusted formulation. AI cannot invent a residency exception. Both execution modes undergo independent validation in `demo.py:229` before recommendation.

## Existing-artifact audit before implementation

Inspected prior run `demo-ba4cc47d8d064fc4b8288acc24d67aef` in the independent fresh-validation workspace.

| Artifact | Existing information | Gap |
|---|---|---|
| recommendation.json / explanation.json | Selected sites, metrics, generic regulatory/recovery PASS, capacity headroom, recovery facts, latency edges, site reason codes, one feasible alternative, mode and genuine-inference flag | No per-environment matching allowlist; no explicit processing-country fallback; no selected weighted contributions |
| summary.md | Status, source, fallback, placement/metrics/errors JSON | Did not explain eligibility, preference, policy or alternatives |
| reference solver.json | OPTIMAL, gap zero, incumbent/bound, extrema, model sizes, solve calls | Needed connection to independent metrics and user-facing tradeoffs |
| validation.json | DEPLOYABLE, independent metrics/loads, violations | Success did not enumerate each satisfied requirement and actual value |
| input_snapshot/*.yaml | Exact effective source inputs | User had to manually trace lookup and defaults |
| provenance.json / COMPLETE.json | Source/input provenance and artifact hashes | Integrity metadata alone does not establish policy semantics or real-world compliance |

No enforcement defect was found that accounts for AWS_HK. The identified defects are misleading potential interpretation of `data_country`, insufficient explicit policy evidence in the presentation, and incomplete disclosure of alternative display/enumeration limits. The SG-only/nonproduction-HK conflict is an existing model limitation, not repaired silently.

## Implemented explanations

`src/placement_explanation.py:6` build derives structured checks from parsed inputs and reruns the independent validator against selected placement and metrics. `render` writes deterministic Markdown, without generated prose. `src/demo.py` writes `constraint_audit.json` and `placement_explanation.md` before sealing the output. Failed/infeasible runs do not receive fabricated PASS checks; invalid report generation fails closed. The same code serves reference and AI-assisted runs.

Each selected environment plus DR reports site/country/provider, policy lookup and actual hosting/processing jurisdiction, services and dependency evidence. Aggregate capacity, recovery/local DR, materiality and budget are explicit. Disabled budget is NOT_APPLICABLE. Evidence names refer to the run's snapshots and independent validation. Normalized components use pre-budget extrema and weights divided by their sum; constant ranges contribute zero.

Complete-placement alternatives include numeric cost/latency/exposure deltas and score differences. Equal scores are marked tied. Site-level hard rejection codes are explicitly distinguished from feasible complete placements; locally eligible does not imply globally feasible. Enumeration bounds and display truncation are disclosed, with no reasons invented for unlisted combinations. Inference provenance distinguishes genuine recorded generation from mocked/reference execution, retains model/revision and formulation provenance, and discloses fallback. No inference was performed in this audit.

## Reference result and report sample

The unchanged configured policy yields AWS_HK for PROD, DEV, SIT, UAT and dedicated local DR. Modeled TCO USD 102,240 over 36 months; p95 latency 5 ms. Gurobi OPTIMAL, gap 0; independent validator DEPLOYABLE.

| Objective | Weight | Range | Selected normalized value | Contribution |
|---|---:|---|---:|---:|
| TCO | 0.35 | 102240–111744 | 0 | 0 |
| Latency | 0.25 | 5–25 | 0 | 0 |
| Concentration | 0.20 | 0.75–1 | 1 | 0.20 |
| Blast radius | 0.20 | 1–1 | 0 | 0 |

Selected score 0.20. The other feasible complete placement uses AWS_SG for PROD/DR and AWS_HK for nonproduction: TCO 111744 (+9504), latency 25 (+20), concentration 0.75 (−0.25), blast radius 1 (unchanged), score 0.60. Its cost and latency penalties contribute +0.60, outweighing the −0.20 concentration improvement. These are the two feasible placements under the current inputs; the full bounded domain contains 10,000 assignments before pruning.

Sample check: `residency_and_policy / PROD`: requirement SG + CONFIDENTIAL_PII; actual AWS/HK/HK; configured AWS, hosting [SG,HK], processing [SG,HK]; PASS. Recovery: required 60/15 minutes, actual 30/5 verified; PASS. This establishes compliance with these modeled inputs only.

## Validation and limitations

Focused regression coverage includes hosting and processing SG-only restrictions in every environment, explicit HK permission, all-site compiler/validator agreement, cheaper/faster forbidden HK, four-environment infeasibility under SG-only, invalid DR/recovery/missing policy, both report modes (mocked AI), tampered-report rejection and bounded enumeration disclosure. Existing workflow tests remain intact. See the current test manifest for exact collection.

The user confirmed the configured SG/HK permissions; external regulatory approval remains outside this audit. Recovery and capacity are static asserted evidence, not live cloud verification. Local DR is same-site independent domains, not cross-region disaster recovery. Real OptiMind inference requires its verified runtime; mocked inference tests do not demonstrate live model behavior. Optimality is relative to the mathematical model and solver tolerances, not external legal or operational approval.

Final validation: **353 passed, 0 failed, 0 skipped** (15.05 seconds), including 18 new cases. Test source manifest and generated artifact hashes verified. Fresh run: `results/regulatory-audit/demo-9cbad6eb4c5a47f7a28c30b759c5723b/`, with 31 explicit constraint checks. Original research preservation check: 6,046 files before and after, zero hash or inventory changes. No GitHub push.
