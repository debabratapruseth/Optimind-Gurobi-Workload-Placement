"""Text-only Transformers dependency/import checks. Never loads a checkpoint."""
import argparse
import importlib.metadata
import sys
from packaging.requirements import Requirement
from packaging.version import Version
from .persistence import json_write

PINS = {'torch': '2.13.0', 'transformers': '5.12.1', 'accelerate': '1.15.0'}


def check_packages(packages, vision_requirements=()):
    reasons = []
    for name, expected in PINS.items():
        actual = packages.get(name)
        # Preserve CUDA local versions, e.g. 2.13.0+cu130, without replacing them.
        if actual is None or Version(actual).public != expected:
            reasons.append(f'PACKAGE_VERSION:{name}:expected={expected}:actual={actual}')
    if 'torchvision' in packages:
        reasons.append('TORCHVISION_NOT_NEEDED_FOR_TEXT_ONLY: remove torchvision before inference')
        for declaration in vision_requirements:
            requirement = Requirement(declaration)
            if requirement.name.lower() == 'torch' and (requirement.marker is None or requirement.marker.evaluate()):
                if packages.get('torch') is None or not requirement.specifier.contains(packages['torch']):
                    reasons.append(f'TORCHVISION_TORCH_MISMATCH: requires {requirement}; installed torch={packages.get("torch")}')
    return dict(passed=not reasons, reasons=reasons, packages={k:packages.get(k) for k in (*PINS, 'torchvision')}, text_only=True)


def installed_check():
    packages = {d.metadata['Name'].lower(): d.version for d in importlib.metadata.distributions() if d.metadata['Name']}
    requirements = (importlib.metadata.requires('torchvision') or []) if 'torchvision' in packages else []
    return check_packages(packages, requirements)


def probe():
    report = installed_check()
    report.update(python=sys.version, imports_passed=False, cuda_available=False, model_loaded=False)
    if not report['passed']:
        return report  # Do not trigger the known broken lazy import.
    try:
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM, set_seed
        report.update(imports_passed=True, cuda_available=torch.cuda.is_available(), torch_cuda_version=torch.version.cuda)
        if not report['cuda_available']:
            report['reasons'].append('CUDA_NOT_AVAILABLE')
    except Exception as exc:
        report['reasons'].append(f'IMPORT_FAILURE:{type(exc).__name__}:{exc}')
    report['passed'] = not report['reasons']
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    report = probe()
    json_write(args.output, report)
    print(report)
    raise SystemExit(0 if report['passed'] else 2)

if __name__ == '__main__':
    main()
