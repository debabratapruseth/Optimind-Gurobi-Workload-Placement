# Validation and reproducibility

Validated locally on 17 October 2026 (Asia/Singapore). This is a local engineering validation, not a production-readiness or genuine AI inference claim.

## Verified workflow

A separate release snapshot was copied to `/tmp/placement-fresh-validation`, without Git metadata, existing environments, caches, historical evidence, or prior results. This simulates the uncommitted release contents; it was not a clone of the still-older remote branch.

A fresh Python 3.14.5 virtual environment was created and the exact `requirements.txt` installed successfully: PyYAML 6.0.3, pydantic 2.12.3, gurobipy 13.0.2, pytest 8.4.2. Transitive dependencies are not fully lockfile-pinned. `pip check` reported no broken requirements. Installation required network-enabled execution after the sandbox could not resolve packages.

The full migrated suite passed **335 tests, no failures or skips**: 14.18 seconds in the working environment and 21.10 seconds in the fresh environment. The original 316 test cases were retained/adapted; 19 cases cover the public pipeline, new notebook, and scenario-runtime binding. Test source hashes and collected node IDs are recorded in `tests/suite_manifest.json` and enforced by runtime verification.

Regression fixtures now live under `tests/fixtures`. The standalone TEST-APP fixture uses 10 vCPU, 40 GB RAM and 2 TB storage per environment and a newly compiled test IR. Its numerical assertions are fixture-specific mathematical regression checks, not the public application's result. Multi-application tests remain solely to protect existing shared mathematical routines; no new multi-application public feature was introduced.

## BANK-PAY-001 reference result

The supplied application card is byte-identical to the existing BANK-PAY-001 input. The new scenario uses the original synthetic recovery-capable inventory, original resource/cost/policy settings, and the two explicit fixed applications. It does not generate 23 additional exposure records. The solver gap is set to zero for verified optimality; no policy, recovery target, or capacity was relaxed.

| Check | Verified result |
| --- | --- |
| New application | BANK-PAY-001; PROD, DEV, SIT, UAT |
| Fixed context | SHARED-ID-001 at AWS_HK; LEGACY-RISK-001 at AWS_SG |
| Eligible production sites | AWS_HK and AWS_SG under the supplied SG policy |
| Eligible nonproduction | AWS_HK under the combination of policy and HK-only nonproduction rule |
| Chosen environments / local DR | All AWS_HK |
| Reserved and simultaneous-peak resources | 160 vCPU, 640 GB RAM, 0 GPU, 10 TB storage at AWS_HK |
| Available residual resources there | 512 vCPU, 2,048 GB RAM, 8 GPUs, 100 TB storage |
| Recovery requirement / supplied site capability | RTO 60 / 30 minutes; RPO 15 / 5 minutes |
| Modeled TCO | USD 102,240 over 36 months |
| Modeled dependency latency | 5 ms |
| Weighted normalized objective | Approximately 0.20 |
| Model size | 21 variables, 111 linear constraints |
| Solver | OPTIMAL, zero gap, restricted-license startup verified |
| Independent audit | Valid, DEPLOYABLE |
| Source | REFERENCE_FALLBACK; genuine_inference=false |

The primary result matches the independent exhaustive oracle. Negative cases for missing policy, missing latency, inadequate capacity, unverified recovery, and insufficient budget return infeasibility without a placement. Invalid references/schema fields, multiple cards, and implicit portfolio generation are rejected. Mocked compact AI tests use real compilation/solving and complete independent equivalence checks, but explicitly report genuine_inference=false. Invalid AI output never falls back through the public entry point.

The standalone trusted formulation check also returned VALID_FORMULATION in the fresh environment. All production modules imported successfully, all 26 local documentation links resolved, and the test-source manifest matched exactly. No obsolete public benchmark paths or historical application ID remain in the production source, user configuration, notebook, or end-user documentation. The Mermaid flowchart uses standard fenced syntax; GitHub visual rendering was not exercised.

## Reproducing checks

```bash
python -m pytest -q -ra tests
python -m src.pipeline --config config/scenario.yaml --mode REFERENCE_FALLBACK --output results/placement
```

Both commands create fresh outputs/cache as appropriate; do not edit completed result manifests. Run directories contain exact input snapshots, the realized problem, source hashes, solver diagnostics, independent audit, and an integrity manifest.

New genuine AI execution requires [the Colab procedure](AI_RUNTIME.md), a matching scenario receipt, pinned model revision and packages, and current hardware checks. A subsequent genuine Colab execution is documented in the [verified AI example](../examples/verified_ai_run/README.md). Its downloaded run lacks the separate runtime/test receipt; the recorded execution and the local test results are distinct evidence. Notebook Python syntax, opt-in consumption, repeat-launch prevention and worker-overlap rejection were tested locally.

The original research directory and historical successful evidence remain preserved externally. Historical artifacts describe an earlier code/input revision; they are not evidence that this new application workflow ran genuine inference.
