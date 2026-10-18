"""Backend boundary. Live engines run in a killable process, never generated code."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from .hardware import hardware_key
from .problem_contract import digest
from .persistence import json_write, hash_file

PACKAGES={'SGLANG':'sglang','TRANSFORMERS':'transformers','VLLM':'vllm'}


def recipe_hash(settings):
    inference=settings.inference.model_dump();inference.pop('backend')
    return digest(dict(inference=inference,precision=settings.model.precision,quantization=settings.model.quantization))


def select_backend(settings, info, checkpoint, receipts=()):
    selected=settings.inference.backend
    if selected!='AUTO':
        if PACKAGES[selected] not in info['packages']: raise ValueError('BACKEND_NOT_INSTALLED:'+selected)
        return selected
    for backend in ('SGLANG','TRANSFORMERS','VLLM'):
        for path in receipts:
            path=Path(path)
            try:
                receipt=json.loads(path.read_text())
                response=path.parent/'worker_result.json'
                if (receipt['live'] is True and receipt['backend']==backend and receipt['model_id']==checkpoint['model_id'] and receipt['revision']==checkpoint['revision']
                    and receipt['hardware_key']==hardware_key(info) and receipt['recipe_hash']==recipe_hash(settings) and receipt['packages']=={k:info['packages'].get(k) for k in (PACKAGES[backend],'torch','transformers','huggingface-hub')}
                    and hash_file(response)==receipt['worker_result_hash'] and json.loads(response.read_text()).get('text','').strip()
                    and all(json.loads(response.read_text()).get(k)==receipt[k] for k in ('model_id','revision','backend'))):
                    return backend
            except (OSError,ValueError,KeyError):continue
    raise ValueError('AUTO_NO_LIVE_TESTED_BACKEND: select an explicit backend for the first live attempt')


def terminate_group(process):
    if process.poll() is None:
        if os.name=='posix':os.killpg(process.pid,signal.SIGKILL)
        else:process.kill()
        process.wait()


class ProcessBackend:
    is_mock=False
    def generate(self, request, folder, timeout):
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        json_write(folder/'worker_request.json',request)
        with (folder/'inference.log').open('w') as log:
            process=subprocess.Popen([sys.executable,'-m','src.inference_worker',str((folder/'worker_request.json').resolve()),str((folder/'worker_result.json').resolve())],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            try:
                process.wait(timeout=timeout)
                if process.returncode:raise RuntimeError('INFERENCE_FAILURE: inspect inference.log and worker_error.json')
                result=json.loads((folder/'worker_result.json').read_text())
            except subprocess.TimeoutExpired as exc:
                terminate_group(process)
                raise TimeoutError('GENERATION_TIMEOUT: worker process group terminated') from exc
            finally:
                terminate_group(process)
        if result['revision']!=request['checkpoint']['revision'] or result['model_id']!=request['checkpoint']['model_id'] or result['backend']!=request['backend']:
            raise ValueError('INFERENCE_IDENTITY_MISMATCH')
        return result


class MockBackend:
    """Explicit test injection only, never selectable through production YAML/AUTO."""
    is_mock=True
    def __init__(self,response='',error=None):self.response=response;self.error=error
    def generate(self,request,folder,timeout):
        if self.error:raise self.error
        return dict(text=self.response,model_id=request['checkpoint']['model_id'],revision=request['checkpoint']['revision'],backend='MOCK',input_tokens=None,output_tokens=None,generation_seconds=0.,model_loading_seconds=0.,finish_reason='mock')
