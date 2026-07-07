from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


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
