"""TAPD story → 平台 Requirement 字段映射。

- 描述 HTML → 纯文本/轻 Markdown（首版策略：去标签、列表项转 "- "，段落转换行）；附件不下载托管，只在 extra 存链接
- 状态：优先用 v_status（中文，with_v_status=1 返回）作 external_status；平台 status 字段统一置哨兵值 'synced'
  （不进平台状态机——TAPD 镜像需求在 TAPD 侧流转，平台不管流转）
- 优先级：TAPD high/middle/low/nice → 平台 P0/P1/P2
"""

import html
import json
import re

# TAPD 镜像需求的平台状态哨兵：不在状态机流转表里，天然只读（apply_transition 会 InvalidTransition）
TAPD_STATUS = "synced"

_PRIORITY_MAP = {
    "high": "P0", "urgent": "P0",
    "middle": "P1", "normal": "P1",
    "low": "P2", "nice": "P2",
}


def map_priority(tapd_priority: str | None) -> str:
    return _PRIORITY_MAP.get((tapd_priority or "").strip().lower(), "P1")


def html_to_text(raw: str | None) -> str:
    """TAPD 描述 HTML → 纯文本（首版：保留基本结构，不做完整富文本还原）。"""
    if not raw:
        return ""
    s = raw
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</p>", "\n\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "\n- ", s)
    s = re.sub(r"(?i)</(ul|ol|div|h[1-6])>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)          # 去掉其余标签
    s = html.unescape(s)                    # 实体还原 &amp; 等
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


# story 里进 external_extra 的字段（保留 TAPD 全量关键信息，不丢）
_EXTRA_KEYS = (
    "workspace_id", "iteration_id", "label", "effort", "effort_completed",
    "begin", "due", "creator", "created", "modified", "status", "custom_field_1",
)


def build_extra(story: dict) -> dict:
    """从 story 抽取兜底字段 + 附件链接进 external_extra。"""
    extra = {k: story[k] for k in _EXTRA_KEYS if story.get(k)}
    # 附件：首版只存链接引用（不下载托管）
    attachments = story.get("attachments") or story.get("Attachment")
    if attachments:
        extra["attachments"] = attachments
    return extra


def tapd_url(workspace_id: str, story_id: str) -> str:
    return f"https://www.tapd.cn/{workspace_id}/prong/stories/view/{story_id}"


def map_story(story: dict, project_id: int, assignee: str, creator: str) -> dict:
    """把一条 TAPD story 映射为 Requirement 的可写字段字典（供 upsert）。

    assignee：owner 经用户映射后的平台 username（映射不到则原 nick）。
    creator：本次同步的操作人（平台 username）——镜像需求的平台侧“拥有者”。
    """
    wid = str(story.get("workspace_id") or "")
    sid = str(story.get("id") or "")
    return {
        "project_id": project_id,
        "source": "tapd",
        "external_id": sid,
        "external_url": tapd_url(wid, sid),
        "external_status": (story.get("v_status") or story.get("status") or "").strip(),
        "title": (story.get("name") or "(无标题)")[:255],
        "description": html_to_text(story.get("description")),
        "priority": map_priority(story.get("priority")),
        "assignee": assignee,
        "creator": creator,
        "status": TAPD_STATUS,
        "req_type": "business",
        "external_extra": json.dumps(build_extra(story), ensure_ascii=False),
    }
