import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    display_name: str = ""
    email: str = ""
    source: str = Field(default="sso", pattern="^(sso|local)$")


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    email: str
    source: str
    is_active: bool
    created_at: datetime


class LoginVerifyRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1)


class RoleGrant(BaseModel):
    role: str
    project_id: int | None  # None = 全局角色（如平台管理员）


class LoginVerifyResponse(BaseModel):
    user: UserOut
    roles: list[RoleGrant]
    project_ids: list[int]


class ProjectCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    repos: list[str] = []


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    repos: list[str] | None = None  # 绑定/解绑代码库（本地 clone 目录名）


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str
    repos: list[str]
    created_at: datetime

    @field_validator("repos", mode="before")
    @classmethod
    def _parse_repos(cls, v):
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                return parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                return []
        return v


class AuditLogCreate(BaseModel):
    actor: str
    action: str
    resource_type: str
    resource_id: str = ""
    detail: str = ""


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor: str
    action: str
    resource_type: str
    resource_id: str
    detail: str
    created_at: datetime
