"""Immutable-per-attempt file records and leakage-limited future prompt inputs."""
from pathlib import Path
from typing import Literal
from pydantic import Field
from .schema import Strict
from .formulation_ir import Hash
from .problem_contract import canonical_bytes, digest
from .persistence import json_write, hash_file

Classification = Literal['UNDERCONSTRAINED', 'OVERCONSTRAINED', 'INCORRECT_OBJECTIVE', 'INVALID_FORMULATION', 'VALID_FORMULATION', 'VALID_BUT_SUBOPTIMAL_SOLUTION', 'UNVERIFIED']


class AttemptContext(Strict):
    experiment_id: str
    benchmark_id: str
    model_identifier: str
    model_version: str
    inference_backend: str
    prompt_mode: Literal['AUTONOMOUS', 'TEMPLATE_GUIDED']
    prompt_hash: Hash
    generation_seed: int
    generation_parameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    attempt_number: int = Field(ge=1)
    repair_iteration: int = Field(ge=0)
    generation_seconds: float = Field(ge=0)
    token_usage: int | None = Field(default=None, ge=0)
    inference_cost_usd: float | None = Field(default=None, ge=0)


class Attempt(Strict):
    attempt_version: Literal['1.0'] = '1.0'
    context: AttemptContext
    problem_hash: Hash
    ir_hash: Hash  # SHA256 of exact submitted bytes, including malformed submissions
    validation: dict
    compilation: dict
    solver: dict
    independent_placement_audit: dict
    objective_and_placement_metrics: dict
    compilation_seconds: float = Field(ge=0)
    solver_seconds: float = Field(ge=0)
    validation_seconds: float = Field(ge=0)
    total_seconds: float = Field(ge=0)
    failure_classification: Classification


def prompt_input(contract, mode):
    """Only contract + generic language schema; never recognizer/reference artifacts."""
    from .formulation_ir import FormulationIR
    if mode not in ('AUTONOMOUS', 'TEMPLATE_GUIDED'):
        raise ValueError('invalid prompt mode')
    data = dict(problem=contract.model_dump(mode='json'), output_schema=FormulationIR.model_json_schema(), mode=mode)
    if mode == 'TEMPLATE_GUIDED':
        data['guidance'] = 'Declare bounded variables, linear constraints and objectives, and link requirement claims to actual algebra. Return JSON only.'
    return data


def repair_feedback(report):
    # No exception text, constraint coefficients, placements, scores or oracle data.
    # Deliberately coarse for future paired repair campaigns.
    return dict(classification=report['classification'], schema_pass=report.get('levels', {}).get('1_schema') == 'PASS',
                placement_valid=report.get('placement_audit', {}).get('valid'),
                fidelity_recognized=report.get('levels', {}).get('3_fidelity', {}).get('recognized'))


def evaluate_attempt(contract, payload, context, folder, **limits):
    import hashlib
    from time import perf_counter
    from .formulation_validation import verify_formulation
    context = AttemptContext.model_validate(context.model_dump() if isinstance(context, AttemptContext) else context)
    if isinstance(payload, str): payload = payload.encode('utf-8')
    if not isinstance(payload, bytes): raise ValueError('attempt payload must be exact bytes')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)  # no overwrite, including interrupted attempts
    started = perf_counter()
    json_write(folder / 'context.json', context.model_dump())
    json_write(folder / 'problem.json', contract.model_dump())
    # Escaped JSON string preserves any malformed or executable submission inertly.
    json_write(folder / 'submission.json', dict(encoding='hex', bytes=payload.hex()))
    report = verify_formulation(contract, payload, folder / 'verification', **limits)
    compile_time = report['compilation'].get('seconds', 0.)
    solve_time = report['solver'].get('runtime_seconds', 0.)
    attempt = Attempt(context=context, problem_hash=digest(contract), ir_hash=hashlib.sha256(payload).hexdigest(), validation=report,
                      compilation=report['compilation'], solver=report['solver'], independent_placement_audit=report['placement_audit'],
                      objective_and_placement_metrics=dict(metrics=report['metrics'], placement=report.get('placement'), incumbent=report['solver'].get('incumbent'), reference_gap=report.get('reference_gap')),
                      compilation_seconds=compile_time, solver_seconds=solve_time,
                      validation_seconds=max(0., report['timings']['validation_total_seconds'] - compile_time - solve_time),
                      total_seconds=perf_counter() - started + context.generation_seconds, failure_classification=report['classification'])
    json_write(folder / 'attempt.json', attempt.model_dump())
    json_write(folder / 'COMPLETE.json', {str(p.relative_to(folder)): hash_file(p) for p in sorted(folder.rglob('*')) if p.is_file()})
    return attempt


