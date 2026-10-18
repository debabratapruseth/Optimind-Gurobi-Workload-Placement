# Placement explanation

Configured synthetic policy only; not external regulatory approval.

Status: RECOMMENDED

## A. Selected placement

| Application | Environment | Site | Country | Provider |
|---|---|---|---|---|
| BANK-PAY-001 | PROD | AWS_HK | HK | AWS |
| BANK-PAY-001 | DEV | AWS_HK | HK | AWS |
| BANK-PAY-001 | SIT | AWS_HK | HK | AWS |
| BANK-PAY-001 | UAT | AWS_HK | HK | AWS |
| BANK-PAY-001 | DR | AWS_HK | HK | AWS |

## B. Modeled constraints

| Constraint / scope | Requirement | Actual | Rule | Status | Evidence |
|---|---|---|---|---|---|
| "site_approval / PROD" | true | true | "Site must be approved" | "PASS" | "input_snapshot/sites.yaml" |
| "residency_and_policy / PROD" | {"classification": "CONFIDENTIAL_PII", "data_country": "SG"} | {"hosting_country": "HK", "processing_country": "HK", "processing_country_defaulted": true, "provider": "AWS"} | {"approved_hosting_countries": ["SG", "HK"], "approved_processing_countries": ["SG", "HK"], "approved_providers": ["AWS"], "classification": "CONFIDENTIAL_PII", "data_country": "SG"} | "PASS" | ["input_snapshot/applications.yaml", "input_snapshot/regulatory.yaml", "input_snapshot/sites.yaml"] |
| "services / PROD" | ["COMPUTE", "DATABASE", "STORAGE", "MESSAGING", "NETWORKING"] | ["COMPUTE", "DATABASE", "STORAGE", "MESSAGING", "NETWORKING", "AI_ML"] | "All required services available" | "PASS" | "input_snapshot/sites.yaml" |
| "dependency_latency / PROD" | {"max_p95_latency_ms": 30.0, "target": "SHARED-ID-001"} | {"p95_ms": 5.0, "target_site": "AWS_HK"} | "Configured edge exists and p95 <= maximum" | "PASS" | ["input_snapshot/dependencies.yaml", "input_snapshot/existing_portfolio.yaml"] |
| "site_approval / DEV" | true | true | "Site must be approved" | "PASS" | "input_snapshot/sites.yaml" |
| "environment / DEV" | "HK" | "HK" | "Nonproduction requires HK" | "PASS" | "src/validation.py:validate" |
| "residency_and_policy / DEV" | {"classification": "CONFIDENTIAL_PII", "data_country": "SG"} | {"hosting_country": "HK", "processing_country": "HK", "processing_country_defaulted": true, "provider": "AWS"} | {"approved_hosting_countries": ["SG", "HK"], "approved_processing_countries": ["SG", "HK"], "approved_providers": ["AWS"], "classification": "CONFIDENTIAL_PII", "data_country": "SG"} | "PASS" | ["input_snapshot/applications.yaml", "input_snapshot/regulatory.yaml", "input_snapshot/sites.yaml"] |
| "services / DEV" | ["COMPUTE", "DATABASE", "STORAGE", "MESSAGING", "NETWORKING"] | ["COMPUTE", "DATABASE", "STORAGE", "MESSAGING", "NETWORKING", "AI_ML"] | "All required services available" | "PASS" | "input_snapshot/sites.yaml" |
| "dependency_latency / DEV" | {"max_p95_latency_ms": 30.0, "target": "SHARED-ID-001"} | {"p95_ms": 5.0, "target_site": "AWS_HK"} | "Configured edge exists and p95 <= maximum" | "PASS" | ["input_snapshot/dependencies.yaml", "input_snapshot/existing_portfolio.yaml"] |
| "site_approval / SIT" | true | true | "Site must be approved" | "PASS" | "input_snapshot/sites.yaml" |
| "environment / SIT" | "HK" | "HK" | "Nonproduction requires HK" | "PASS" | "src/validation.py:validate" |
| "residency_and_policy / SIT" | {"classification": "CONFIDENTIAL_PII", "data_country": "SG"} | {"hosting_country": "HK", "processing_country": "HK", "processing_country_defaulted": true, "provider": "AWS"} | {"approved_hosting_countries": ["SG", "HK"], "approved_processing_countries": ["SG", "HK"], "approved_providers": ["AWS"], "classification": "CONFIDENTIAL_PII", "data_country": "SG"} | "PASS" | ["input_snapshot/applications.yaml", "input_snapshot/regulatory.yaml", "input_snapshot/sites.yaml"] |
| "services / SIT" | ["COMPUTE", "DATABASE", "STORAGE", "MESSAGING", "NETWORKING"] | ["COMPUTE", "DATABASE", "STORAGE", "MESSAGING", "NETWORKING", "AI_ML"] | "All required services available" | "PASS" | "input_snapshot/sites.yaml" |
| "dependency_latency / SIT" | {"max_p95_latency_ms": 30.0, "target": "SHARED-ID-001"} | {"p95_ms": 5.0, "target_site": "AWS_HK"} | "Configured edge exists and p95 <= maximum" | "PASS" | ["input_snapshot/dependencies.yaml", "input_snapshot/existing_portfolio.yaml"] |
| "site_approval / UAT" | true | true | "Site must be approved" | "PASS" | "input_snapshot/sites.yaml" |
| "environment / UAT" | "HK" | "HK" | "Nonproduction requires HK" | "PASS" | "src/validation.py:validate" |
| "residency_and_policy / UAT" | {"classification": "CONFIDENTIAL_PII", "data_country": "SG"} | {"hosting_country": "HK", "processing_country": "HK", "processing_country_defaulted": true, "provider": "AWS"} | {"approved_hosting_countries": ["SG", "HK"], "approved_processing_countries": ["SG", "HK"], "approved_providers": ["AWS"], "classification": "CONFIDENTIAL_PII", "data_country": "SG"} | "PASS" | ["input_snapshot/applications.yaml", "input_snapshot/regulatory.yaml", "input_snapshot/sites.yaml"] |
| "services / UAT" | ["COMPUTE", "DATABASE", "STORAGE", "MESSAGING", "NETWORKING"] | ["COMPUTE", "DATABASE", "STORAGE", "MESSAGING", "NETWORKING", "AI_ML"] | "All required services available" | "PASS" | "input_snapshot/sites.yaml" |
| "dependency_latency / UAT" | {"max_p95_latency_ms": 30.0, "target": "SHARED-ID-001"} | {"p95_ms": 5.0, "target_site": "AWS_HK"} | "Configured edge exists and p95 <= maximum" | "PASS" | ["input_snapshot/dependencies.yaml", "input_snapshot/existing_portfolio.yaml"] |
| "site_approval / DR" | true | true | "Site must be approved" | "PASS" | "input_snapshot/sites.yaml" |
| "residency_and_policy / DR" | {"classification": "CONFIDENTIAL_PII", "data_country": "SG"} | {"hosting_country": "HK", "processing_country": "HK", "processing_country_defaulted": true, "provider": "AWS"} | {"approved_hosting_countries": ["SG", "HK"], "approved_processing_countries": ["SG", "HK"], "approved_providers": ["AWS"], "classification": "CONFIDENTIAL_PII", "data_country": "SG"} | "PASS" | ["input_snapshot/applications.yaml", "input_snapshot/regulatory.yaml", "input_snapshot/sites.yaml"] |
| "services / DR" | ["COMPUTE", "DATABASE", "STORAGE", "MESSAGING", "NETWORKING"] | ["COMPUTE", "DATABASE", "STORAGE", "MESSAGING", "NETWORKING", "AI_ML"] | "All required services available" | "PASS" | "input_snapshot/sites.yaml" |
| "dependency_latency / DR" | {"max_p95_latency_ms": 30.0, "target": "SHARED-ID-001"} | {"p95_ms": 5.0, "target_site": "AWS_HK"} | "Configured edge exists and p95 <= maximum" | "PASS" | ["input_snapshot/dependencies.yaml", "input_snapshot/existing_portfolio.yaml"] |
| "capacity / AWS_HK:cpu_vcpu" | {"reserved": 160.0, "simultaneous_peak": 160.0} | 512.0 | "Both aggregate loads <= residual capacity (includes DR)" | "PASS" | ["input_snapshot/capacity.yaml", "recommendation.json#independent_validation"] |
| "capacity / AWS_HK:ram_gb" | {"reserved": 640.0, "simultaneous_peak": 640.0} | 2048.0 | "Both aggregate loads <= residual capacity (includes DR)" | "PASS" | ["input_snapshot/capacity.yaml", "recommendation.json#independent_validation"] |
| "capacity / AWS_HK:gpu_count" | {"reserved": 0.0, "simultaneous_peak": 0.0} | 8.0 | "Both aggregate loads <= residual capacity (includes DR)" | "PASS" | ["input_snapshot/capacity.yaml", "recommendation.json#independent_validation"] |
| "capacity / AWS_HK:storage_tb" | {"reserved": 10.0, "simultaneous_peak": 10.0} | 100.0 | "Both aggregate loads <= residual capacity (includes DR)" | "PASS" | ["input_snapshot/capacity.yaml", "recommendation.json#independent_validation"] |
| "dedicated_local_dr / DR" | {"cpu_ratio": 1.0, "gpu_ratio": 1.0, "mode": "DEDICATED", "ram_ratio": 1.0, "rpo_minutes": 15.0, "rto_minutes": 60.0, "storage_ratio": 1.0} | {"failure_domain_contract": "INDEPENDENT_LOCAL_DOMAINS", "ha_verified": true, "independent_failure_domains": 2, "site": "AWS_HK"} | "Same site/provider/region, independent local domains; DR loads included in capacity" | "PASS" | ["input_snapshot/applications.yaml", "input_snapshot/sites.yaml"] |
| "recovery / PROD/DR" | {"cpu_ratio": 1.0, "gpu_ratio": 1.0, "mode": "DEDICATED", "ram_ratio": 1.0, "rpo_minutes": 15.0, "rto_minutes": 60.0, "storage_ratio": 1.0} | {"rpo_minutes": 5.0, "rto_minutes": 30.0, "scaling_verified": true, "verified": true} | "Verified RTO/RPO <= requested; reduced DR requires verified scaling" | "PASS" | "input_snapshot/sites.yaml" |
| "materiality_approval / BANK-PAY-001" | "MATERIAL" | {"approval_required": true, "approval_status": "APPROVED", "lead_time_days": 30} | "Required approval must be APPROVED" | "PASS" | "input_snapshot/regulatory.yaml" |
| "budget / BANK-PAY-001" | {"enabled": false, "max_total_tco_usd": null} | 102240.0 | "TCO <= enabled budget" | "NOT_APPLICABLE" | "input_snapshot/cost.yaml" |

