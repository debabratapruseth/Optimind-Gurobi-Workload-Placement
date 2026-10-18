# Verified OptiMind-SFT + Gurobi example

Run `demo-66c9b6ebceee4839a2202e3eb006d57e` is the successful user-supplied Colab execution. This directory is a minimal public subset, not a complete replay bundle. The original downloaded run remains unchanged and excluded from Git under `results/verified_ai_run/`. No original evidence was deleted. The user also reported downloading it from Google Drive; continued remote retention was not independently checked.

## Results

AI_ASSISTED; genuine inference true; fallback false; RECOMMENDED. Model `microsoft/OptiMind-SFT`, revision `817e06666a39155f9352d00354b3227d230da46d`, Transformers BF16 without quantization. OptiMind selected DIRECT_ASSIGNMENT / INLINE; trusted code authored the algebra and Gurobi 13.0.2 solved it. This is not an AI-generated unrestricted optimization program.

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

The ten copied artifacts are byte-identical to the originals. `verification.json` and this README are review-derived additions. `PUBLIC_MANIFEST.json` hashes the public subset; it does not replace or claim to be the original run's COMPLETE.json. All 50 entries in that original manifest verified before extraction. Hashes detect changes relative to the supplied manifest; they are not externally signed proof of execution.

Raw prompts/responses, hardware identifiers, local-path-bearing requests/configurations/logs, and full input snapshots are deliberately excluded. The copied reports retain evidence filenames for the original bundle; those references do not imply the omitted files are present here. No model weights, secrets, or license files are distributed.

The separate runtime/test receipt is absent from the downloaded directory. Therefore this example does not independently attest to the previously reported 353 tests. The reference comparison is the in-run bounded mathematical audit, not a second archived Gurobi-only run. The unused reference_reason in the original effective configuration is stale default text; recorded mode, genuine inference, null fallback reason, and fallback=false consistently identify the successful AI execution.

## Verify public file integrity

From this directory, run the following without loading a model or invoking Gurobi:

```python
import hashlib
import json
from pathlib import Path

root = Path('.')
manifest = json.loads((root / 'PUBLIC_MANIFEST.json').read_text())
for name, expected in manifest['files'].items():
    assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name
print('All public artifact hashes match')
```
