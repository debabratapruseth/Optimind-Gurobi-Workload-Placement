# Single-application migration report

Date: 17 October 2026 (Asia/Singapore). Local changes only: no commit, push, release, or history rewrite was performed.

## Implementation

- Added `src.pipeline` as the public single-card entry point. REFERENCE_FALLBACK is explicit/default; AI_ASSISTED requires matching version-3 scenario runtime evidence and never automatically falls back.
- Reused strict input schemas, the existing problem contract, deterministic compiler, Gurobi implementation, and independent audit. The mathematical compiler/constraint/metric/validator modules are unchanged.
- Added the BANK-PAY-001 card and separated infrastructure, policies, optimization, AI and internal runtime configuration. Retained DR requirements in the existing application/site schemas.
- Required an explicit two-application fixed inventory. This avoids the known generated-portfolio extra-field incompatibility rather than weakening the contract or silently discarding metadata.
- Runtime verification now validates the actual single-application scenario rather than hardcoded public benchmark paths. The full regression suite remains mandatory; source, test, hardware, Colab, Drive, package, model-size and equivalence guards remain in place. Input changes invalidate the receipt.
- Added an opt-in Colab notebook and rewrote end-user documentation.

## Release directory tree

```text
optimind-gurobi-workload-placement/
├── README.md
├── LICENSE
├── LICENSE_REVIEW_REQUIRED.md
├── MIGRATION_REPORT.md
├── requirements.txt
├── requirements-inference-transformers.txt
├── config/
│   ├── application.yaml
│   ├── scenario.yaml
│   ├── optimind.yaml
│   ├── infrastructure/{sites,capacity,costs,portfolio}.yaml
│   ├── policies/{regulatory,dependencies}.yaml
│   ├── optimization/{objectives,solver}.yaml
│   └── runtime/{baseline_ai,generator,reference,verification}.yaml
├── src/
│   ├── pipeline.py
│   ├── demo.py
│   ├── formulation_check.py
│   ├── runtime_verification.py
│   └── existing loaders, compiler, solver, validation and inference modules
├── notebooks/run_pipeline.ipynb
├── docs/{INPUTS,ARCHITECTURE,AI_RUNTIME,VALIDATION,SECURITY_REVIEW}.md
└── tests/
    ├── test_pipeline.py
    ├── existing adapted mathematical/inference/security regressions
    ├── suite_manifest.json
    ├── fixtures/{config,notebooks,phase2a,phase2b}/
    └── support/{optimind_experiment,prepare_inference}.py
```

Ignored local virtual environments/caches are not release contents. No generated run output is included.

## Tests and results

See [Validation](docs/VALIDATION.md) for exact results and limitations. Both working and fresh-environment suites pass 335 tests without skips. Fresh dependency installation, dependency consistency, the reference CLI, input resolution, problem construction, output generation, and manifest integrity were checked. The reference result is all environments/local DR at AWS_HK, modeled USD 102,240 / 5 ms, OPTIMAL with zero gap, 21 variables / 111 constraints, independently DEPLOYABLE. This is not an AI inference result.

All original test cases remain represented. Public benchmark dependencies were moved into self-contained test fixtures, and the single fixture was changed to TEST-APP with independent resource values and freshly generated test-only algebra. Research inference harnesses and notebook controls were moved to test support to preserve security/failure-path coverage without presenting them as user entry points. A compile-only notebook test now targets the new public notebook.

## Removal and retention decisions

Before cleanup, the new pipeline tests and migrated full suite passed (331 cases at that stage). References to each removed tracked path were inventoried; old public docs were replaced and code/test references migrated. The subsequent clean-tree test run caught one compile-only reference to a removed notebook; it was redirected to the new public notebook without dropping the test. Final 335-case runs pass.

Retained reusable direct/enumeration/joint mathematical routines because deleting them would discard correctness coverage and risk shared behavior. The public pipeline rejects multiple new applications; retaining these internals is not new multi-application feature development. Retained strict IR parsing, inference worker guards, runtime manifests, independent equivalence, and regression harnesses. `src.formulation_check` replaces the research-named trusted conversion runner.

Removed the old public benchmark/experiment configurations, old notebooks and research orchestration entry points, obsolete publication reports and documentation, old serialized single-fixture algebra, and the publication copy of historical evidence. Historical evidence was neither edited nor regenerated.

## Preservation and Git history

Before removing the publication copy, all 48 successful-run files were verified byte-for-byte against the durable copy in the original research project's `docs/demo_publication/evidence/` directory. Its COMPLETE manifest remains valid. A before/after SHA-256 comparison confirmed all 6,046 regular files in the original research directory unchanged. No original-project operation wrote files there. A pre-migration publication archive was also retained locally outside this release tree.

The removal applies to the working/release tree only. Historical evidence remains in earlier Git commits and the previously published remote history. No attempt was made to purge it, rewrite history, or modify the remote.

## Remaining limitations and blockers

