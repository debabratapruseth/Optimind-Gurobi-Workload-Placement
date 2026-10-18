"""Future formulation boundary. No model downloads or generated-code execution."""
from typing import Protocol

class FormulationAdapter(Protocol):
    def formulate(self, problem: dict) -> dict: ...

# Configured inference is separate from the legacy formulation call.
from .optimind import OptiMindAdapter
