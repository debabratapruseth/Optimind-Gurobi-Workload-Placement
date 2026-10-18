"""Small-dependency hardware inventory and conservative full-weight preflight."""
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
import urllib.parse
from .problem_contract import digest

GIB = 1024**3


def inventory(path='.'):
    packages = {d.metadata['Name'].lower(): d.version for d in importlib.metadata.distributions() if d.metadata['Name']}
    ram = dict(total_bytes=None, available_bytes=None)
    if Path('/proc/meminfo').exists():
        values = dict(re.findall(r'^(\w+):\s+(\d+)', Path('/proc/meminfo').read_text(), re.M))
        ram = dict(total_bytes=int(values['MemTotal'])*1024, available_bytes=int(values['MemAvailable'])*1024)
    elif platform.system() == 'Darwin':
        try:
            ram['total_bytes'] = int(subprocess.check_output(['sysctl', '-n', 'hw.memsize'], text=True, stderr=subprocess.DEVNULL, timeout=10))
            vm = subprocess.check_output(['vm_stat'], text=True, stderr=subprocess.DEVNULL, timeout=10)
            page = int(re.search(r'page size of (\d+)', vm).group(1))
            counts = dict(re.findall(r'^(Pages [^:]+):\s+(\d+)', vm, re.M))
            ram['available_bytes'] = page*sum(int(counts.get(k, 0)) for k in ('Pages free', 'Pages inactive', 'Pages speculative'))
        except (OSError, ValueError, subprocess.SubprocessError, AttributeError):
            pass
    gpus = []; gpu_error = None
    smi = shutil.which('nvidia-smi')
    if smi:
        try:
            result = subprocess.run([smi, '--query-gpu=index,uuid,name,memory.total,memory.free,compute_cap,driver_version', '--format=csv,noheader,nounits'], capture_output=True, text=True, check=True, timeout=15)
            for line in result.stdout.strip().splitlines():
                i, uid, name, total, free, capability, driver = [x.strip() for x in line.split(',')]
                gpus.append(dict(index=int(i), uuid=uid, name=name, total_bytes=int(float(total)*1024**2), free_bytes=int(float(free)*1024**2), compute_capability=float(capability), driver=driver))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            gpu_error = str(exc)
    else:
        gpu_error = 'nvidia-smi unavailable'
    boot = Path('/proc/sys/kernel/random/boot_id')
    return dict(python=sys.version, python_version=list(sys.version_info[:3]), os=platform.system(), platform=platform.platform(),
                packages=packages, gpus=gpus, gpu_error=gpu_error, ram=ram,
                disk=dict(path=str(Path(path).resolve()), free_bytes=shutil.disk_usage(path).free),
                colab='google-colab' in packages and Path('/content').is_dir(),
                runtime_id=boot.read_text().strip() if boot.exists() else platform.node())


def hardware_key(info):
    return digest(dict(runtime_id=info['runtime_id'], python=info['python'], os=info['os'],
                       gpus=[{k:g[k] for k in ('index','uuid','name','total_bytes','compute_capability','driver')} for g in info['gpus']]))


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        raw = response.read(5_000_001)
    if len(raw) > 5_000_000: raise ValueError('metadata payload exceeds limit')
    return json.loads(raw)


def resolve_checkpoint(settings, fetch=fetch_json):
    model = settings.model
    repo = model.model_id
    info = fetch('https://huggingface.co/api/models/' + repo + '/revision/' + urllib.parse.quote(model.revision or 'main', safe=''))
    revision = info.get('sha', '')
    if info.get('id') != repo or not re.fullmatch('[a-f0-9]{40}', revision):
        raise ValueError('checkpoint identity/revision could not be verified')
    if model.revision and re.fullmatch('[a-f0-9]{40}', model.revision) and model.revision != revision:
        raise ValueError('resolved checkpoint revision mismatch')
    config = fetch(f'https://huggingface.co/{repo}/resolve/{revision}/config.json')
    index = fetch(f'https://huggingface.co/{repo}/resolve/{revision}/model.safetensors.index.json')
    params = info.get('safetensors', {}).get('total')
    size = index.get('metadata', {}).get('total_size')
    if not isinstance(params, int) or params < 20_000_000_000 or not isinstance(size, int) or size < params*2:
        raise ValueError('official full BF16 parameter/weight metadata missing or inconsistent')
    if config.get('model_type') != 'gpt_oss' or config.get('quantization_config') or config.get('dtype', config.get('torch_dtype')) != 'bfloat16':
        raise ValueError('unsupported architecture/quantized checkpoint')
    for key in ('num_hidden_layers', 'num_key_value_heads', 'head_dim', 'max_position_embeddings'):
        if not isinstance(config.get(key), int) or config[key] <= 0: raise ValueError('missing model memory dimensions')
    return dict(model_id=repo, requested_revision=model.revision, revision=revision, total_parameters=params,
                weight_bytes=size, precision=model.precision, quantization='NONE', quantization_source=None,
                quantization_revision=None, config=config)


def preflight(settings, info, checkpoint, prompt_bytes=0):
    cfg = settings.inference
    reasons = []
    gpus = [g for g in info['gpus'] if g['index'] == cfg.gpu_index]
    gpu = gpus[0] if len(gpus) == 1 else None
    if not gpu: reasons.append('NO_SELECTED_NVIDIA_GPU')
    if info['os'] != 'Linux': reasons.append('UNSUPPORTED_RUNTIME_OS')
    if tuple(info['python_version'][:2]) < (3, 12): reasons.append('PYTHON_3_12_REQUIRED')
    if gpu and gpu['compute_capability'] < (8.0 if settings.model.precision == 'BF16' else 7.0): reasons.append('PRECISION_UNSUPPORTED')
    model = checkpoint['config']
    tokens = cfg.max_context_tokens
    # Full-length KV at every layer is deliberately conservative for mixed sliding/full attention.
    kv_bytes = 2*model['num_hidden_layers']*model['num_key_value_heads']*model['head_dim']*tokens*2
    weight_bytes = max(checkpoint['weight_bytes'], checkpoint['total_parameters']*2)
    required_gpu = weight_bytes + kv_bytes + cfg.memory_overhead_gib*GIB
    required_ram = weight_bytes*cfg.ram_weight_multiplier
    required_disk = weight_bytes*cfg.disk_weight_multiplier + 5*GIB
    if gpu and required_gpu > min(gpu['total_bytes'],gpu['free_bytes'])*cfg.gpu_safety_fraction: reasons.append('INSUFFICIENT_GPU_MEMORY')
    if info['ram']['available_bytes'] is None or info['ram']['available_bytes'] < required_ram: reasons.append('INSUFFICIENT_SYSTEM_RAM')
    if info['disk']['free_bytes'] < required_disk: reasons.append('INSUFFICIENT_DISK')
    if tokens > model['max_position_embeddings'] or cfg.max_new_tokens >= tokens: reasons.append('INVALID_CONTEXT_BUDGET')
    # Tokenizer is checked exactly in the worker before weights load. Bytes are a safe upper bound for this byte-level tokenizer.
    if prompt_bytes + cfg.max_new_tokens > tokens: reasons.append('PROMPT_CONTEXT_UPPER_BOUND_EXCEEDED')
    return dict(passed=not reasons, reasons=reasons, required_gpu_bytes=required_gpu, full_weight_bytes=weight_bytes,
                kv_cache_bytes=kv_bytes, required_ram_bytes=required_ram, required_disk_bytes=required_disk,
                selected_gpu=gpu, hardware_key=hardware_key(info), estimate='full weights + conservative KV + explicit workspace reserve; no CPU offload')
