"""Version 2 AI settings; legacy disabled version 1 banking configs stay intact."""
from pathlib import Path
from typing import Literal
from pydantic import Field
import yaml
from .schema import Strict
from .config import UniqueLoader


class Checkpoint(Strict):
    provider: Literal['HUGGINGFACE'] = 'HUGGINGFACE'
    model_id: Literal['microsoft/OptiMind-SFT'] = 'microsoft/OptiMind-SFT'
    revision: str | None = Field(default=None, pattern=r'^[A-Za-z0-9._/-]+$')
    precision: Literal['BF16', 'FP16'] = 'BF16'
    quantization: Literal['NONE'] = 'NONE'
    trust_remote_code: Literal[False] = False


class Inference(Strict):
    backend: Literal['AUTO', 'SGLANG', 'TRANSFORMERS', 'VLLM'] = 'AUTO'
    temperature: float = Field(default=.9, gt=0, le=2)
    top_p: float = Field(default=1., gt=0, le=1)
    max_new_tokens: int = Field(default=4096, gt=0, le=32768)
    max_context_tokens: int = Field(default=32768, gt=0, le=131072)
    seed: int = Field(default=42, ge=0, le=2**31-1)
    timeout_seconds: float = Field(default=1800., gt=0, le=14400)
    gpu_index: int = Field(default=0, ge=0)
    memory_overhead_gib: float = Field(default=8., ge=4)
    gpu_safety_fraction: float = Field(default=.9, gt=0, le=.95)
    ram_weight_multiplier: float = Field(default=1.2, ge=1)
    disk_weight_multiplier: float = Field(default=2., ge=1)


class Generation(Strict):
    mode: Literal['NATIVE_GUROBIPY', 'STRUCTURED_IR'] = 'NATIVE_GUROBIPY'
    prompt_mode: Literal['AUTONOMOUS', 'TEMPLATE_GUIDED'] = 'AUTONOMOUS'
    attempts: Literal[1] = 1
    repairs: Literal[0] = 0


class Evaluation(Strict):
    execute_generated_python: Literal[False] = False
    validate_generated_ir: Literal[True] = True
    compare_with_reference: Literal[True] = True
    max_raw: int = Field(default=200000, gt=0, le=200000)
    max_projected: int = Field(default=2000, gt=0, le=2000)


class InferenceAI(Strict):
    version: Literal[2] = 2
    enabled: bool = True
    model: Checkpoint = Field(default_factory=Checkpoint)
    inference: Inference = Field(default_factory=Inference)
    generation: Generation = Field(default_factory=Generation)
    evaluation: Evaluation = Field(default_factory=Evaluation)


def load_ai(path):
    return InferenceAI.model_validate(yaml.load(Path(path).read_text(), Loader=UniqueLoader))
