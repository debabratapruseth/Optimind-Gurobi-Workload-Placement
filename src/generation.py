"""Leakage-limited prompts and inert output parsing. Never executes generated code."""
import ast
import json
import re
from .formulation_ir import FormulationIR, parse_ir, MAX_BYTES
from .problem_contract import canonical_bytes, digest


def messages(contract, settings):
    track=settings.generation.mode;mode=settings.generation.prompt_mode
    system='You are an operations research formulation researcher. Preserve every mandatory banking requirement and declared objective. Do not simplify inputs or invent approvals. Report unsupported constructs explicitly.'
    data=dict(problem=contract.model_dump(mode='json'),problem_hash=digest(contract))
    if track=='NATIVE_GUROBIPY':
        system+=' Produce a mathematical description of decision variables, objective functions, hard constraints and auxiliary linearizations, followed by exactly one fenced python block containing a GurobiPy implementation. Your code will only be inspected, never executed.'
        if mode=='TEMPLATE_GUIDED': system+=' Organize the description into sets and parameters, variable domains, linear constraints, objective definitions and requirement coverage. Keep the complete model inside the provided license limits.'
    else:
        system+=' Return exactly one JSON object conforming to the provided IR schema. Use GENERAL_LINEAR_V1 for independently authored algebra. No Python, callbacks or nonlinear terms. Include the provided problem_hash unchanged. Expressions use constant plus a terms mapping; senses are LE/EQ/GE. Assignment metadata maps binary variables to application/environment/site. Include raw metric expressions and manifest statuses. Do not omit normalization or unsupported objectives.'
        data['output_schema']=FormulationIR.model_json_schema()
        data['limits']=dict(max_payload_bytes=MAX_BYTES,max_total_terms=100000,coefficient_max=1e12,nonzero_min=1e-12,significant_digits=17)
        if mode=='TEMPLATE_GUIDED': system+=' Separate variables, constraints, four metric expressions, prioritized objectives and requirement manifest. All variables need finite bounds. Link requirement claims to actual IDs; a label is not evidence. Use only explicit linear auxiliary structures where needed.'
    return [dict(role='system',content=system),dict(role='user',content=canonical_bytes(data).decode())]


def final_channel(raw):
    # Explicit model protocol delimiters only; the unmodified raw response is retained separately.
    split=re.split(r'<\|(?:channel|meta_sep)\|>final<\|(?:message|im_sep)\|>',raw)
    text=split[-1] if len(split)>1 else raw
    return re.sub(r'<\|(?:return|end|im_end|fim_suffix)\|>\s*$','',text).strip()


def parse_response(raw, track):
    if not isinstance(raw,str) or not raw.strip(): raise ValueError('EMPTY_RESPONSE')
    if len(raw.encode())>MAX_BYTES: raise ValueError('RESPONSE_SIZE_EXCEEDED')
    text=final_channel(raw)
    if text.startswith('UNSUPPORTED:'):
        return dict(format_valid=False,ir_payload=None,mathematics=None,code=None,static_inspection=None,unsupported_reason=text)
    blocks=list(re.finditer(r'^```([^\n]*)\n(.*?)^```\s*$',text,re.M|re.S))
    if track=='STRUCTURED_IR':
        if blocks:
            if len(blocks)!=1 or blocks[0].group(1).strip().lower()!='json' or text[:blocks[0].start()].strip() or text[blocks[0].end():].strip(): raise ValueError('AMBIGUOUS_IR_RESPONSE')
            payload=blocks[0].group(2).strip()
        else: payload=text
        # Parsing never normalizes, adds, or repairs generated fields.
        try: json.loads(payload)
        except ValueError as exc: raise ValueError('INVALID_JSON_RESPONSE') from exc
        return dict(format_valid=True,ir_payload=payload,mathematics=None,code=None,static_inspection=None)
    if len(blocks)!=1 or blocks[0].group(1).strip().lower() not in ('python','py'): raise ValueError('EXPECTED_ONE_PYTHON_BLOCK')
    code=blocks[0].group(2);math=(text[:blocks[0].start()]+text[blocks[0].end():]).strip()
    inspection=dict(status='STATICALLY_INSPECTED',syntax_valid=False,executed=False,security_findings=[])
    try:
        tree=ast.parse(code)
        inspection['syntax_valid']=True
        for node in ast.walk(tree):
            if isinstance(node,(ast.Import,ast.ImportFrom)):
                modules=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or '']
                for module in modules:
                    if module.split('.')[0] not in ('gurobipy','math','itertools','collections'):
                        inspection['security_findings'].append('IMPORT:'+module)
            if isinstance(node,ast.Call):
                name=node.func.id if isinstance(node.func,ast.Name) else node.func.attr if isinstance(node.func,ast.Attribute) else ''
                if name in ('eval','exec','compile','__import__','open','system','popen','run','check_output','request','urlopen'):
                    inspection['security_findings'].append('CALL:'+name)
        inspection['security_findings']=sorted(set(inspection['security_findings']))
    except (SyntaxError,RecursionError) as exc:
        inspection.update(status='PARSED_NOT_VALID_PYTHON',error=str(exc))
    return dict(format_valid=bool(math),mathematics=math,code=code,ir_payload=None,static_inspection=inspection)


def outcomes(report=None):
    if report is None:
        return dict(ir_schema_valid=None,compilation_success=None,canonical_recognition=None,bounded_behavioral_equivalence=None,constraint_completeness='UNVERIFIED',placement_feasible=None,objective_correct=None,optimality_gap=None,mathematical_outcome='UNVERIFIED')
    levels=report.get('levels',{});eq=levels.get('5_equivalence',{});faith=levels.get('3_fidelity',{})
    complete=eq.get('complete',False)
    equal=complete and not any(eq.get(k,0) for k in ('extra_infeasible','missing_feasible','metric_mismatches','objective_mismatches'))
    witnessed=any(eq.get(k,0) for k in ('extra_infeasible','missing_feasible','metric_mismatches','objective_mismatches'))
    recognized=faith.get('recognized',False)
    return dict(ir_schema_valid=levels.get('1_schema')=='PASS',compilation_success=report.get('compilation',{}).get('status')=='COMPILED',
                canonical_recognition=recognized,bounded_behavioral_equivalence=equal if complete else None,
                constraint_completeness='VERIFIED_CANONICAL_BOUNDED' if recognized and equal else 'COUNTEREXAMPLE' if eq.get('extra_infeasible') or eq.get('missing_feasible') else 'UNVERIFIED',
                placement_feasible=report.get('placement_audit',{}).get('valid'),objective_correct=not(eq.get('metric_mismatches') or eq.get('objective_mismatches')) if complete else None,
                optimality_gap=report.get('reference_gap'),mathematical_outcome='COUNTEREXAMPLE' if witnessed else 'BOUNDED_EQUIVALENT' if equal else 'UNVERIFIED',
                phase2a_classification=report['classification'])
