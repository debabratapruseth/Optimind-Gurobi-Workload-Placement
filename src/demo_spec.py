"""Compact demo choices expanded by trusted code, never LLM-authored algebra.

Both objective encodings preserve the configured feasible set and objective.
The expanded model still requires independent exhaustive equivalence validation.
"""
import json
from typing import Literal
from pydantic import Field
from .schema import Strict
from .problem_contract import canonical_bytes, digest
from .formulation_ir import Hash, ID, parse_ir
from .generation import parse_response
from .ir_reference import direct_to_ir
from .persistence import json_write


class OptimizationSpec(Strict):
    spec_version: Literal['1.0']
    problem_hash: Hash
    application_id: ID
    formulation: Literal['DIRECT_ASSIGNMENT']
    objective_encoding: Literal['INLINE', 'EXPLICIT_SCORE']
    environment_order: list[ID] = Field(min_length=1, max_length=16)


def messages(contract):
    system = (
        'Select a compact optimization specification for one workload. Return ONLY one JSON object '
        'matching the schema; no explanation, thinking tags, Markdown, Python or coefficients. '
        'Use the exact problem_hash and application_id. environment_order must be a permutation '
        'of ALL configured environments; it orders assignment variables, not deployment priority. '
        'Choose INLINE for the normalized weighted objective directly on existing variables, or '
        'EXPLICIT_SCORE for a bounded auxiliary score variable linked by an equality. Both have '
        'identical business semantics; EXPLICIT_SCORE costs one variable and one row. Consider '
        'model size and explicit score inspectability. Do not propose placements or policy switches. '
        'Trusted code derives ALL mandatory constraints, domains, metrics, objective weights and '
        'normalization from the supplied inputs. Your role is formulation selection, not algebra authoring.'
    )
    return [dict(role='system', content=system), dict(role='user', content=canonical_bytes(dict(
        problem=contract.model_dump(mode='json'), problem_hash=digest(contract),
        output_schema=OptimizationSpec.model_json_schema())).decode())]


def parse_spec(raw, contract):
    if len(raw.encode()) > 65536:
        raise ValueError('SPEC_RESPONSE_TOO_LARGE')
    payload = parse_response(raw, 'STRUCTURED_IR')['ir_payload']
    if payload is None:
        raise ValueError('UNSUPPORTED_SPEC')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('DUPLICATE_SPEC_KEY: ' + key)
            result[key] = value
        return result
    spec = OptimizationSpec.model_validate(json.loads(payload, object_pairs_hook=unique))
    if len(contract.applications) != 1 or contract.objectives.strategy != 'WEIGHTED':
        raise ValueError('SPEC_SCOPE_REQUIRES_ONE_APPLICATION_WEIGHTED')
    app = contract.applications[0]
    if spec.problem_hash != digest(contract) or spec.application_id != app.id:
        raise ValueError('SPEC_INPUT_IDENTITY_MISMATCH')
    if sorted(spec.environment_order) != sorted(app.environments):
        raise ValueError('SPEC_ENVIRONMENTS_MUST_MATCH_CONFIGURATION')
    return spec


def compile_spec(spec, contract, folder):
    # Recheck typed objects too: callers cannot skip identity/scope validation.
    spec = parse_spec(canonical_bytes(spec).decode(), contract)
    ir = direct_to_ir(contract, folder / 'trusted_expansion').model_dump()
    order = {e: i for i, e in enumerate(spec.environment_order)}
    ir['variables'].sort(key=lambda v: (
        order[v['assignment']['environment']] if v['assignment'] else len(order), v['id']))
    if spec.objective_encoding == 'EXPLICIT_SCORE':
        objective = ir['objectives'][0]
        expr = objective['expression']
        variables = {v['id']: v for v in ir['variables']}
        lo = hi = expr['constant']
        for name, coefficient in expr['terms'].items():
            a, b = (coefficient * variables[name][bound] for bound in ('lower', 'upper'))
            lo += min(a, b)
            hi += max(a, b)
        name = 'demo_normalized_score'
        row = 'demo_score_definition'
        if name in variables or any(r['id'] == row for r in ir['constraints']):
            raise ValueError('SPEC_RESERVED_ID_COLLISION')
        ir['variables'].append(dict(id=name, kind='CONTINUOUS', lower=lo, upper=hi, assignment=None))
        ir['constraints'].append(dict(id=row, family='objective', sense='EQ', rhs=expr['constant'],
            expression=dict(constant=0., terms={name: 1., **{k: -v for k, v in expr['terms'].items()}})))
        objective['expression'] = dict(constant=0., terms={name: 1.})
        claim = next(m for m in ir['manifest'] if m['requirement'] == 'objective')
        claim['variables'].append(name)
        claim['constraints'].append(row)
        # Generic profile truthfully identifies a different, trusted encoding.
        ir['profile'] = 'GENERAL_LINEAR_V1'
    expanded = parse_ir(canonical_bytes(ir))
    json_write(folder / 'expanded_ir.json', expanded.model_dump())
    json_write(folder / 'compilation_provenance.json', dict(
        algebra_author='TRUSTED_COMPILER', ai_role='FORMULATION_SELECTION',
        specification=spec.model_dump(), policy_source='IMMUTABLE_PROBLEM_CONTRACT',
        expanded_ir_hash=digest(expanded), variables=len(expanded.variables), constraints=len(expanded.constraints)))
    return expanded
