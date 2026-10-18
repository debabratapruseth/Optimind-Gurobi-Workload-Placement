"""Single-application placement entry point; genuine AI is explicit and fail-closed."""
import argparse
import json
from pathlib import Path

from .config import load
from .demo import DemoConfig, ROOT, run_demo
from .problem_contract import from_config


def load_problem(config):
    """Validate a complete scenario with one new card and an explicit fixed inventory."""
    c, sources = load(config)
    if len(c['applications']['applications']) != 1 or len(c['experiment']['selected_application_ids']) != 1:
        raise ValueError('PIPELINE_REQUIRES_ONE_NEW_APPLICATION')
    if c['objectives']['strategy'] != 'WEIGHTED':
        raise ValueError('PIPELINE_REQUIRES_WEIGHTED_OBJECTIVE')
    portfolio = c['existing_portfolio']['applications']
    if c['experiment']['portfolio_size'] != len(portfolio):
        raise ValueError('PIPELINE_REQUIRES_EXPLICIT_FIXED_PORTFOLIO')
    return from_config(c, portfolio), sources


def run(config=ROOT/'config/scenario.yaml', output=ROOT/'results/placement', *,
        mode='REFERENCE_FALLBACK', ai_config=ROOT/'config/optimind.yaml',
        runtime_evidence=None, cache_dir=ROOT/'.model_cache', adapter=None):
    config = Path(config).resolve()
    if mode not in ('REFERENCE_FALLBACK', 'AI_ASSISTED'):
        raise ValueError('UNSUPPORTED_PIPELINE_MODE')
    # Fail before solver/inference setup on invalid schemas, references or unsupported scope.
    _, sources = load_problem(config)
    if mode == 'AI_ASSISTED' and runtime_evidence is None:
        raise ValueError('AI_ASSISTED_REQUIRES_VERIFIED_COLAB_RUNTIME')
    if mode == 'AI_ASSISTED':
        report = json.loads((Path(runtime_evidence)/'runtime.json').read_text())
        if report.get('version', 0) < 3 or report.get('input_hashes') != {k: v['sha256'] for k, v in sources.items()}:
            raise ValueError('AI_ASSISTED_REQUIRES_MATCHING_SCENARIO_VERIFICATION')
    options = DemoConfig(benchmark=str(config), mode=mode, ai_config=str(Path(ai_config).resolve()),
                         allow_reference_fallback=False, formulation_interface='COMPACT_SPEC',
                         reference_reason='Explicit deterministic reference mode; OptiMind was not invoked.')
    return run_demo(config, output, options=options, runtime_evidence=runtime_evidence,
                    cache_dir=cache_dir, adapter=adapter)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(ROOT/'config/scenario.yaml'))
    parser.add_argument('--output', default=str(ROOT/'results/placement'))
    parser.add_argument('--mode', choices=['REFERENCE_FALLBACK', 'AI_ASSISTED'], default='REFERENCE_FALLBACK')
    parser.add_argument('--ai-config', default=str(ROOT/'config/optimind.yaml'))
    parser.add_argument('--runtime-evidence')
    parser.add_argument('--cache-dir', default=str(ROOT/'.model_cache'))
    args = parser.parse_args()
    try:
        folder, result = run(args.config, args.output, mode=args.mode, ai_config=args.ai_config,
                             runtime_evidence=args.runtime_evidence, cache_dir=args.cache_dir)
    except (ValueError, OSError) as exc:
        parser.exit(2, f'Input/preflight error: {exc}\n')
    print(folder, result.status, result.source)
    raise SystemExit(0 if result.status == 'RECOMMENDED' else 2)


if __name__ == '__main__':
    main()