The local reference workflow is verified. Genuine BANK-PAY inference and a live Colab run of the new notebook remain unverified. The documented procedure preserves the runtime guards; mocked AI tests are clearly identified. Remote GitHub remains the earlier version until the owner reviews and publishes these local changes.

The existing MIT license is unchanged. Comprehensive security review, external license eligibility, and publication-rights clearance are not claimed; this migration is not published or declared production-ready. A credential-pattern scan found no matching tokens, private keys, or embedded credential URLs in the candidate files. Input data, costs, policies, and recovery capabilities remain synthetic.

## Removed tracked paths

The following paths are absent from the new working tree (migrated coverage and replacements are described above):

- `GITHUB_PACKAGING_REPORT.md`
- `README_TECHNICAL.md`
- `README_VALIDATION_REPORT.md`
- `config/ai/inference.yaml`
- `config/ai/optimind_v2.yaml`
- `config/applications/existing_portfolio.yaml`
- `config/applications/new_applications.yaml`
- `config/benchmarks/complex.yaml`
- `config/benchmarks/complex_direct.yaml`
- `config/benchmarks/inputs/complex_applications.yaml`
- `config/benchmarks/inputs/complex_capacity.yaml`
- `config/benchmarks/inputs/complex_objectives.yaml`
- `config/benchmarks/inputs/cost.yaml`
- `config/benchmarks/inputs/dependencies.yaml`
- `config/benchmarks/inputs/generator.yaml`
- `config/benchmarks/inputs/medium_applications.yaml`
- `config/benchmarks/inputs/medium_capacity.yaml`
- `config/benchmarks/inputs/medium_objectives.yaml`
- `config/benchmarks/inputs/portfolio.yaml`
- `config/benchmarks/inputs/regulatory.yaml`
- `config/benchmarks/inputs/sites.yaml`
- `config/benchmarks/inputs/small_applications.yaml`
- `config/benchmarks/inputs/small_capacity.yaml`
- `config/benchmarks/inputs/small_objectives.yaml`
- `config/benchmarks/inputs/solver.yaml`
- `config/benchmarks/medium.yaml`
- `config/benchmarks/medium_direct.yaml`
- `config/benchmarks/small.yaml`
- `config/benchmarks/small_direct.yaml`
- `config/capacity/capacity.yaml`
- `config/cost/tco.yaml`
- `config/datasets/generator.yaml`
- `config/demo/ai_small.yaml`
- `config/demo/optimind.yaml`
- `config/demo/small.yaml`
- `config/dependencies/latency.yaml`
- `config/experiments/experiment.yaml`
- `config/experiments/experiment_recovery_demo.yaml`
- `config/infrastructure/sites_recovery_demo.yaml`
- `config/regulatory/policies.yaml`
- `config/research/phase2a.yaml`
- `config/solver/gurobi.yaml`
- `docs/ADDING_APPLICATIONS.md`
- `docs/BUSINESS_PROBLEM.md`
- `docs/CUSTOMIZING_CONSTRAINTS.md`
- `docs/EXTENDING_OPTIMIZATION.md`
- `docs/GUROBI_OPTIMIZATION.md`
- `docs/INPUT_RULES.md`
- `docs/LIMITATIONS.md`
- `docs/MATHEMATICAL_MODEL.md`
- `docs/OPTIMIND_ROLE.md`
- `docs/REPRODUCIBILITY.md`
- `docs/RESULTS.md`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/COMPLETE.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/ai_input.yaml`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/checkpoint.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/compilation_provenance.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/expanded_ir.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/generation.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/hardware.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/inference.log`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/preflight.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/problem.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/prompt.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/prompt_tokens.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/raw_response.txt`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/rendered_prompt.txt`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/request.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/response.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/settings.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/spec_validation.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/specification.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/text_environment.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/trusted_expansion/solver.log`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/validation/compiled/audit_solves.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/validation/compiled/compiled.lp`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/validation/compiled/solver.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/validation/compiled/solver.log`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/validation/trusted_recognition/solver.log`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/validation/validation.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/worker_preflight.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/worker_request.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/ai/worker_result.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/demo_config.yaml`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/explanation.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/input_snapshot/ai.yaml`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/input_snapshot/applications.yaml`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/input_snapshot/capacity.yaml`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/input_snapshot/cost.yaml`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/input_snapshot/dataset_generator.yaml`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/input_snapshot/dependencies.yaml`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/input_snapshot/existing_portfolio.yaml`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/input_snapshot/experiment.yaml`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/input_snapshot/objectives.yaml`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/input_snapshot/regulatory.yaml`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/input_snapshot/sites.yaml`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/input_snapshot/solver.yaml`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/provenance.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/recommendation.json`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/run.log`
- `evidence/successful_demo/demo-f984f814bfed415f849a16079713e719/summary.md`
- `notebooks/run_demo.ipynb`
- `notebooks/run_experiment.ipynb`
- `notebooks/run_optimind.ipynb`
- `src/optimind_experiment.py`
- `src/phase2_demo.py`
- `src/prepare_inference.py`
- `tests/fixtures/phase2a/small_problem.json`
- `tests/fixtures/phase2a/small_trusted_ir.json`
