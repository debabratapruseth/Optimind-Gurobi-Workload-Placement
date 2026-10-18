"""One E1–E4 attempt, no repairs, no execution of model-produced Python."""
import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4
from src.config import load
from src.portfolio import generate
from src.problem_contract import from_config,canonical_bytes,digest
from src.inference_config import load_ai,InferenceAI
from src.optimind import OptiMindAdapter
from src.inference_backends import PACKAGES,recipe_hash
from src.hardware import hardware_key
from src.generation import messages,parse_response,outcomes
from src.research_attempts import evaluate_attempt
from src.runtime_verification import seal
from src.persistence import json_write,atomic,hash_file,csv_write
from src.main import source_hashes

EXPERIMENTS={'E1':('NATIVE_GUROBIPY','AUTONOMOUS'),'E2':('NATIVE_GUROBIPY','TEMPLATE_GUIDED'),'E3':('STRUCTURED_IR','AUTONOMOUS'),'E4':('STRUCTURED_IR','TEMPLATE_GUIDED')}


def run(config,ai_config,output,runtime_evidence,experiment='E1',cache_dir='.model_cache',receipts=(),adapter=None,single_evidence=None):
    started=perf_counter();folder=Path(output)/('optimind-'+experiment+'-'+uuid4().hex[:12]);folder.mkdir(parents=True)
    record=dict(attempt_id=folder.name,attempt_version='2.0',experiment_id=experiment,benchmark_id=Path(config).stem,attempt_number=1,repair_iteration=0,
                status='STARTED',genuine_inference=False,live_attempt_started=False,model_id=None,revision=None,backend=None,prompt_hash=None,response_hash=None,
                hardware=None,parameters=None,generation_seconds=None,worker_wall_seconds=None,total_seconds=None,
                evaluation=outcomes(),validation=None,failure=None)
    json_write(folder/'attempt.json',record)
    stage='CONFIGURATION'
    try:
        if experiment not in EXPERIMENTS:raise ValueError('unknown experiment ID')
        settings=load_ai(ai_config)
        effective=settings.model_dump();effective['generation']['mode'],effective['generation']['prompt_mode']=EXPERIMENTS[experiment]
        settings=InferenceAI.model_validate(effective)
        c,sources=load(config);contract=from_config(c,generate(c));prompt=messages(contract,settings)
        record.update(model_id=settings.model.model_id,parameters=settings.model_dump(),generation_mode=settings.generation.mode,prompt_mode=settings.generation.prompt_mode,
                      problem_hash=digest(contract),prompt_hash=digest(prompt),input_hashes={k:v['sha256'] for k,v in sources.items()},ai_config_hash=hash_file(ai_config),source_hashes=source_hashes())
        json_write(folder/'problem.json',contract.model_dump());json_write(folder/'prompt.json',prompt);json_write(folder/'settings.json',settings.model_dump())
        atomic(folder/'ai_input.yaml',Path(ai_config).read_text())
        stage='PREFLIGHT'
        adapter=adapter or OptiMindAdapter(settings)
        if adapter.settings.model_dump()!=settings.model_dump():raise ValueError('adapter settings differ from effective experiment settings')
        request,info=adapter.prepare(prompt,folder,runtime_evidence,cache_dir,receipts)
        record.update(revision=request['checkpoint']['revision'],backend=request['backend'],hardware=info,checkpoint=request['checkpoint'])
        if record['benchmark_id'] not in ('single','single_direct'):
            if single_evidence is None:raise ValueError('SMALL_LIVE_EXPERIMENT_REQUIRED')
            single_folder=Path(single_evidence)
            manifest=json.loads((single_folder/'COMPLETE.json').read_text())
            if manifest.get('attempt.json')!=hash_file(single_folder/'attempt.json'):raise ValueError('single evidence integrity failure')
            previous=json.loads((single_folder/'attempt.json').read_text())
            if not (previous['benchmark_id'] in ('single','single_direct') and previous['genuine_inference'] and previous['evaluation'].get('output_format_valid') and previous['revision']==record['revision'] and previous['generation_mode']==settings.generation.mode):
                raise ValueError('SMALL_LIVE_EXPERIMENT_REQUIRED')
        json_write(folder/'attempt.json',record)
        stage='INFERENCE';record['live_attempt_started']=not adapter.backend.is_mock
        json_write(folder/'attempt.json',record)
        begun=perf_counter();result=adapter.generate(request,folder)
        record['worker_wall_seconds']=perf_counter()-begun
        # Mock backends are always labelled; they cannot produce AUTO qualification.
        if result['model_id']!=settings.model.model_id or result['revision']!=record['revision']:raise ValueError('INFERENCE_IDENTITY_MISMATCH')
        json_write(folder/'response.json',result)
        raw=result['text'];atomic(folder/'raw_response.txt',raw)
        record.update(genuine_inference=not adapter.backend.is_mock,backend=result['backend'],response_hash=hashlib.sha256(raw.encode()).hexdigest(),
                      generation_seconds=result['generation_seconds'],model_loading_seconds=result.get('model_loading_seconds'),input_tokens=result.get('input_tokens'),output_tokens=result.get('output_tokens'),finish_reason=result.get('finish_reason'))
        if not adapter.backend.is_mock and raw.strip():
            receipt=dict(live=True,model_id=record['model_id'],revision=record['revision'],backend=record['backend'],hardware_key=hardware_key(info),
                         recipe_hash=recipe_hash(settings),packages={k:info['packages'].get(k) for k in (PACKAGES[record['backend']],'torch','transformers','huggingface-hub')},worker_result_hash=hash_file(folder/'worker_result.json'))
            json_write(folder/'backend_receipt.json',receipt)
        stage='PARSING';parsed=parse_response(raw,settings.generation.mode)
        json_write(folder/'extraction.json',parsed);record['evaluation']['output_format_valid']=parsed['format_valid']
        if parsed.get('unsupported_reason'):
            record['status']='UNSUPPORTED_MODEL_OUTPUT'
            record['evaluation']['unsupported_reason']=parsed['unsupported_reason']
        elif parsed['code'] is not None:
            atomic(folder/'generated_gurobipy.py.txt',parsed['code']);atomic(folder/'mathematical_formulation.txt',parsed['mathematics'])
            record.update(status='STATICALLY_INSPECTED',static_inspection=parsed['static_inspection'])
        else:
            stage='VALIDATION';payload=parsed['ir_payload'];atomic(folder/'generated_ir.json',payload)
            context=dict(experiment_id=experiment,benchmark_id=record['benchmark_id'],model_identifier=record['model_id'],model_version=record['revision'],inference_backend=record['backend'],prompt_mode=settings.generation.prompt_mode,prompt_hash=record['prompt_hash'],generation_seed=settings.inference.seed,generation_parameters=settings.inference.model_dump(),attempt_number=1,repair_iteration=0,generation_seconds=record['generation_seconds'])
            attempt=evaluate_attempt(contract,payload,context,folder/'ir_evaluation',max_raw=settings.evaluation.max_raw,max_projected=settings.evaluation.max_projected)
            record['validation']=attempt.validation;record['evaluation']={**outcomes(attempt.validation),'output_format_valid':True}
            record['status']='EVALUATED';record['failure_classification']=attempt.failure_classification
    except Exception as exc:
        record.update(status='BLOCKED_PREFLIGHT' if stage in ('CONFIGURATION','PREFLIGHT') else 'GENERATION_TIMEOUT' if isinstance(exc,TimeoutError) else 'FAILED',failure=dict(stage=stage,type=type(exc).__name__,message=str(exc)))
        if stage=='PARSING':record['evaluation']['output_format_valid']=False
    finally:
        # Retain metadata even if preparation resolved a revision and then failed a guard.
        for name,key in [('hardware.json','hardware'),('checkpoint.json','checkpoint')]:
            if (folder/name).exists():record[key]=json.loads((folder/name).read_text())
        if record.get('checkpoint'):record['revision']=record['checkpoint']['revision']
        record['total_seconds']=perf_counter()-started
        json_write(folder/'attempt.json',record)
        row=dict(experiment=experiment,benchmark=record['benchmark_id'],status=record['status'],genuine_inference=record['genuine_inference'],generation_mode=record.get('generation_mode'),prompt_mode=record.get('prompt_mode'),revision=record['revision'],backend=record['backend'],total_seconds=record['total_seconds'],**record['evaluation'])
        csv_write(folder/'summary.csv',[row],list(row));seal(folder)
    return folder,record


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default='tests/fixtures/config/scenarios/single.yaml');p.add_argument('--ai-config',default='tests/fixtures/config/ai/optimind_v2.yaml')
    p.add_argument('--output',default='results/phase2b');p.add_argument('--runtime-evidence',required=True)
    p.add_argument('--experiment',choices=EXPERIMENTS,default='E1');p.add_argument('--cache-dir',default='.model_cache')
    p.add_argument('--backend-receipts',nargs='*',default=[]);p.add_argument('--single-evidence')
    args=p.parse_args();folder,record=run(args.config,args.ai_config,args.output,args.runtime_evidence,args.experiment,args.cache_dir,args.backend_receipts,single_evidence=args.single_evidence)
    print(folder,record['status'],record['evaluation'])
    raise SystemExit(0 if record['status'] in ('EVALUATED','STATICALLY_INSPECTED') else 2)

if __name__=='__main__':main()