def aggregate(attempts):
    """Empirical problem-level pass@k; incomplete five-attempt groups are excluded.

Repairs do not count as new independent samples. Conditional is not deployable.
"""
    from collections import defaultdict
    rows = [a.model_dump() if isinstance(a, Attempt) else a for a in attempts]
    groups = defaultdict(list)
    for a in rows:
        c = a['context']
        groups[(a['problem_hash'], c['model_identifier'], c['model_version'], c['inference_backend'], c['prompt_mode'])].append(a)
    def passed(a):
        return a['failure_classification'] == 'VALID_FORMULATION' and a['independent_placement_audit'].get('status') == 'DEPLOYABLE' and a['solver'].get('optimality_proven', False)
    def rate(values): return sum(values) / len(values) if values else None
    for values in groups.values():
        identities = [(a['context']['attempt_number'], a['context']['repair_iteration']) for a in values]
        if len(identities) != len(set(identities)):
            raise ValueError('duplicate attempt/repair identity in campaign group')
    initial = [a for a in rows if a['context']['repair_iteration'] == 0]
    pass1, pass5, repairs = [], [], []
    for values in groups.values():
        first = {a['context']['attempt_number']: a for a in values if a['context']['repair_iteration'] == 0}
        if 1 in first: pass1.append(passed(first[1]))
        if all(i in first for i in range(1, 6)): pass5.append(any(passed(first[i]) for i in range(1, 6)))
        for i, a in first.items():
            follow = [b for b in values if b['context']['attempt_number'] == i and b['context']['repair_iteration'] > 0]
            if follow and not passed(a): repairs.append(any(passed(b) for b in follow))
    valid = ('VALID_FORMULATION', 'VALID_BUT_SUBOPTIMAL_SOLUTION')
    return dict(attempt_count=len(rows), initial_count=len(initial), formulation_validity_rate=rate([a['failure_classification'] in valid for a in initial]),
                hard_constraint_fidelity_rate=rate([a['validation'].get('levels', {}).get('3_fidelity', {}).get('recognized', False) and a['validation'].get('levels', {}).get('5_equivalence', {}).get('complete', False) and not a['validation']['levels']['5_equivalence']['extra_infeasible'] and not a['validation']['levels']['5_equivalence']['missing_feasible'] for a in initial]),
                feasible_placement_rate=rate([a['independent_placement_audit'].get('status') == 'DEPLOYABLE' for a in initial]),
                objective_correctness_rate=rate([a['validation'].get('levels', {}).get('5_equivalence', {}).get('complete', False) and a['failure_classification'] in valid for a in initial]),
                pass_at_1=rate(pass1), pass_at_5=rate(pass5), pass_at_5_eligible_problems=len(pass5), repair_success_rate=rate(repairs),
                mean_generation_seconds=sum(a['context']['generation_seconds'] for a in rows)/len(rows) if rows else None,
                mean_solver_seconds=sum(a['solver_seconds'] for a in rows)/len(rows) if rows else None,
                mean_total_seconds=sum(a['total_seconds'] for a in rows)/len(rows) if rows else None)
