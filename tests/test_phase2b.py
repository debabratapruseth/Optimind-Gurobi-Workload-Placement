"""Mock-only inference integration; never downloads or loads model weights."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from contextlib import nullcontext
import json
import sys
import subprocess
import time
import pytest
import yaml
from src.inference_config import InferenceAI,load_ai
from src.hardware import preflight,resolve_checkpoint,hardware_key,GIB
from src.inference_backends import select_backend,MockBackend,ProcessBackend,recipe_hash
from src.optimind import OptiMindAdapter
from tests.support.optimind_experiment import run,EXPERIMENTS
from src.generation import messages,parse_response,outcomes
from src.problem_contract import ProblemContract,digest
from src.persistence import json_write,hash_file
from src.runtime_verification import seal,sync_verified,require_runtime

ROOT=Path(__file__).resolve().parents[1]
SHA='a'*40


def info():
    # Complete synthetic inventory: worker validation intentionally never reads host packages here.
    return dict(python='3.12',python_version=[3,12,0],os='Linux',runtime_id='test-boot',colab=True,
                packages={'accelerate':'1.15.0','transformers':'5.12.1','torch':'2.13.0','sglang':'0.5.21','vllm':'0.31.0','huggingface-hub':'test'},
                gpus=[dict(index=0,uuid='GPU-test',name='test A100 80GB',total_bytes=80*GIB,free_bytes=79*GIB,compute_capability=8.,driver='test')],
                ram=dict(total_bytes=128*GIB,available_bytes=100*GIB),disk=dict(path='/tmp',free_bytes=200*GIB))


def checkpoint():
    return dict(model_id='microsoft/OptiMind-SFT',revision=SHA,total_parameters=20_914_757_184,weight_bytes=41_829_514_368,precision='BF16',quantization='NONE',config=dict(model_type='gpt_oss',dtype='bfloat16',num_hidden_layers=24,num_key_value_heads=8,head_dim=64,max_position_embeddings=131072))


def contract():
    return ProblemContract.model_validate(json.loads((ROOT/'tests/fixtures/phase2a/single_problem.json').read_text()))


def effective(experiment):
    data=load_ai(ROOT/'tests/fixtures/config/ai/optimind_v2.yaml').model_dump()
    data['generation']['mode'],data['generation']['prompt_mode']=EXPERIMENTS[experiment]
    return InferenceAI.model_validate(data)


@pytest.mark.parametrize('field,value',[('model_id','other/model'),('quantization','AWQ'),('trust_remote_code',True),('precision','FP8')])
def test_model_schema(field,value):
    data=InferenceAI().model_dump();data['model'][field]=value
    with pytest.raises(ValueError):InferenceAI.model_validate(data)


@pytest.mark.parametrize('section,field,value',[('inference','backend','MOCK'),('inference','temperature',float('nan')),('generation','repairs',1),('generation','attempts',5),('evaluation','execute_generated_python',True),('evaluation','compare_with_reference',False)])
def test_no_unsafe_or_implicit_modes(section,field,value):
    data=InferenceAI().model_dump();data[section][field]=value
    with pytest.raises(ValueError):InferenceAI.model_validate(data)


def test_metadata_pin_without_weight_download():
    seen=[];cp=checkpoint()
    def fetch(url):
        seen.append(url)
        if '/api/models/' in url:return dict(id=cp['model_id'],sha=SHA,safetensors={'total':cp['total_parameters']})
        if url.endswith('config.json'):return cp['config']
        return dict(metadata={'total_size':cp['weight_bytes']})
    resolved=resolve_checkpoint(InferenceAI(),fetch)
    assert resolved['revision']==SHA and resolved['total_parameters']>20_000_000_000
    assert all('/'+SHA+'/' in url for url in seen[1:])
    data=InferenceAI().model_dump();data['model']['revision']='b'*40
    with pytest.raises(ValueError,match='mismatch'):resolve_checkpoint(InferenceAI.model_validate(data),fetch)


@pytest.mark.parametrize('mutation,reason',[('gpu','NO_SELECTED_NVIDIA_GPU'),('memory','INSUFFICIENT_GPU_MEMORY'),('ram','INSUFFICIENT_SYSTEM_RAM'),('disk','INSUFFICIENT_DISK'),('precision','PRECISION_UNSUPPORTED'),('os','UNSUPPORTED_RUNTIME_OS')])
def test_preflight_rejects(mutation,reason):
    hw=info()
    if mutation=='gpu':hw['gpus']=[]
    if mutation=='memory':hw['gpus'][0]['free_bytes']=16*GIB
    if mutation=='ram':hw['ram']['available_bytes']=10*GIB
    if mutation=='disk':hw['disk']['free_bytes']=10*GIB
    if mutation=='precision':hw['gpus'][0]['compute_capability']=7.5
    if mutation=='os':hw['os']='Darwin'
    result=preflight(InferenceAI(),hw,checkpoint())
    assert not result['passed'] and reason in result['reasons']
    assert result['full_weight_bytes']==checkpoint()['total_parameters']*2


def test_preflight_context_and_memory_estimates():
    cfg=InferenceAI();hw=info();cp=checkpoint()
    result=preflight(cfg,hw,cp)
    assert result['passed'] and result['required_gpu_bytes']>result['full_weight_bytes']
    assert not preflight(cfg,hw,cp,100000)['passed']
    # UUID/capacity/software identity is stable across free-memory changes.
    hw['gpus'][0]['free_bytes']-=GIB
    assert hardware_key(hw)==hardware_key(info())


def test_auto_requires_real_evidence(tmp_path):
    settings=InferenceAI();hw=info();cp=checkpoint()
    with pytest.raises(ValueError,match='AUTO_NO'):select_backend(settings,hw,cp)
    json_write(tmp_path/'worker_result.json',dict(text='actual result',backend='TRANSFORMERS',model_id=cp['model_id'],revision=SHA))
    receipt=dict(live=True,recipe_hash=recipe_hash(settings),backend='TRANSFORMERS',model_id=cp['model_id'],revision=SHA,hardware_key=hardware_key(hw),
                 packages={k:hw['packages'].get(k) for k in ('transformers','torch','huggingface-hub')},worker_result_hash=hash_file(tmp_path/'worker_result.json'))
    path=tmp_path/'backend_receipt.json';json_write(path,receipt)
    assert select_backend(settings,hw,cp,[path])=='TRANSFORMERS'
    receipt['live']=False;json_write(path,receipt)
    with pytest.raises(ValueError):select_backend(settings,hw,cp,[path])
    receipt['live']=True;receipt['revision']='b'*40;json_write(path,receipt)
    with pytest.raises(ValueError):select_backend(settings,hw,cp,[path])


@pytest.mark.parametrize('backend',['TRANSFORMERS','SGLANG','VLLM'])
def test_explicit_backend_selection(backend):
    data=InferenceAI().model_dump();data['inference']['backend']=backend;cfg=InferenceAI.model_validate(data)
    assert select_backend(cfg,info(),checkpoint())==backend
    hw=info();hw['packages']={}
    with pytest.raises(ValueError):select_backend(cfg,hw,checkpoint())


@pytest.mark.parametrize('experiment',list(EXPERIMENTS))
def test_prompt_reproducibility_and_no_reference_leak(experiment):
    cfg=effective(experiment);prompt=messages(contract(),cfg)
    assert digest(prompt)==digest(messages(contract(),cfg))
    data=json.loads(prompt[1]['content'])
    assert set(data)<= {'problem','problem_hash','output_schema','limits'}
    assert data['problem_hash']==digest(contract())
    assert all(word not in json.dumps(prompt) for word in ('TEST-APP,PROD,AWS_HK','0.369863013698','reference_objective','source_snapshot','count_link['))
    assert ('output_schema' in data)==(experiment in ('E3','E4'))


def test_native_extraction_never_executes(tmp_path):
    target=tmp_path/'must_not_exist'
    response=f'Math: select an assignment.\n```python\nimport os\nopen({str(target)!r}, "w").write("unsafe")\n```'
    result=parse_response(response,'NATIVE_GUROBIPY')
    assert result['code'].startswith('import os') and not target.exists()
    assert result['static_inspection']['security_findings']
    assert result['static_inspection']['executed'] is False
    assert outcomes()['mathematical_outcome']=='UNVERIFIED'


@pytest.mark.parametrize('response',['','no block','```python\nx=\n```\n```python\nx=1\n```'])
def test_bad_native_response(response):
    with pytest.raises(ValueError):parse_response(response,'NATIVE_GUROBIPY')


def test_native_bad_syntax_is_preserved():
    parsed=parse_response('Math\n```python\nx=\n```','NATIVE_GUROBIPY')
    assert parsed['code']=='x=\n' and not parsed['static_inspection']['syntax_valid']


@pytest.mark.parametrize('response',['not JSON','```json\n{}\n```\n```json\n{}\n```','prefix\n```json\n{}\n```'])
def test_ambiguous_ir_response(response):
    with pytest.raises(ValueError):parse_response(response,'STRUCTURED_IR')


def test_ir_extraction_preserves_text_and_harmony():
    text='{"ir_version":"1.0","x":3}'
    response='<|channel|>analysis<|message|>private drafting<|start|>assistant<|channel|>final<|message|>```json\n'+text+'\n```<|return|>'
    assert parse_response(response,'STRUCTURED_IR')['ir_payload']==text


def mocked_adapter(experiment,response='',error=None):
    adapter=OptiMindAdapter(effective(experiment),MockBackend(response,error))
    def prepare(prompt,folder,runtime_evidence,cache_dir,receipts):
        return dict(messages=prompt,settings=adapter.settings.model_dump(),checkpoint=checkpoint(),backend='MOCK'),info()
    adapter.prepare=prepare
    return adapter


def test_mock_native_attempt_persistence(tmp_path):
    adapter=mocked_adapter('E1','Math description\n```python\nimport gurobipy as gp\n```')
    folder,result=run(ROOT/'tests/fixtures/config/scenarios/single.yaml',ROOT/'tests/fixtures/config/ai/optimind_v2.yaml',tmp_path,'unused',adapter=adapter)
    assert result['status']=='STATICALLY_INSPECTED' and result['genuine_inference'] is False
    assert result['backend']=='MOCK' and result['revision']==SHA
    assert (folder/'raw_response.txt').is_file() and (folder/'generated_gurobipy.py.txt').is_file()
    assert not (folder/'backend_receipt.json').exists()
    for path,expected in json.loads((folder/'COMPLETE.json').read_text()).items():assert hash_file(folder/path)==expected


@pytest.mark.parametrize('error,status',[(TimeoutError('timeout'),'GENERATION_TIMEOUT'),(RuntimeError('inference error'),'FAILED')])
def test_generation_failures_persist(error,status,tmp_path):
    adapter=mocked_adapter('E1',error=error)
    folder,result=run(ROOT/'tests/fixtures/config/scenarios/single.yaml',ROOT/'tests/fixtures/config/ai/optimind_v2.yaml',tmp_path,'unused',adapter=adapter)
    assert result['status']==status and not result['genuine_inference']
    assert (folder/'prompt.json').exists() and (folder/'attempt.json').exists()


def test_real_process_timeout_kills_worker_group(tmp_path,monkeypatch):
    import src.inference_backends as module
    original=subprocess.Popen
    def start(*args,**kwargs):
        return original([sys.executable,'-c','import time; time.sleep(20)'],**kwargs)
    monkeypatch.setattr(module.subprocess,'Popen',start)
    before=time.monotonic()
    with pytest.raises(TimeoutError):ProcessBackend().generate({},tmp_path,.05)
    assert time.monotonic()-before<3


def renamed_ir():
    ir=json.loads((ROOT/'tests/fixtures/phase2a/single_trusted_ir.json').read_text())
    ir['profile']='GENERAL_LINEAR_V1'
    ir['objectives'][0]['id']='my_score'
    for entry in ir['manifest']:entry['objectives']=['my_score' if x=='weighted' else x for x in entry['objectives']]
    return json.dumps(ir)


def test_unknown_ir_equivalence_separate_from_recognition(tmp_path):
    adapter=mocked_adapter('E3',renamed_ir())
    folder,result=run(ROOT/'tests/fixtures/config/scenarios/single.yaml',ROOT/'tests/fixtures/config/ai/optimind_v2.yaml',tmp_path,'unused',experiment='E3',adapter=adapter)
    assert result['status']=='EVALUATED',result
    e=result['evaluation']
    assert e['ir_schema_valid'] and e['compilation_success']
    assert not e['canonical_recognition'] and e['bounded_behavioral_equivalence']
    assert e['mathematical_outcome']=='BOUNDED_EQUIVALENT'
    assert e['phase2a_classification']=='UNVERIFIED'
    assert (folder/'generated_ir.json').read_text()==renamed_ir()


def test_invalid_ir_is_not_repaired(tmp_path):
    adapter=mocked_adapter('E4','{"python":"print(1)"}')
    folder,result=run(ROOT/'tests/fixtures/config/scenarios/single.yaml',ROOT/'tests/fixtures/config/ai/optimind_v2.yaml',tmp_path,'unused',experiment='E4',adapter=adapter)
    assert result['status']=='EVALUATED'
    assert not result['evaluation']['ir_schema_valid'] and not result['evaluation']['compilation_success']
    assert result['evaluation']['mathematical_outcome']=='UNVERIFIED'


def test_preflight_blocks_backend(tmp_path,monkeypatch):
    adapter=OptiMindAdapter(effective('E1'),MockBackend(error=AssertionError('must not generate')))
    monkeypatch.setattr('src.optimind.inventory',lambda *args:info())
    monkeypatch.setattr('src.optimind.require_runtime',lambda *args: (_ for _ in ()).throw(ValueError('COLAB_RUNTIME_VERIFICATION_PENDING')))
    folder,result=run(ROOT/'tests/fixtures/config/scenarios/single.yaml',ROOT/'tests/fixtures/config/ai/optimind_v2.yaml',tmp_path,'absent',adapter=adapter,cache_dir=tmp_path/'cache')
    assert result['status']=='BLOCKED_PREFLIGHT'
    assert not result['genuine_inference']


def test_sync_hashes_and_tampering(tmp_path):
    source=tmp_path/'source';source.mkdir();json_write(source/'test.json',{'a':1});seal(source)
    result=sync_verified(source,tmp_path/'copy')
    assert result['verified']
    json_write(source/'test.json',{'a':2})
    with pytest.raises(ValueError,match='integrity'):sync_verified(source,tmp_path/'copy')


def assert_notebook_cells_compile(notebook):
    # Saved outputs are normal Colab evidence, not executable source or a readiness gate.
    for cell in notebook['cells']:
        if cell['cell_type']=='code':compile(''.join(cell['source']),'notebook','exec')


def test_new_notebook_cells_compile():
    notebook=json.loads((ROOT/'tests/fixtures/notebooks/run_optimind.ipynb').read_text())
    assert_notebook_cells_compile(notebook)


def test_notebook_saved_outputs_are_preserved():
    notebook=json.loads((ROOT/'tests/fixtures/notebooks/run_optimind.ipynb').read_text())
    cell=next(c for c in notebook['cells'] if c['cell_type']=='code')
    cell['execution_count']=3
    cell['outputs']=[{'output_type':'stream','name':'stdout','text':['Mounted at /content/drive\n']},
                     {'output_type':'error','ename':'CalledProcessError','evalue':'exit status 2','traceback':[]}]
    original=deepcopy(notebook)
    assert_notebook_cells_compile(notebook)
    assert notebook==original


def test_notebook_saved_outputs_do_not_hide_invalid_source():
    notebook={'cells':[{'cell_type':'code','source':['def broken('],
                       'outputs':[{'output_type':'stream','name':'stdout','text':['previous output']}]}]}
    with pytest.raises(SyntaxError):assert_notebook_cells_compile(notebook)


@pytest.mark.parametrize('backend',['TRANSFORMERS','SGLANG','VLLM'])
def test_worker_backend_api_contracts_without_models(backend,tmp_path,monkeypatch):
    import src.inference_worker as worker
    cfg=effective('E1');data=cfg.model_dump();data['inference']['backend']=backend;cfg=InferenceAI.model_validate(data)
    class Tokens:
        def __getitem__(self,key):return self
        def tolist(self):return [1,2]
    class Encoded(dict):
        def to(self,*args):return self
    class Tokenizer:
        pad_token_id=0
        def apply_chat_template(self,*args,**kwargs):return 'rendered'
        def __call__(self,text,**kwargs):return Encoded(input_ids=[1,2,3])
        def decode(self,*args,**kwargs):return 'full response'
    class Model:
        def __init__(self,*args,**kwargs):pass
        def to(self,*args):return self
        def eval(self):pass
        def generate(self,*args,**kwargs):
            if backend=='TRANSFORMERS':return Tokens()
            if backend=='SGLANG':return {'text':'full response','meta_info':{'completion_tokens':2}}
            return [SimpleNamespace(outputs=[SimpleNamespace(text='full response',token_ids=[1,2],finish_reason='stop')])]
        def shutdown(self):pass
    snapshots=[]
    def snapshot(**kwargs):snapshots.append(kwargs);return str(tmp_path/SHA)
    monkeypatch.setitem(sys.modules,'huggingface_hub',SimpleNamespace(snapshot_download=snapshot))
    monkeypatch.setitem(sys.modules,'transformers',SimpleNamespace(AutoTokenizer=SimpleNamespace(from_pretrained=lambda *a,**k:Tokenizer()),set_seed=lambda seed:None,AutoModelForCausalLM=SimpleNamespace(from_pretrained=lambda *a,**k:Model())))
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:True,is_bf16_supported=lambda:True),bfloat16='bf16',float16='fp16',inference_mode=nullcontext))
    monkeypatch.setitem(sys.modules,'vllm',SimpleNamespace(LLM=Model,SamplingParams=lambda **kwargs:kwargs))
    monkeypatch.setitem(sys.modules,'sglang',SimpleNamespace(Engine=Model))
    monkeypatch.setattr(worker,'inventory',lambda *a:info());monkeypatch.setattr(worker,'require_runtime',lambda *a:True)
    monkeypatch.setenv('CUDA_VISIBLE_DEVICES','')
    result=worker.generate(dict(settings=cfg.model_dump(),checkpoint=checkpoint(),backend=backend,cache_dir=str(tmp_path),runtime_evidence='unused',messages=[]),tmp_path)
    assert result['backend']==backend and result['revision']==SHA
    assert result['text']=='full response'
    assert len(snapshots)==2 and all(s['revision']==SHA for s in snapshots)
    assert '*.safetensors' not in snapshots[0]['allow_patterns']


def test_unverified_is_not_counted_as_mathematical_error():
    result=outcomes(dict(classification='UNVERIFIED',levels={'1_schema':'PASS','3_fidelity':{'recognized':False},'5_equivalence':{'complete':False,'reason':'limit'}},compilation={'status':'COMPILED'}))
    assert result['mathematical_outcome']=='UNVERIFIED'
    assert result['bounded_behavioral_equivalence'] is None and result['objective_correct'] is None


def test_wrong_objective_direction_is_not_equivalent(tmp_path):
    ir=json.loads(renamed_ir());ir['objective_sense']='MAX'
    adapter=mocked_adapter('E3',json.dumps(ir))
    _,result=run(ROOT/'tests/fixtures/config/scenarios/single.yaml',ROOT/'tests/fixtures/config/ai/optimind_v2.yaml',tmp_path,'unused',experiment='E3',adapter=adapter)
    assert not result['evaluation']['bounded_behavioral_equivalence']
    assert result['evaluation']['mathematical_outcome']=='COUNTEREXAMPLE'


def test_medium_requires_single_live_evidence(tmp_path):
    adapter=mocked_adapter('E1','Math\n```python\nx=1\n```')
    _,result=run(ROOT/'tests/fixtures/config/scenarios/medium.yaml',ROOT/'tests/fixtures/config/ai/optimind_v2.yaml',tmp_path,'unused',adapter=adapter)
    assert result['status']=='BLOCKED_PREFLIGHT'
    assert result['failure']['message']=='SMALL_LIVE_EXPERIMENT_REQUIRED'


def test_missing_assignment_encoding_is_unverified(tmp_path):
    ir=json.loads(renamed_ir())
    for v in ir['variables']:v['assignment']=None
    adapter=mocked_adapter('E3',json.dumps(ir))
    _,result=run(ROOT/'tests/fixtures/config/scenarios/single.yaml',ROOT/'tests/fixtures/config/ai/optimind_v2.yaml',tmp_path,'unused',experiment='E3',adapter=adapter)
    assert result['evaluation']['mathematical_outcome']=='UNVERIFIED'
    assert result['evaluation']['bounded_behavioral_equivalence'] is None


def test_declared_unsupported_response_is_explicit(tmp_path):
    response=json.loads((ROOT/'tests/fixtures/phase2b/responses.json').read_text())['unsupported']
    adapter=mocked_adapter('E3',response)
    _,result=run(ROOT/'tests/fixtures/config/scenarios/single.yaml',ROOT/'tests/fixtures/config/ai/optimind_v2.yaml',tmp_path,'unused',experiment='E3',adapter=adapter)
    assert result['status']=='UNSUPPORTED_MODEL_OUTPUT'
    assert result['evaluation']['mathematical_outcome']=='UNVERIFIED'
    assert result['evaluation']['unsupported_reason']==response
