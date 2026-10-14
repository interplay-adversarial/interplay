"""Description-driven research assessments, independent of any release gate.

Generation, target observations, judging and export have replaceable interfaces.
DataDesigner is the built-in generator/judge; targets never execute generated code.
"""

from .models import AssessmentRecord, AssessmentSpec, JudgeOutput, Observation, Probe
from .runner import run_assessment
from .storage import recover_assessment, to_arrow

__all__ = [
    "AssessmentRecord",
    "AssessmentSpec",
    "JudgeOutput",
    "Observation",
    "Probe",
    "recover_assessment",
    "run_assessment",
    "to_arrow",
]
