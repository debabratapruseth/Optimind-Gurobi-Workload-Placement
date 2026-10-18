"""Trusted local inference worker. Heavy dependencies are imported after gating.

Only this repository-owned module is executed. Model-produced Python remains text.
"""
import json
import os
from pathlib import Path
import sys
from time import perf_counter
from .inference_config import InferenceAI
from .hardware import inventory, preflight, hardware_key
from .runtime_verification import require_runtime
from .problem_contract import canonical_bytes
from .persistence import json_write, atomic
from .text_environment import check_packages


def generate(request, folder):
    settings=InferenceAI.model_validate(request['settings'])
    checkpoint=request['checkpoint'];cfg=settings.inference;backend=request['backend']
    info=inventory(request['cache_dir'])
    require_runtime(request['runtime_evidence'],info)
    check=preflight(settings,info,checkpoint,len(canonical_bytes(request['messages'])))
    json_write(folder/'worker_preflight.json',check)
    if not check['passed']:raise ValueError('WORKER_PREFLIGHT_FAILED:'+','.join(check['reasons']))
    if backend == 'TRANSFORMERS':
        environment = check_packages(info['packages'])
        json_write(folder/'text_environment.json', environment)
        if not environment['passed']:
            raise ValueError('TEXT_ENVIRONMENT_FAILED:' + ';'.join(environment['reasons']))
    # UUID avoids CUDA index/visibility remapping ambiguity. One GPU, no implicit offload.
    os.environ['CUDA_VISIBLE_DEVICES']=check['selected_gpu']['uuid']
    from huggingface_hub import snapshot_download
    from transformers import AutoTokenizer, set_seed
    if backend == 'TRANSFORMERS':
        from transformers import AutoModelForCausalLM  # Force lazy import BEFORE any snapshot download.
    import torch
    if not torch.cuda.is_available():raise ValueError('CUDA_NOT_AVAILABLE')
    if settings.model.precision=='BF16' and not torch.cuda.is_bf16_supported():raise ValueError('BF16_NOT_SUPPORTED')
    # Download tokenizer/config first; exact context check precedes weight download.
    common=dict(repo_id=checkpoint['model_id'],revision=checkpoint['revision'],cache_dir=request['cache_dir'])
    snapshot=snapshot_download(**common,allow_patterns=['*.json','*.jinja'])
    if Path(snapshot).name!=checkpoint['revision']:raise ValueError('SNAPSHOT_REVISION_MISMATCH')
    tokenizer=AutoTokenizer.from_pretrained(snapshot,trust_remote_code=False,local_files_only=True)
    prompt=tokenizer.apply_chat_template(request['messages'],tokenize=False,add_generation_prompt=True)
    ids=tokenizer(prompt,add_special_tokens=False)['input_ids']
    atomic(folder/'rendered_prompt.txt',prompt)
    json_write(folder/'prompt_tokens.json',dict(input_tokens=len(ids),max_new_tokens=cfg.max_new_tokens))
    if len(ids)+cfg.max_new_tokens>cfg.max_context_tokens:raise ValueError('EXACT_TOKEN_CONTEXT_LIMIT_EXCEEDED')
    started=perf_counter()
    snapshot=snapshot_download(**common,allow_patterns=['*.json','*.jinja','*.safetensors'])
    set_seed(cfg.seed)
    dtype=torch.bfloat16 if settings.model.precision=='BF16' else torch.float16
    if backend=='TRANSFORMERS':
        model=AutoModelForCausalLM.from_pretrained(snapshot,dtype=dtype,trust_remote_code=False,local_files_only=True,attn_implementation='flex_attention').to('cuda:0')
        model.eval();loading=perf_counter()-started;begun=perf_counter()
        encoded=tokenizer(prompt,return_tensors='pt',add_special_tokens=False).to('cuda:0')
        with torch.inference_mode():
            tokens=model.generate(**encoded,do_sample=True,temperature=cfg.temperature,top_p=cfg.top_p,max_new_tokens=cfg.max_new_tokens,pad_token_id=tokenizer.pad_token_id)
        completion=tokens[0,len(ids):].tolist()
        text=tokenizer.decode(completion,skip_special_tokens=False)
        output_tokens=len(completion);finish='length' if output_tokens>=cfg.max_new_tokens else 'stop'
    elif backend=='VLLM':
        from vllm import LLM,SamplingParams
        model=LLM(model=snapshot,tokenizer=snapshot,trust_remote_code=False,dtype='bfloat16' if settings.model.precision=='BF16' else 'float16',seed=cfg.seed,max_model_len=cfg.max_context_tokens,gpu_memory_utilization=cfg.gpu_safety_fraction,tensor_parallel_size=1)
        loading=perf_counter()-started;begun=perf_counter()
        item=model.generate([{'prompt_token_ids':ids}],SamplingParams(temperature=cfg.temperature,top_p=cfg.top_p,max_tokens=cfg.max_new_tokens,seed=cfg.seed,skip_special_tokens=False))[0].outputs[0]
        text=item.text;output_tokens=len(item.token_ids);finish=item.finish_reason
    elif backend=='SGLANG':
        import sglang as sgl
        model=sgl.Engine(model_path=snapshot,tokenizer_path=snapshot,trust_remote_code=False,dtype='bfloat16' if settings.model.precision=='BF16' else 'float16',random_seed=cfg.seed,context_length=cfg.max_context_tokens,mem_fraction_static=cfg.gpu_safety_fraction,tp_size=1)
        loading=perf_counter()-started;begun=perf_counter()
        try:
            item=model.generate(prompt,dict(temperature=cfg.temperature,top_p=cfg.top_p,max_new_tokens=cfg.max_new_tokens,skip_special_tokens=False))
            text=item['text'];output_tokens=item.get('meta_info',{}).get('completion_tokens');finish=item.get('meta_info',{}).get('finish_reason')
        finally:model.shutdown()
    else:raise ValueError('UNKNOWN_BACKEND')
    return dict(text=text,model_id=checkpoint['model_id'],revision=checkpoint['revision'],backend=backend,input_tokens=len(ids),output_tokens=output_tokens,generation_seconds=perf_counter()-begun,model_loading_seconds=loading,finish_reason=finish)


def main():
    source,destination=map(Path,sys.argv[1:]);folder=destination.parent
    try:json_write(destination,generate(json.loads(source.read_text()),folder))
    except Exception as exc:
        json_write(folder/'worker_error.json',dict(type=type(exc).__name__,message=str(exc)))
        raise

if __name__=='__main__':main()
