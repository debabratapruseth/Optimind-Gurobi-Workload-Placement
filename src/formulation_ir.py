"""Data-only linear MILP language. No executable extensions or dynamic dispatch."""
import json
import math
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import Field, AfterValidator, model_validator
from .schema import Strict
from .problem_contract import canonical_bytes

MAX_BYTES = 2_000_000
MAX_TERMS = 1800
MAX_TOTAL_TERMS = 100_000
ID = Annotated[str, Field(min_length=1, max_length=200, pattern=r'^[A-Za-z0-9_.,:\[\]/ -]+$')]
Hash = Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
Metric = Literal['tco', 'latency', 'concentration', 'blast_radius']


def number(v):
    if not math.isfinite(v) or abs(v) > 1e12:
        raise ValueError('numeric magnitude exceeds 1e12')
    if len(Decimal(str(v)).as_tuple().digits) > 17:
        raise ValueError('numeric precision exceeds 17 significant digits')
    if v and abs(v) < 1e-12:
        raise ValueError('nonzero numeric magnitude below 1e-12')
    return v

Number = Annotated[float, AfterValidator(number)]


class Assignment(Strict):
    application: ID
    environment: ID
    site: ID


class Variable(Strict):
    id: ID
    kind: Literal['BINARY', 'INTEGER', 'CONTINUOUS']
    lower: Number
    upper: Number
    assignment: Assignment | None = None
    @model_validator(mode='after')
    def domain(self):
        if self.lower > self.upper:
            raise ValueError('reversed bounds')
        if self.kind == 'BINARY' and (self.lower not in (0, 1) or self.upper not in (0, 1)):
            raise ValueError('binary bounds must be 0/1')
        if self.kind == 'INTEGER' and (not self.lower.is_integer() or not self.upper.is_integer()):
            raise ValueError('integer bounds must be integral')
        if self.assignment is not None and self.kind != 'BINARY':
            raise ValueError('placement metadata requires binary domain')
        return self


class Expression(Strict):
    constant: Number = 0.0
    terms: dict[ID, Number] = Field(default_factory=dict, max_length=MAX_TERMS)


class Constraint(Strict):
    id: ID
    family: ID
    expression: Expression
    sense: Literal['LE', 'EQ', 'GE']
    rhs: Number


class Objective(Strict):
    id: ID
    expression: Expression
    priority: int = Field(ge=0, le=100)
    weight: Number = Field(gt=0)


class ManifestEntry(Strict):
    requirement: ID
    status: Literal['REPRESENTED', 'NOT_REPRESENTED', 'UNSUPPORTED', 'NOT_APPLICABLE']
    variables: list[ID] = Field(default_factory=list, max_length=1800)
    constraints: list[ID] = Field(default_factory=list, max_length=1800)
    objectives: list[ID] = Field(default_factory=list, max_length=16)
    metrics: list[Metric] = Field(default_factory=list)


class FormulationIR(Strict):
    ir_version: Literal['1.0'] = '1.0'
    problem_hash: Hash
    profile: Literal['CANONICAL_DIRECT_V1', 'GENERAL_LINEAR_V1']
    variables: list[Variable] = Field(max_length=1800)
    constraints: list[Constraint] = Field(max_length=1800)
    metrics: dict[Metric, Expression]
    objectives: list[Objective] = Field(min_length=1, max_length=16)
    objective_sense: Literal['MIN', 'MAX'] = 'MIN'
    manifest: list[ManifestEntry] = Field(max_length=64)

    @model_validator(mode='after')
    def references(self):
        def unique(values):
            if len(values) != len(set(values)):
                raise ValueError('duplicate identifier')
            return set(values)
        vs = unique([v.id for v in self.variables])
        cs = unique([r.id for r in self.constraints])
        os = unique([o.id for o in self.objectives])
        unique([e.requirement for e in self.manifest])
        unique([(v.assignment.application, v.assignment.environment, v.assignment.site) for v in self.variables if v.assignment])
        expressions = [r.expression for r in self.constraints] + [o.expression for o in self.objectives] + list(self.metrics.values())
        if sum(len(e.terms) for e in expressions) > MAX_TOTAL_TERMS:
            raise ValueError('total expression size exceeded')
        for e in expressions:
            if not set(e.terms) <= vs:
                raise ValueError('unknown variable reference')
        for entry in self.manifest:
            if not set(entry.variables) <= vs or not set(entry.constraints) <= cs or not set(entry.objectives) <= os or not set(entry.metrics) <= set(self.metrics):
                raise ValueError('unknown manifest reference')
        if set(self.metrics) != {'tco', 'latency', 'concentration', 'blast_radius'}:
            raise ValueError('all four metric definitions required')
        return self


def parse_ir(payload):
    """Public trust boundary, including revalidation of existing model instances."""
    if isinstance(payload, FormulationIR):
        payload = canonical_bytes(payload)
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    if not isinstance(payload, bytes):
        raise ValueError('IR input must be serialized JSON bytes/text')
    if len(payload) > MAX_BYTES:
        raise ValueError('payload byte limit exceeded')
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ValueError('duplicate JSON key')
            out[k] = v
        return out
    def numeric(token):
        if len(Decimal(token).as_tuple().digits) > 17:
            raise ValueError('numeric precision exceeds 17 significant digits')
        return float(token)
    def invalid(token):
        raise ValueError('nonfinite JSON number')
    try:
        value = json.loads(payload.decode('utf-8'), object_pairs_hook=pairs, parse_float=numeric, parse_constant=invalid)
    except (RecursionError, UnicodeError) as exc:
        raise ValueError('malformed JSON encoding/depth') from exc
    ir = FormulationIR.model_validate(value)
    return ir