## C. Objective and selection

```json
{
  "components": {
    "blast_radius": {
      "contribution": 0.0,
      "normalized": 0.0
    },
    "concentration": {
      "contribution": 0.2,
      "normalized": 1.0
    },
    "latency": {
      "contribution": 0.0,
      "normalized": 0.0
    },
    "tco": {
      "contribution": 0.0,
      "normalized": 0.0
    }
  },
  "metrics": {
    "blast_radius": 1.0,
    "concentration": 1.0,
    "latency": 5.0,
    "tco": 102240.0
  },
  "normalization_basis": "Pre-budget feasible extrema; constant components normalize to zero",
  "ranges": {
    "blast_radius": [
      1.0,
      1.0
    ],
    "concentration": [
      0.75,
      1.0
    ],
    "latency": [
      5.0,
      25.0
    ],
    "tco": [
      102240.0,
      111744.0
    ]
  },
  "score": 0.2,
  "weights": {
    "blast_radius": 0.2,
    "concentration": 0.2,
    "latency": 0.25,
    "tco": 0.35
  }
}
```

## D. Alternatives and screening

```json
{
  "budget_rejection_count": 0,
  "capacity_rejection_count": 0,
  "capacity_rejection_examples": [],
  "display_limit_applies": true,
  "displayed_alternatives": [
    {
      "classification": "FEASIBLE_LOWER_RANKED",
      "metrics": {
        "blast_radius": 1.0,
        "concentration": 0.75,
        "latency": 25.0,
        "tco": 111744.0
      },
      "normalized_objective": 0.6,
      "placement": {
        "application_id": "BANK-PAY-001",
        "dr_site_id": "AWS_SG",
        "environments": {
          "DEV": "AWS_HK",
          "PROD": "AWS_SG",
          "SIT": "AWS_HK",
          "UAT": "AWS_HK"
        },
        "failure_domain_contract": "INDEPENDENT_LOCAL_DOMAINS"
      },
      "score_delta": 0.39999999999999997,
      "tradeoff_vs_selected": {
        "blast_radius": 0.0,
        "concentration": -0.25,
        "latency": 20.0,
        "tco": 9504.0
      }
    }
  ],
  "enumeration_complete": true,
  "feasible_count_including_selected": 2,
  "global_rejections": [],
  "not_evaluated_reason": null,
  "scope": "Site screening is not full-placement ranking. Examples may be truncated; unlisted combinations have no invented rejection reason.",
  "site_screening": [
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "PROD",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "POLICY_DENIAL"
      ],
      "site": "AWS_UK"
    },
    {
      "classification": "LOCAL_CHECKS_PASSED_NOT_A_COMPLETE_PLACEMENT",
      "environment": "PROD",
      "reasons": [],
      "site": "AWS_SG"
    },
    {
      "classification": "LOCAL_CHECKS_PASSED_NOT_A_COMPLETE_PLACEMENT",
      "environment": "PROD",
      "reasons": [],
      "site": "AWS_HK"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "PROD",
      "reasons": [
        "POLICY_DENIAL"
      ],
      "site": "AZURE_HK"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "PROD",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "POLICY_DENIAL"
      ],
      "site": "AZURE_UK"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "PROD",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "POLICY_DENIAL"
      ],
      "site": "AZURE_IN"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "PROD",
      "reasons": [
        "POLICY_DENIAL"
      ],
      "site": "GLOBAL_DC_HK"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "PROD",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "POLICY_DENIAL"
      ],
      "site": "GLOBAL_DC_LONDON"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "PROD",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "POLICY_DENIAL"
      ],
      "site": "COUNTRY_DC_IN"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "PROD",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "POLICY_DENIAL"
      ],
      "site": "COUNTRY_DC_LONDON"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "DEV",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "NONPROD_REQUIRES_HK",
        "POLICY_DENIAL"
      ],
      "site": "AWS_UK"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "DEV",
      "reasons": [
        "NONPROD_REQUIRES_HK"
      ],
      "site": "AWS_SG"
    },
    {
      "classification": "LOCAL_CHECKS_PASSED_NOT_A_COMPLETE_PLACEMENT",
      "environment": "DEV",
      "reasons": [],
      "site": "AWS_HK"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "DEV",
      "reasons": [
        "POLICY_DENIAL"
      ],
      "site": "AZURE_HK"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "DEV",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "NONPROD_REQUIRES_HK",
        "POLICY_DENIAL"
      ],
      "site": "AZURE_UK"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "DEV",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "NONPROD_REQUIRES_HK",
        "POLICY_DENIAL"
      ],
      "site": "AZURE_IN"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "DEV",
      "reasons": [
        "POLICY_DENIAL"
      ],
      "site": "GLOBAL_DC_HK"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "DEV",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "NONPROD_REQUIRES_HK",
        "POLICY_DENIAL"
      ],
      "site": "GLOBAL_DC_LONDON"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "DEV",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "NONPROD_REQUIRES_HK",
        "POLICY_DENIAL"
      ],
      "site": "COUNTRY_DC_IN"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "DEV",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "NONPROD_REQUIRES_HK",
        "POLICY_DENIAL"
      ],
      "site": "COUNTRY_DC_LONDON"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "SIT",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "NONPROD_REQUIRES_HK",
        "POLICY_DENIAL"
      ],
      "site": "AWS_UK"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "SIT",
      "reasons": [
        "NONPROD_REQUIRES_HK"
      ],
      "site": "AWS_SG"
    },
    {
      "classification": "LOCAL_CHECKS_PASSED_NOT_A_COMPLETE_PLACEMENT",
      "environment": "SIT",
      "reasons": [],
      "site": "AWS_HK"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "SIT",
      "reasons": [
        "POLICY_DENIAL"
      ],
      "site": "AZURE_HK"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "SIT",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "NONPROD_REQUIRES_HK",
        "POLICY_DENIAL"
      ],
      "site": "AZURE_UK"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "SIT",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "NONPROD_REQUIRES_HK",
        "POLICY_DENIAL"
      ],
      "site": "AZURE_IN"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "SIT",
      "reasons": [
        "POLICY_DENIAL"
      ],
      "site": "GLOBAL_DC_HK"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "SIT",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "NONPROD_REQUIRES_HK",
        "POLICY_DENIAL"
      ],
      "site": "GLOBAL_DC_LONDON"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "SIT",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "NONPROD_REQUIRES_HK",
        "POLICY_DENIAL"
      ],
      "site": "COUNTRY_DC_IN"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "SIT",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "NONPROD_REQUIRES_HK",
        "POLICY_DENIAL"
      ],
      "site": "COUNTRY_DC_LONDON"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "UAT",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "NONPROD_REQUIRES_HK",
        "POLICY_DENIAL"
      ],
      "site": "AWS_UK"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "UAT",
      "reasons": [
        "NONPROD_REQUIRES_HK"
      ],
      "site": "AWS_SG"
    },
    {
      "classification": "LOCAL_CHECKS_PASSED_NOT_A_COMPLETE_PLACEMENT",
      "environment": "UAT",
      "reasons": [],
      "site": "AWS_HK"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "UAT",
      "reasons": [
        "POLICY_DENIAL"
      ],
      "site": "AZURE_HK"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "UAT",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "NONPROD_REQUIRES_HK",
        "POLICY_DENIAL"
      ],
      "site": "AZURE_UK"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "UAT",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "NONPROD_REQUIRES_HK",
        "POLICY_DENIAL"
      ],
      "site": "AZURE_IN"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "UAT",
      "reasons": [
        "POLICY_DENIAL"
      ],
      "site": "GLOBAL_DC_HK"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "UAT",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "NONPROD_REQUIRES_HK",
        "POLICY_DENIAL"
      ],
      "site": "GLOBAL_DC_LONDON"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "UAT",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "NONPROD_REQUIRES_HK",
        "POLICY_DENIAL"
      ],
      "site": "COUNTRY_DC_IN"
    },
    {
      "classification": "HARD_INFEASIBLE",
      "environment": "UAT",
      "reasons": [
        "MISSING_LATENCY_EVIDENCE",
        "NONPROD_REQUIRES_HK",
        "POLICY_DENIAL"
      ],
      "site": "COUNTRY_DC_LONDON"
    }
  ]
}
```

