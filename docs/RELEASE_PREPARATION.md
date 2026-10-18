# Release preparation and runtime cleanup

Date: 17 October 2026 (Asia/Singapore). Local preparation only; no commit, push, or new genuine AI inference. Optimization mathematics, policies, source code and tests were not changed in this task.

## Landing page and inspection

The README now covers architecture; clone/configure/run; every public input; both execution modes; the verified AI experiment; why AWS_HK won; explanation/audit artifacts; limitations and release status. Links use repository-relative paths. Its results are sourced from the reviewed public example and original downloaded AI artifacts, not fabricated or inferred from mocked tests.

Inspected the current README, migration report, configuration, pipeline, notebook, AI runtime and regulatory audit docs, results, tests, ignore rules and licensing/security notices. README_TECHNICAL.md was already deleted in the earlier uncommitted migration; its HEAD version was inspected for historical context, not restored as current documentation. It describes the old SMALL-1 experiment and is not authoritative for BANK-PAY-001.

Reference requirements are pinned in requirements.txt. Python 3.14.5 was used for local validation; the AI artifacts record Python 3.13.15. No broad compatibility range is declared. Reference CLI requires Gurobi but no GPU or HF token. AI requires the pinned text stack, HF_TOKEN, verified Colab GPU runtime and matching scenario evidence. The notebook's shared verification gate requires GPU readiness even with USE_AI=False; CPU-only reference users should use the CLI.

The release notebook had USE_AI=True saved. Restored USE_AI=False, retained RUN_PIPELINE=False, and cleared outputs/execution counters. Launch behavior and validation implementation remain unchanged. AI_RUNTIME and VALIDATION now acknowledge the genuine Colab evidence while retaining its documented limits.

## Classification and deletion inventory

| Category | Paths | Decision |
|---|---|---|
| Essential source/config | src/, config/, requirements files | Retained; no source or mathematical changes |
| Runtime configuration templates | config/runtime/baseline_ai.yaml, generator.yaml, reference.yaml, verification.yaml | Retained: referenced by scenario loading, demo defaults and formulation verification; not ignored |
| Documentation | README, docs/, MIGRATION_REPORT.md, licensing/security files | Retained; current documentation updated |
| Tests and fixtures | tests/, tests/fixtures/, tests/support/ | Retained, test sources and manifest unchanged |
| Public verified evidence | examples/verified_ai_run/ | All 13 files retained byte-for-byte, including its public manifest |
| Original downloaded evidence | results/verified_ai_run/ | All 51 files retained unchanged; already Git-ignored |
| Prior reference evidence | results/regulatory-audit/ | Retained unchanged because REGULATORY_AUDIT.md explicitly references it |
| Temporary caches | .pytest_cache/, tests/__pycache__/, tests/support/__pycache__/, src/__pycache__/ | Removed 62 regenerable files after tests; zero tracked files |
| Virtual environment | .venv/ | Retained for the user's local execution; ignored |
| Original research | Separate original research directory and historical evidence | Not modified or deleted |

A complete cache-file inventory with pre-removal hashes was recorded locally before deletion. No additional tracked deletions were proposed or performed. No Colab staging directories or notebook checkpoints requiring deletion were found in the repository. Existing pending tracked deletions belong to the earlier migration and were not expanded or reversed. No ambiguous or referenced evidence was deleted.

The original downloaded run remains in place. Its previously reported Drive origin is not a new verification that the remote copy still exists; no deletion depends on that assumption.

## Ignore rules

Existing rules exclude results/, local environments, model caches, Python caches/bytecode, environment secrets, Gurobi license files, and launch locks. Added .ipynb_checkpoints/ and an exception for the distributable .env.example template. Existing config/runtime templates and examples/ remain visible to Git. Ignore rules do not remove already tracked files.

## Validation

- Full suite: **353 passed, 0 failed, 0 skipped**, in 14.88 seconds. Test source hashes match the existing suite manifest.
- Fresh reference run: `demo-386bfb07fba644228a17d3f12f3cbbfe`, in a separate temporary validation output directory rather than the evidence folders.
- Result: RECOMMENDED / REFERENCE_FALLBACK; no genuine inference; AWS_HK for PROD/DEV/SIT/UAT and dedicated local DR; TCO USD 102,240; latency 5 ms; concentration 1.0; blast radius 1.0.
- Solver: OPTIMAL, gap 0; independent validation DEPLOYABLE. Generated artifact manifest verified.
- Recorded AI run remains `demo-66c9b6ebceee4839a2202e3eb006d57e`: genuine inference true, fallback false, objective 0.20, 21 variables/111 constraints, approximately 86.4 seconds. Its runtime/test receipt is not included in the downloaded bundle. Local tests above are separate evidence.
- README commands match implemented CLI options; installation steps match the existing pinned requirements. No new model download or inference was performed.

## Remaining release blockers and Git status

MIT remains unchanged. Third-party model/output redistribution rights, Gurobi eligibility, dependency licensing, and comprehensive security clearance remain unresolved; see [license review](../LICENSE_REVIEW_REQUIRED.md) and [security review](SECURITY_REVIEW.md). An evidence pattern scan is not a complete security review. Preparation is not publication approval.

The worktree already contained substantial uncommitted migration changes (modified files, tracked deletions and new files). This task updates README.md, .gitignore, the release notebook, docs/AI_RUNTIME.md, docs/VALIDATION.md, and this report; it removes only ignored caches. No staging, commit, push, reset, or history rewrite was performed.

Final checks: all local Markdown file links in the README, current docs and public example resolve; README contains no absolute machine paths; git diff --check passes. Source, configuration, tests, both existing results directories and the public example are byte-identical to their pre-task snapshots. The public evidence manifest and test source manifest pass. The separate original research directory was not written to; its earlier temporary hash baseline is no longer available, so the historical 6,046-file comparison was not repeated in this task. Final Git status contains 22 modified tracked files, 109 pre-existing tracked deletions and 26 untracked entries (directory entries may represent multiple files). These totals include earlier work, not just this cleanup.
