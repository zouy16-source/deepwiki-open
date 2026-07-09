"""TAPD OpenAPI 客户端：拉取需求（story）。

企业级 OpenAPI，Basic Auth（公司一套 api_user/api_password），GET https://api.tapd.cn/stories，
workspace_id 必填、owner 过滤处理人、with_v_status=1 直接拿中文状态名、limit≤200 分页。
凭证经环境变量配置（见 config.Settings）。

TAPD_FAKE=1 时返回内置样例，用于离线验证同步逻辑（无凭证）；真实调用逻辑就绪，配好凭证即生效。
"""

import logging

import httpx

from .config import settings

logger = logging.getLogger(__name__)

TAPD_BASE = "https://api.tapd.cn"
PAGE_LIMIT = 200


class TapdError(Exception):
    pass


def _fake_stories(workspace_id: str, owner: str) -> list[dict]:
    """离线样例（TAPD_FAKE=1）：两条不同状态的需求（owner 用固定 nick，便于验证映射）。"""
    who = owner or "王产品"
    return [
        {
            "id": "1120000000001000123",
            "name": "运单批量导入支持 Excel 模板校验",
            "description": "<p>业务方希望批量导入运单时<strong>前置校验</strong>模板字段：</p><ul><li>必填项缺失即整单驳回</li><li>错误行标红导出</li></ul>",
            "status": "in_progress",
            "v_status": "实现中",
            "priority": "high",
            "owner": who,
            "creator": "王产品",
            "created": "2026-06-20 10:12:00",
            "modified": "2026-07-01 15:30:00",
            "iteration_id": "1120000000001999001",
            "workspace_id": workspace_id,
            "label": "运单;导入",
            "effort": "5",
        },
        {
            "id": "1120000000001000456",
            "name": "对账单导出增加客户维度筛选",
            "description": "<p>财务对账需按客户导出，含结算状态列。</p>",
            "status": "resolved",
            "v_status": "已实现",
            "priority": "middle",
            "owner": who,
            "creator": "李业务",
            "created": "2026-05-11 09:00:00",
            "modified": "2026-06-28 18:05:00",
            "iteration_id": "",
            "workspace_id": workspace_id,
            "label": "对账;导出",
            "effort": "3",
        },
    ]


def fetch_stories(workspace_id: str, owner: str) -> list[dict]:
    """拉取某 workspace 下、指定处理人(owner)的全部需求（分页取完）。

    返回 Story dict 列表（已从 {"Story": {...}} 解包）。owner 为空则不按处理人过滤（全量）。
    """
    if settings.tapd_fake:
        return _fake_stories(workspace_id, owner)

    if not (settings.tapd_api_user and settings.tapd_api_password):
        raise TapdError("TAPD 凭证未配置（TAPD_API_USER / TAPD_API_PASSWORD）")

    stories: list[dict] = []
    page = 1
    with httpx.Client(
        base_url=TAPD_BASE,
        auth=(settings.tapd_api_user, settings.tapd_api_password),
        timeout=settings.tapd_timeout,
    ) as client:
        while True:
            params = {
                "workspace_id": workspace_id,
                "with_v_status": 1,
                "limit": PAGE_LIMIT,
                "page": page,
            }
            if owner:
                params["owner"] = owner
            try:
                resp = client.get("/stories", params=params)
                resp.raise_for_status()
                body = resp.json()
            except httpx.HTTPError as e:
                raise TapdError(f"TAPD 接口调用失败（page={page}）：{e}")

            if body.get("status") != 1:
                raise TapdError(f"TAPD 返回异常：{body.get('info')}")

            batch = [item.get("Story", {}) for item in (body.get("data") or [])]
            stories.extend(b for b in batch if b.get("id"))
            if len(batch) < PAGE_LIMIT:
                break
            page += 1
            if page > 100:  # 硬上限，防异常分页死循环
                logger.warning("TAPD 分页超过 100 页，提前停止 workspace=%s", workspace_id)
                break

    return stories
