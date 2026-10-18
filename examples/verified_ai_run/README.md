# Verified OptiMind-SFT + Gurobi example

## Results

AI_ASSISTED; genuine inference true; fallback false; RECOMMENDED. Model `microsoft/OptiMind-SFT`, Transformers BF16 without quantization. OptiMind selected DIRECT_ASSIGNMENT / INLINE; trusted code authored the algebra and Gurobi 13.0.2 solved it. This is not an AI-generated unrestricted optimization program.

| Placement | 36-month TCO (USD) | Dependency p95 (ms) | Weighted score |
|---|---:|---:|---:|
| AWS_HK for PROD, DEV, SIT, UAT and local DR | 102240 | 5 | 0.20 |
| AWS_SG for PROD/DR; AWS_HK for DEV/SIT/UAT | 111744 | 25 | 0.60 |

The winner has concentration 1.0 and blast radius 1.0; the alternative has 0.75 and 1.0. Lower score is better. There are two feasible complete placements in the bounded equivalence audit. The compiled MILP has 21 variables and 111 linear constraints; Gurobi reports OPTIMAL, gap 0, and incumbent/bound 0.20000000000000107 (floating-point equivalent to 0.20). Independent validation is DEPLOYABLE with no violations. The 31 constraint entries contain 30 PASS and one NOT_APPLICABLE (disabled budget).

The synthetic SG/CONFIDENTIAL_PII policy explicitly permits AWS hosting and processing in SG or HK. This result establishes modeled feasibility, not external regulatory approval, production readiness, or a cloud price quote.

## Evidence and integrity

- [Recommendation](recommendation.json), [human-readable explanation](placement_explanation.md), and [constraint audit](constraint_audit.json).
- [Structured problem](problem.json), [generation metadata](ai/generation.json), and [selected specification](ai/specification.json).
- [Compiler provenance](ai/compilation_provenance.json), [specification equivalence](ai/spec_validation.json), [independent validation](ai/validation/validation.json), and [solver record](ai/validation/compiled/solver.json).
- [Review findings and limitations](verification.json); [public-file hashes](PUBLIC_MANIFEST.json).

