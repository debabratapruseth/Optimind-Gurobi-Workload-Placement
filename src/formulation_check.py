"""Trusted direct-to-IR demonstration; no inference or generated Python."""
import argparse
from pathlib import Path
from time import perf_counter
from uuid import uuid4
from .config import load, UniqueLoader
from .schema import Strict
from pydantic import Field
from typing import Literal
import yaml
from .portfolio import generate
from .problem_contract import from_config, canonical_bytes, digest
from .ir_reference import direct_to_ir
from .research_attempts import evaluate_attempt, prompt_input
from .persistence import json_write, csv_write, hash_file
from .main import source_hashes


class VerificationLimits(Strict):
    version: Literal[1]
    max_raw: int = Field(gt=0, le=200_000)
    max_projected: int = Field(gt=0, le=2000)


def run(config, output, settings='config/runtime/verification.yaml'):
    limits = VerificationLimits.model_validate(yaml.load(Path(settings).read_text(), Loader=UniqueLoader))
    c, sources = load(config)
    contract = from_config(c, generate(c))
    folder = Path(output) / ('formulation-'  + uuid4().hex[:12])
    started = perf_counter()
    ir = direct_to_ir(contract, folder / 'trusted_conversion')
    generation_seconds = perf_counter() - started
    prompt = prompt_input(contract, 'AUTONOMOUS')
    context = dict(experiment_id=c['experiment']['experiment_id'], benchmark_id=Path(config).stem,
                   model_identifier='TRUSTED_DIRECT_CONVERSION', model_version='1.0', inference_backend='NONE',
                   prompt_mode='AUTONOMOUS', prompt_hash=digest(prompt), generation_seed=c['solver']['seed'],
                   generation_parameters={}, attempt_number=1, repair_iteration=0, generation_seconds=generation_seconds)
    json_write(folder / 'formulation.json', ir.model_dump())
    json_write(folder / 'verification_limits.json', limits.model_dump())
    json_write(folder / 'provenance.json', dict(input_hashes={k:v['sha256'] for k,v in sources.items()}, source_hashes=source_hashes()))
    attempt = evaluate_attempt(contract, canonical_bytes(ir), context, folder / 'attempt', max_raw=limits.max_raw, max_projected=limits.max_projected)
    row = dict(benchmark=Path(config).stem, classification=attempt.failure_classification, variables=attempt.solver.get('model_counts', {}).get('variables'), constraints=attempt.solver.get('model_counts', {}).get('linear_constraints'), solver_status=attempt.solver.get('status'), gap=attempt.solver.get('mip_gap'), runtime_seconds=attempt.solver.get('runtime_seconds'))
    csv_write(folder / 'summary.csv', [row], list(row))
    json_write(folder / 'COMPLETE.json', {str(p.relative_to(folder)): hash_file(p) for p in sorted(folder.rglob('*')) if p.is_file()})
    return folder, attempt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/scenario.yaml')
    parser.add_argument('--output', default='results/formulation-check')
    parser.add_argument('--settings', default='config/runtime/verification.yaml')
    args = parser.parse_args()
    folder, result = run(args.config, args.output, args.settings)
    print(folder, result.failure_classification)
    raise SystemExit(0 if result.failure_classification == 'VALID_FORMULATION' else 2)

if __name__ == '__main__':
    main()
