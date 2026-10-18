"""Metadata-only preflight before installing optional dependencies or weights."""
import argparse
from pathlib import Path
import yaml
from src.config import load
from src.inference_config import load_ai,InferenceAI
from src.hardware import inventory,resolve_checkpoint,preflight
from src.generation import messages
from tests.support.optimind_experiment import EXPERIMENTS
from src.runtime_verification import require_runtime,seal
from src.problem_contract import from_config,canonical_bytes
from src.portfolio import generate
from src.persistence import json_write,atomic


def prepare(ai_config,runtime_evidence,output,cache_dir,config='tests/fixtures/config/scenarios/single.yaml'):
    folder=Path(output);folder.mkdir(parents=True,exist_ok=False);Path(cache_dir).mkdir(parents=True,exist_ok=True)
    result=dict(passed=False)
    try:
        settings=load_ai(ai_config)
        if not settings.enabled:raise ValueError('AI_DISABLED')
        info=inventory(cache_dir);json_write(folder/'hardware.json',info);require_runtime(runtime_evidence,info)
        checkpoint=resolve_checkpoint(settings);json_write(folder/'checkpoint.json',checkpoint)
        c,_=load(config);contract=from_config(c,generate(c));checks={}
        for key,(track,mode) in EXPERIMENTS.items():
            data=settings.model_dump();data['generation'].update(mode=track,prompt_mode=mode);choice=InferenceAI.model_validate(data)
            checks[key]=preflight(choice,info,checkpoint,len(canonical_bytes(messages(contract,choice))))
        result.update(checks=checks,passed=all(v['passed'] for v in checks.values()))
        if result['passed']:
            data=settings.model_dump();data['model']['revision']=checkpoint['revision']
            atomic(folder/'pinned_ai.yaml',yaml.safe_dump(data,sort_keys=False))
    except Exception as exc:result['error']=f'{type(exc).__name__}: {exc}'
    json_write(folder/'preflight.json',result);seal(folder)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ai-config',default='tests/fixtures/config/ai/optimind_v2.yaml');p.add_argument('--config',default='tests/fixtures/config/scenarios/single.yaml')
    p.add_argument('--runtime-evidence',required=True);p.add_argument('--output',required=True);p.add_argument('--cache-dir',required=True)
    a=p.parse_args();result=prepare(a.ai_config,a.runtime_evidence,a.output,a.cache_dir,a.config);print(result);raise SystemExit(0 if result['passed'] else 2)

if __name__=='__main__':main()
