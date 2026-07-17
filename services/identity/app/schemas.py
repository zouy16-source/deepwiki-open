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
    tapd_nick: str
    is_active: bool
    created_at: datetime

    @field_validator("tapd_nick", mode="before")
    @classmethod
    def _none_to_empty(cls, v):
        return v or ""


class UserUpdate(BaseModel):
    display_name: str | None = None
    email: str | None = None
    tapd_nick: str | None = None  # 绑定 TAPD 账号（nick），用于按当前用户同步 TAPD 需求
    is_active: bool | None = None


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


class RepoMeta(BaseModel):
    """一个绑定代码库的补充元数据（供编码 Worker 使用）。"""
    git_url: str = ""          # 可 clone 的 git 地址（如 https://git.ymdd.tech/组/仓库.git）
    default_branch: str = "main"


class ProjectCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    repos: list[str] = []
    repo_meta: dict[str, RepoMeta] = {}  # 名字 → {git_url, default_branch}
    tapd_workspace_id: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    repos: list[str] | None = None  # 绑定/解绑代码库（本地 clone 目录名）
    repo_meta: dict[str, RepoMeta] | None = None  # 补齐/更新代码库 git 地址
    tapd_workspace_id: str | None = None  # 绑定 TAPD workspace（项目）id


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str
    repos: list[str]
    repo_meta: dict[str, RepoMeta]
    tapd_workspace_id: str
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

    @field_validator("repo_meta", mode="before")
    @classmethod
    def _parse_repo_meta(cls, v):
        # 存量行/新列可能为 NULL 或 JSON 字符串；统一坍缩为 dict
        if v is None or v == "":
            return {}
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return v

    @field_validator("tapd_workspace_id", mode="before")
    @classmethod
    def _none_to_empty(cls, v):
        return v or ""


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
