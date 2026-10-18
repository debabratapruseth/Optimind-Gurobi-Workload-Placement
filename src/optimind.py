"""Official checkpoint adapter: metadata, resource guards, and explicit backend."""
from pathlib import Path
from .hardware import inventory,resolve_checkpoint,preflight
from .inference_backends import ProcessBackend,select_backend
from .runtime_verification import require_runtime
from .problem_contract import canonical_bytes
from .persistence import json_write


class OptiMindAdapter:
    def __init__(self,settings=None,backend=None):
        self.settings=settings;self.backend=backend or ProcessBackend()
    def formulate(self,problem):
        # Preserve the old unsafe/unconfigured adapter call as a non-executable stub.
        raise NotImplementedError('NOT_IMPLEMENTED: use configured generation via src.pipeline; arbitrary Python execution is disabled')
    def prepare(self,messages,folder,runtime_evidence,cache_dir,receipts=()):
        if self.settings is None or not self.settings.enabled:raise ValueError('AI_DISABLED_OR_UNCONFIGURED')
        folder=Path(folder);Path(cache_dir).mkdir(parents=True,exist_ok=True)
        info=inventory(cache_dir);json_write(folder/'hardware.json',info)
        require_runtime(runtime_evidence,info)
        checkpoint=resolve_checkpoint(self.settings);json_write(folder/'checkpoint.json',checkpoint)
        check=preflight(self.settings,info,checkpoint,len(canonical_bytes(messages)));json_write(folder/'preflight.json',check)
        if not check['passed']:raise ValueError('HARDWARE_PREFLIGHT_FAILED:'+','.join(check['reasons']))
        backend=select_backend(self.settings,info,checkpoint,receipts)
        request=dict(settings=self.settings.model_dump(),messages=messages,checkpoint=checkpoint,backend=backend,runtime_evidence=str(Path(runtime_evidence).resolve()),cache_dir=str(Path(cache_dir).resolve()))
        return request,info
    def generate(self,request,folder):
        return self.backend.generate(request,folder,self.settings.inference.timeout_seconds)
