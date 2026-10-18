# Genuine OptiMind inference in Colab

A genuine BANK-PAY OptiMind-SFT + Gurobi execution has now been recorded in Colab; see the [verified public example](../examples/verified_ai_run/README.md) and its evidence limitations. Local reference success and mocked AI tests alone are not AI inference evidence.

Use [notebooks/run_pipeline.ipynb](../notebooks/run_pipeline.ipynb) in Google Colab. The pinned model is `microsoft/OptiMind-SFT` at `817e06666a39155f9352d00354b3227d230da46d`. It uses Transformers, BF16, no quantization, and no remote custom model code. The recorded research hardware was an NVIDIA A100 80 GB; current free GPU/RAM/disk must pass live preflight. Do not lower safety guards to force a launch.

1. Place the complete cleaned repository—including tests and fixtures—in `MyDrive/optimind-gurobi-workload-placement`. Configure the application and inputs there first. The notebook stages a new local copy and excludes environments, caches, Git metadata, and old results.
2. Keep the saved project notebook at `USE_AI=False`, `RUN_PIPELINE=False`, with outputs cleared before staging. After staging, choose the mode in the active notebook. A reference run first is optional. Install `requirements.txt`; the reference CLI needs no GPU, but this notebook’s shared verification gate requires a Colab GPU runtime. Run runtime verification and inspect the full suite plus actual application formulation results.
3. For genuine inference set `USE_AI=True`; rerun mode/dependency setup and verification. Put `HF_TOKEN` in Colab Secrets and grant notebook access; never paste it into source or logs. Install `requirements-inference-transformers.txt` and require `src.text_environment` to pass. Keep torchvision absent for this text-only workflow. A Colab runtime restart may be necessary after package changes; restage and reverify if restarted.
4. Runtime verification must report VERIFIED, ready, no missing/failed/skipped tests, a valid application formulation, and verified Drive synchronization. The suite count comes from its current manifest, not a historical hardcoded number.
5. Set `RUN_PIPELINE=True` only in the authorization cell after reviewing verification. Run the launch cell once. It consumes the flag and guards overlapping launches. The adapter performs checkpoint, hardware, package, context, and token-budget checks before loading/generating.
6. Inspect the new result. A genuine successful result must be RECOMMENDED, OPTIMIND_SPEC_TRUSTED_MILP, genuine_inference=true, fallback_used=false, proven optimal, and independently DEPLOYABLE. Failures remain failures and are preserved with diagnostics.

The equivalent runtime command, executed in the staged Colab repository, is:

```bash
python -m src.runtime_verification --config config/scenario.yaml \
  --output results/runtime \
  --drive-output /content/drive/MyDrive/optimind-gurobi-workload-placement/results/runtime
```

Set `RUNTIME_EVIDENCE` to the new **local** `runtime-*` directory printed by that command. Do not select an older receipt or edit its flags. Then run:

```bash
python -m src.pipeline --config config/scenario.yaml --mode AI_ASSISTED \
  --ai-config config/optimind.yaml --runtime-evidence "$RUNTIME_EVIDENCE" \
  --cache-dir /content/optimind-model-cache --output results/placement
```

CLI launches do not perform the notebook's final Drive copy automatically; use the notebook for the verified synchronization workflow. A new input file changes the bound input hashes and requires fresh scenario runtime verification. Source or test changes invalidate previous runtime evidence. No unrestricted local-GPU inference support is claimed.
