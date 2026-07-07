import json
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RequirementCreate(BaseModel):
    project_id: int
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    req_type: str = Field(default="business", pattern="^(business|system)$")
    parent_id: int | None = None
    priority: str = Field(default="P1", pattern="^P[0-2]$")
    expected_online_date: date | None = None


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    parent_id: int | None
    req_type: str
    title: str
    description: str
    status: str
    priority: str
    complexity: str | None
    expected_online_date: date | None
    creator: str
    created_at: datetime
    updated_at: datetime


class TransitionIn(BaseModel):
    action: str
    comment: str = ""
    artifact_type: str | None = None  # analysis_report / doc / mr / test_result
    artifact_ref: str | None = None


class ReviewCreate(BaseModel):
    participants: list[str] = []
    scheduled_at: datetime | None = None
    agenda: str | None = None  # 不传则服务端按模板自动生成


class ReviewConclude(BaseModel):
    conclusion: Literal["approved", "conditional", "rejected"]
    comment: str = ""


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requirement_id: int
    initiator: str
    agenda: str
    participants: list[str]
    scheduled_at: datetime | None
    conclusion: str | None
    conclusion_comment: str
    concluded_by: str | None
    concluded_at: datetime | None
    created_at: datetime

    @field_validator("participants", mode="before")
    @classmethod
    def _parse_participants(cls, v):
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                return parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                return []
        return v


class AnalysisRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requirement_id: int
    task_id: str | None
    status: str
    summary: str
    complexity: str | None
    report_md: str
    error: str
    created_by: str
    created_at: datetime
    finished_at: datetime | None


class AnalysisCallbackIn(BaseModel):
    run_id: int
    task_id: str = ""
    status: Literal["succeeded", "failed"]
    summary: str = ""
    complexity: str = ""
    report_md: str = ""
    error: str = ""


class FlowEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requirement_id: int
    from_status: str | None
    to_status: str
    action: str
    operator: str
    comment: str
    artifact_type: str | None
    artifact_ref: str | None
    created_at: datetime
