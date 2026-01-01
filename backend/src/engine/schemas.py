from __future__ import annotations

from pydantic import BaseModel, Field


class Stage1Response(BaseModel):
    model: str
    response: str


class Stage2Evaluation(BaseModel):
    label: str
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)


class Stage2JudgeOutput(BaseModel):
    evaluations: list[Stage2Evaluation]
    final_ranking: list[str]
    failure_modes_top1: list[str]
    verification_steps: list[str]