## E. AI provenance

```json
{
  "fallback_reason": null,
  "fallback_used": false,
  "formulation": {
    "ai_role": "FORMULATION_SELECTION",
    "algebra_author": "TRUSTED_COMPILER",
    "constraints": 111,
    "expanded_ir_hash": "ce975e411ee3e082cc1fc2aa3097ec0051178ab7649b5c7f49cf277304c377eb",
    "policy_source": "IMMUTABLE_PROBLEM_CONTRACT",
    "specification": {
      "application_id": "BANK-PAY-001",
      "environment_order": [
        "PROD",
        "DEV",
        "SIT",
        "UAT"
      ],
      "formulation": "DIRECT_ASSIGNMENT",
      "objective_encoding": "INLINE",
      "problem_hash": "093f4113ffb801c1a46f51f97aa6ac58d17b29c020b3806fe0cedeb3133a602d",
      "spec_version": "1.0"
    },
    "variables": 21
  },
  "genuine_optimind_inference": true,
  "invocation_evidence": "Recorded genuine generation",
  "mode": "AI_ASSISTED",
  "model": {
    "model_id": "microsoft/OptiMind-SFT",
    "precision": "BF16",
    "provider": "HUGGINGFACE",
    "quantization": "NONE",
    "revision": "817e06666a39155f9352d00354b3227d230da46d",
    "trust_remote_code": false
  },
  "source": "OPTIMIND_SPEC_TRUSTED_MILP"
}
```

