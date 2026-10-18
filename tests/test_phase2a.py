"""Contract, algebra, malicious submissions and bounded formulation verification."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import gurobipy as gp
import pytest
from src.config import load
from src.portfolio import generate
from src.problem_contract import ProblemContract, from_config, inputs, canonical_bytes, digest
from src.formulation_ir import parse_ir, MAX_BYTES
from src.ir_compiler import CompiledIR, restricted_environment
from src.ir_reference import direct_to_ir
from src.formulation_validation import verify_formulation
from src.research_attempts import evaluate_attempt, prompt_input, repair_feedback, aggregate, Attempt
from src.solver import LicenseSizeExceeded

ROOT = Path(__file__).resolve().parents[1]


def problem(name='single'):
    c, _ = load(ROOT / f'tests/fixtures/config/scenarios/{name}.yaml')
    return from_config(c, generate(c))


@pytest.fixture(scope='module')
def fixtures(tmp_path_factory):
    root = tmp_path_factory.mktemp('phase2a')
    return {name: (p := problem(name), direct_to_ir(p, root / name)) for name in ('single', 'medium', 'complex')}


def verify(p, ir, folder, **limits):
    return verify_formulation(p, canonical_bytes(ir), folder, **limits)


def remove_rows(ir, predicate):
    removed = {r['id'] for r in ir['constraints'] if predicate(r)}
    ir['constraints'] = [r for r in ir['constraints'] if r['id'] not in removed]
    for entry in ir['manifest']:
        entry['constraints'] = [k for k in entry['constraints'] if k not in removed]


def test_contract_determinism_and_neutrality():
    a = problem()
    assert canonical_bytes(a) == canonical_bytes(problem())
    c, _ = load(ROOT / 'tests/fixtures/config/scenarios/single_direct.yaml')
    assert digest(a) == digest(from_config(c, generate(c)))
    raw = canonical_bytes(a)
    assert all(x not in raw for x in (b'selected_index', b'formulation_method', b'optimal_solution', b'paths', b'python'))
    assert digest(a) == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize('mutation', ['unknown', 'bad_version', 'units', 'reference', 'nan'])
def test_contract_strict(mutation):
    data = problem().model_dump()
    if mutation == 'unknown': data['source_code'] = 'print(1)'
    if mutation == 'bad_version': data['contract_version'] = '2.0'
    if mutation == 'units': data['semantics']['cost'] = 'EUR'
    if mutation == 'reference': data['applications'][0]['dependencies'][0]['target'] = 'UNKNOWN'
    if mutation == 'nan': data['cost']['per_vcpu_monthly']['AWS_HK'] = float('nan')
    with pytest.raises(ValueError): ProblemContract.model_validate(data)


@pytest.mark.parametrize('name', ['single', 'medium', 'complex'])
def test_independent_equivalence(fixtures, name, tmp_path):
    p, ir = fixtures[name]
    r = verify(p, ir, tmp_path)
    assert r['classification'] == 'VALID_FORMULATION', r
    assert r['solver']['status'] == 'OPTIMAL'
    assert r['solver']['mip_gap'] == 0
    assert r['levels']['5_equivalence']['complete']
    assert r['levels']['5_equivalence']['reference_feasible_count'] == {'single': 9, 'medium': 4, 'complex': 282}[name]
    assert r['reference_gap'] == pytest.approx(0, abs=1e-8)


def test_large_is_unverified(fixtures, tmp_path):
    p, ir = fixtures['single']
    r = verify(p, ir, tmp_path, max_raw=1)
    assert r['placement_audit']['valid']
    assert r['classification'] == 'UNVERIFIED'


@pytest.mark.parametrize('attack', ['code', 'imports', 'callback', 'nonlinear', 'reference', 'bounds', 'bool', 'infinity', 'tiny', 'huge', 'duplicates', 'bytes', 'precision', 'vars', 'rows'])
def test_ir_rejects_unsafe_or_malformed(fixtures, attack):
    _, model = fixtures['single']
    ir = model.model_dump()
    if attack in ('code', 'imports', 'callback'): ir[attack] = '__import__("os").system("touch /tmp/forbidden")'
    if attack == 'nonlinear': ir['objectives'][0]['expression']['quadratic'] = [['x', 'x', 1]]
    if attack == 'reference': ir['constraints'][0]['expression']['terms']['missing'] = 1.
    if attack == 'bounds': ir['variables'][0]['upper'] = -1.
    if attack == 'bool': ir['variables'][0]['upper'] = True
    if attack == 'infinity': ir['variables'][0]['upper'] = float('inf')
    if attack == 'tiny': ir['objectives'][0]['expression']['constant'] = 1e-20
    if attack == 'huge': ir['objectives'][0]['expression']['constant'] = 1e13
    if attack == 'vars': ir['variables'] = [dict(id=f'v{i}', kind='BINARY', lower=0., upper=1., assignment=None) for i in range(1801)]
    if attack == 'rows': ir['constraints'] = [dict(ir['constraints'][0], id=f'r{i}') for i in range(1801)]
    payload = json.dumps(ir).encode()
    if attack == 'duplicates': payload = b'{"ir_version":"1.0","ir_version":"1.0"}'
    if attack == 'bytes': payload = b' ' * (MAX_BYTES + 1)
    if attack == 'precision': payload = payload.replace(b'0.0', b'0.1234567890123456789', 1)
    with pytest.raises(ValueError): parse_ir(payload)


def test_compiler_exact_algebra_and_multiobjective(fixtures, tmp_path):
    p, source = fixtures['single']
    ir = source.model_dump()
    # Generic bounded integer and continuous variables and signed GE/EQ expressions.
    ir['variables'] += [dict(id='integer', kind='INTEGER', lower=-2., upper=3.), dict(id='continuous', kind='CONTINUOUS', lower=-4., upper=5.)]
    ir['constraints'].append(dict(id='signed', family='test', sense='GE', rhs=-3., expression=dict(constant=2.5, terms={'integer': -2., 'continuous': 3.25})))
    ir['objectives'] = [dict(id='one', priority=9, weight=2., expression=dict(constant=1.25, terms={'integer': -4.})), dict(id='two', priority=2, weight=.5, expression=dict(constant=0., terms={'continuous': 2.}))]
    for entry in ir['manifest']: entry['objectives'] = []
    with restricted_environment(tmp_path) as env:
        compiled = CompiledIR(canonical_bytes(ir), p.solver.model_dump(), env)
        try:
            m = compiled.model
            for row in ir['constraints']:
                actual = m.getConstrByName(row['id'])
                assert actual.Sense == {'LE': '<', 'GE': '>', 'EQ': '='}[row['sense']]
                assert actual.RHS == pytest.approx(row['rhs'] - row['expression']['constant'])
                for name, coef in row['expression']['terms'].items(): assert m.getCoeff(actual, compiled.variables[name]) == coef
            assert compiled.variables['integer'].VType == 'I'
            assert compiled.variables['integer'].LB == -2
            assert compiled.variables['continuous'].UB == 5
            for i, o in enumerate(ir['objectives']):
                m.Params.ObjNumber = i
                assert m.ObjNPriority == o['priority'] and m.ObjNWeight == o['weight']
                assert m.getObjective(i).getConstant() == o['expression']['constant']
            assert compiled.optimize()['status'] == 'OPTIMAL'
        finally: compiled.close()


def test_guard_before_every_optimize(fixtures, tmp_path, monkeypatch):
    p, ir = fixtures['single']
    with restricted_environment(tmp_path) as env:
        compiled = CompiledIR(ir, p.solver.model_dump(), env)
        try:
            compiled.model.addVars(1800, vtype=gp.GRB.BINARY)
            def forbidden(*args): pytest.fail('oversized model optimized')
            monkeypatch.setattr(gp.Model, 'optimize', forbidden)
            with pytest.raises(LicenseSizeExceeded): compiled.optimize()
        finally: compiled.close()


@pytest.mark.parametrize('mutation', ['manifest', 'completeness', 'dr', 'tco', 'concentration', 'transitive', 'objective'])
def test_mutated_algebra_detected(fixtures, mutation, tmp_path):
    p, model = fixtures['complex' if mutation == 'transitive' else 'single']
    ir = model.model_dump()
    if mutation == 'manifest': ir['manifest'][0]['status'] = 'NOT_REPRESENTED'
    if mutation == 'completeness': remove_rows(ir, lambda r: r['family'] == 'placement')
    if mutation == 'dr':
        for r in ir['constraints']:
            if r['family'] == 'capacity': r['expression']['terms'] = {k: v/2 for k, v in r['expression']['terms'].items()}
    if mutation in ('tco', 'concentration'):
        ir['metrics'][mutation]['constant'] += -100. if mutation == 'tco' else .1
    if mutation == 'transitive': remove_rows(ir, lambda r: r['id'].startswith('failure_lower'))
    if mutation == 'objective': ir['objectives'][0]['expression']['constant'] += .1
    r = verify(p, ir, tmp_path)
    assert r['classification'] not in ('VALID_FORMULATION', 'UNVERIFIED'), r


def test_underconstrained_capacity(fixtures, tmp_path):
    p, model = fixtures['medium']
    ir = model.model_dump()
    remove_rows(ir, lambda r: r['family'] == 'capacity')
    r = verify(p, ir, tmp_path)
    assert r['classification'] == 'UNDERCONSTRAINED'
    assert r['levels']['5_equivalence']['extra_infeasible'] > 0


def test_overconstrained(fixtures, tmp_path):
    p, model = fixtures['single']
    ir = model.model_dump()
    v = next(v['id'] for v in ir['variables'] if v['assignment'])
    ir['constraints'].append(dict(id='extra', family='extra', expression=dict(terms={v: 1.}, constant=0.), sense='EQ', rhs=0.))
    r = verify(p, ir, tmp_path)
    assert r['classification'] == 'OVERCONSTRAINED'


@pytest.mark.parametrize('mutation', ['regulatory', 'service', 'approval', 'reverse'])
def test_unary_and_directed_mutations(mutation, tmp_path):
    p = problem('medium' if mutation == 'reverse' else 'single')
    data = p.model_dump()
    if mutation == 'regulatory':
        for policy in data['regulatory']['policies']: policy['approved_providers'] = ['AWS']
    if mutation == 'service': data['sites']['service_category_overrides']['AWS_HK'] = []
    if mutation == 'approval':
        data['regulatory']['materiality']['MATERIAL']['approval_status'] = 'PENDING'
        data['objectives']['infeasibility']['remediation_analysis'] = False
    if mutation == 'reverse': data['applications'][0]['dependencies'][1]['max_p95_latency_ms'] = 8.
    p = ProblemContract.model_validate(data)
    bad = deepcopy(data)
    if mutation == 'regulatory':
        for policy in bad['regulatory']['policies']: policy['approved_providers'] = ['AWS', 'AZURE', 'GLOBAL_DC', 'COUNTRY_DC']
    if mutation == 'service': bad['sites']['service_category_overrides'].pop('AWS_HK')
    if mutation == 'approval': bad['regulatory']['materiality']['MATERIAL']['approval_status'] = 'APPROVED'
    if mutation == 'reverse':
        matrix = bad['dependencies']['latency_matrix_ms']
        bad['dependencies']['latency_matrix_ms'] = {s: {t: matrix[t][s] for t in row} for s, row in matrix.items()}
    ir = direct_to_ir(ProblemContract.model_validate(bad), tmp_path / 'mutation').model_dump()
    ir['problem_hash'] = digest(p)
    r = verify(p, ir, tmp_path / 'verify')
    assert r['classification'] not in ('VALID_FORMULATION', 'UNVERIFIED'), r


def test_hierarchical_contract_and_compiler(tmp_path):
    data = problem().model_dump()
    data['objectives']['strategy'] = 'HIERARCHICAL'
    p = ProblemContract.model_validate(data)
    ir = direct_to_ir(p, tmp_path / 'export')
    r = verify(p, ir, tmp_path / 'verify')
    assert r['classification'] == 'VALID_FORMULATION'
    assert r['solver']['mip_gap'] is None


def context(p):
    return dict(experiment_id='test', benchmark_id='single', model_identifier='trusted', model_version='1', inference_backend='NONE', prompt_mode='AUTONOMOUS', prompt_hash=digest(prompt_input(p, 'AUTONOMOUS')), generation_seed=42, generation_parameters={}, attempt_number=1, repair_iteration=0, generation_seconds=0.)


def test_attempt_preserves_failures_and_hashes(fixtures, tmp_path):
    p, _ = fixtures['single']
    payload = b'{"python":"import os"}'
    result = evaluate_attempt(p, payload, context(p), tmp_path / 'failed')
    assert result.failure_classification == 'INVALID_FORMULATION'
    assert result.ir_hash == hashlib.sha256(payload).hexdigest()
    manifest = json.loads((tmp_path / 'failed/COMPLETE.json').read_text())
    for relative, expected in manifest.items():
        assert hashlib.sha256((tmp_path / 'failed' / relative).read_bytes()).hexdigest() == expected
    assert Attempt.model_validate(json.loads((tmp_path / 'failed/attempt.json').read_text())) == result
    with pytest.raises(FileExistsError): evaluate_attempt(p, payload, context(p), tmp_path / 'failed')
    assert bytes.fromhex(json.loads((tmp_path / 'failed/submission.json').read_text())['bytes']) == payload
    assert aggregate([result])['pass_at_1'] == 0
    assert aggregate([result])['pass_at_5'] is None


def test_prompt_and_feedback_do_not_leak_reference(fixtures, tmp_path):
    p, ir = fixtures['single']
    for mode in ('AUTONOMOUS', 'TEMPLATE_GUIDED'):
        prompt = prompt_input(p, mode)
        assert set(prompt) <= {'problem', 'output_schema', 'mode', 'guidance'}
        assert 'source_code' not in canonical_bytes(prompt).decode()
    r = verify(p, ir, tmp_path)
    feedback = repair_feedback(r)
    assert set(feedback) == {'classification', 'schema_pass', 'placement_valid', 'fidelity_recognized'}
    assert not any(k in feedback for k in ('reference_objective', 'placement', 'metrics', 'normalization_ranges', 'error'))


def test_compiler_requires_verified_license_environment(fixtures):
    p, ir = fixtures['single']
    with gp.Env(params={'OutputFlag': 0}) as env:
        with pytest.raises(ValueError, match='verified restricted environment'):
            CompiledIR(ir, p.solver.model_dump(), env)


def test_manifest_claim_without_algebra_fails(fixtures, tmp_path):
    p, source = fixtures['single']
    ir = source.model_dump()
    ir['constraints'] = [r for r in ir['constraints'] if r['family'] != 'capacity']
    r = verify(p, ir, tmp_path)
    assert r['classification'] == 'INVALID_FORMULATION'
    assert r['levels']['1_schema'] == 'FAIL'


def test_configured_guard_and_tampered_model_instance(fixtures, tmp_path):
    p, original = fixtures['single']
    with restricted_environment(tmp_path) as env:
        solver = p.solver.model_dump()
        solver['safety_limits']['max_variables'] = 1
        with pytest.raises(LicenseSizeExceeded): CompiledIR(original, solver, env)
        forged = original.model_copy(deep=True)
        forged.variables[0].lower = -1.
        with pytest.raises(ValueError): CompiledIR(forged, p.solver.model_dump(), env)


def test_suboptimal_solution_classification(fixtures, tmp_path, monkeypatch):
    p, ir = fixtures['single']
    original = CompiledIR.optimize
    def stop_with_suboptimal(self):
        # Simulate a valid early incumbent: maximize the submitted weighted score,
        # restore minimization sense without another solve, report TIME_LIMIT.
        if not self.history:
            self.model.ModelSense = gp.GRB.MAXIMIZE
            stats = original(self)
            stats.update(status='TIME_LIMIT', status_code=gp.GRB.TIME_LIMIT, optimality_proven=False)
            return stats
        return original(self)
    monkeypatch.setattr(CompiledIR, 'optimize', stop_with_suboptimal)
    result = verify(p, ir, tmp_path)
    assert result['classification'] == 'VALID_BUT_SUBOPTIMAL_SOLUTION'
    assert result['placement_audit']['valid']
    assert result['reference_gap'] > 0


def test_pass_at_five_and_repairs(fixtures, tmp_path):
    p, _ = fixtures['single']
    failed = evaluate_attempt(p, b'{}', context(p), tmp_path / 'fail').model_dump()
    rows = []
    for i in range(1, 6):
        row = deepcopy(failed)
        row['context']['attempt_number'] = i
        rows.append(row)
    rows[4]['failure_classification'] = 'VALID_FORMULATION'
    rows[4]['independent_placement_audit'] = {'status': 'DEPLOYABLE'}
    rows[4]['solver'] = {'optimality_proven': True}
    repaired = deepcopy(rows[4])
    repaired['context'].update(attempt_number=1, repair_iteration=1)
    result = aggregate(rows + [repaired])
    assert result['pass_at_1'] == 0 and result['pass_at_5'] == 1
    assert result['repair_success_rate'] == 1
    with pytest.raises(ValueError, match='duplicate'): aggregate(rows + [rows[0]])


def test_unknown_equivalent_profile_unverified(fixtures, tmp_path):
    p, ir = fixtures['single']
    data = ir.model_dump()
    data['profile'] = 'GENERAL_LINEAR_V1'
    result = verify(p, data, tmp_path)
    assert result['levels']['5_equivalence']['complete']
    assert result['classification'] == 'UNVERIFIED'


def test_persisted_schemas_and_fixtures_are_current():
    from src.formulation_ir import FormulationIR
    for filename, schema in [('problem-contract-1.0', ProblemContract), ('formulation-ir-1.0', FormulationIR), ('research-attempt-1.0', Attempt)]:
        assert json.loads((ROOT / f'schemas/{filename}.json').read_text()) == schema.model_json_schema()
    root = ROOT / 'tests/fixtures/phase2a'
    contract = ProblemContract.model_validate(json.loads((root / 'single_problem.json').read_text()))
    ir = parse_ir((root / 'single_trusted_ir.json').read_bytes())
    assert ir.problem_hash == digest(contract)
    with pytest.raises(ValueError): parse_ir((root / 'rejected_executable.json').read_bytes())
