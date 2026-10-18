# Architecture

The public entry point is `src.pipeline.run()` / `python -m src.pipeline`. It loads the existing strict scenario schema, rejects multiple cards or implicit portfolio generation, and builds `ProblemContract`. No new mathematical input schema is introduced.

`src.demo.run_demo()` remains the recommendation backend. It captures inputs and the realized problem, invokes the selected mode, and requires an independent DEPLOYABLE audit and proven optimality. The public wrapper fixes the compact interface and forbids AI fallback. Low-level modules retain regression-tested functionality beyond the public single-application interface; that is not a public portfolio-optimization feature.

Reference mode uses `src.main.run()` and the configured deterministic formulation. The supplied scenario uses `DIRECT_ASSIGNMENT_MILP` in `src.direct`. Existing enumeration code is retained for correctness comparisons and regression tests.

AI mode uses `src.demo_spec.messages()` to serialize the full validated contract and output schema. OptiMind may choose environment ordering and INLINE or EXPLICIT_SCORE; DIRECT_ASSIGNMENT is fixed. `parse_spec()` binds its response to the problem hash, ID, and environments. `compile_spec()` delegates business algebra to `src.ir_reference.direct_to_ir()` and `src.direct.build()`. `src.ir_compiler.CompiledIR` translates validated linear IR into Gurobi.

`src.formulation_validation` compares coverage and performs bounded independent equivalence checks. `src.validation` independently recomputes placement validity and metrics. Neither a valid JSON response nor a good solver incumbent alone authorizes a recommendation.

## Runtime and provenance

Runtime verification runs the complete manifest-bound suite and trusted formulation verification for the actual application scenario. It preserves Colab, GPU, package, restricted-license, Drive synchronization, source/test-integrity and scenario-input gates. Changing scenario inputs invalidates the runtime receipt. The model worker also checks runtime and text-environment compatibility. New runtime evidence is required after source/test/hardware changes.

The original generated-portfolio contract mismatch is avoided by the public pipeline's explicit inventory requirement. Generated inventory is not silently stripped or accepted with permissive schemas.

## Extension boundaries

New cards using existing semantics need configuration changes only. New policy types require agreement among `schema.py`, `problem_contract.py`, `direct.py`, relevant enumeration/metrics modules, IR requirements, `formulation_validation.py`, `validation.py`, and the independent oracle. Add positive and negative tests and preserve model-size limits. Existing mathematical implementations were retained during this migration.