## F. Independent validation

```json
{
  "independent_metrics": {
    "blast_radius": 1.0,
    "concentration": 1.0,
    "latency": 5.0,
    "tco": 102240.0
  },
  "independent_tco": 102240.0,
  "reasons": [],
  "reserved_capacity": {
    "AWS_HK": {
      "cpu_vcpu": 160.0,
      "gpu_count": 0.0,
      "ram_gb": 640.0,
      "storage_tb": 10.0
    }
  },
  "simultaneous_peak_capacity": {
    "AWS_HK": {
      "cpu_vcpu": 160.0,
      "gpu_count": 0.0,
      "ram_gb": 640.0,
      "storage_tb": 10.0
    }
  },
  "status": "DEPLOYABLE",
  "valid": true
}
```

## Solver certificate

```json
{
  "best_bound": 0.20000000000000107,
  "incumbent": 0.20000000000000107,
  "license": "FREE_SIZE_LIMITED",
  "license_verified_from_startup_log": true,
  "mip_gap": 0.0,
  "model_counts": {
    "general_constraints": 0,
    "linear_constraints": 111,
    "quadratic_constraints": 0,
    "quadratic_objective_terms": 0,
    "sos_constraints": 0,
    "variables": 21
  },
  "optimality_proven": true,
  "runtime_seconds": 0.0002570152282714844,
  "solution_count": 1,
  "status": "OPTIMAL",
  "status_code": 2
}
```

Optimality applies only to the implemented model and solver tolerances. Independent validation checks configured modeled requirements, not real-world compliance.
