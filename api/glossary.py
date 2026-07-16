"""业务术语表：从代码的中英共现自动抽取「中文业务词 → 代码标识符」映射。

设计原则（关键）：术语表不是权威，是**带出处的检索线索**。
- 自动从代码抽（注释/字段声明的中英共现），不靠人工维护；代码变了重抽，不会漂移；
- 每条映射带 file:line 出处；
- 只作为 agent 的 grep 起点——agent 拿候选标识符去真实代码 grep 核验，命中才采信；
- 术语表错了顶多浪费一次检索，污染不了结论（结论仍由内容核验/对抗验证把关）。

纯 stdlib（re + os），跑在本地 clone 上。抽取结果按仓库缓存到 ~/.adalflow/glossary/<repo>.json。
"""

import json
import os
import re

from api.trace_tools import SKIP_DIRS, TEXT_EXTS, repos_root

_CN = r"[一-鿿]"
# 字段声明里的标识符：类型 + 名字 + 结束符；名字取最后一个标识符
_FIELD_IDENT = r"[a-zA-Z_$][\w$]*"

# 模式 1：Javadoc 单行中文注释 + 紧跟字段声明
#   /**
#    * 收货地区
#    */
#   private String consigneeArea;
_JAVADOC_FIELD = re.compile(
    r"/\*\*\s*\n\s*\*\s*(" + _CN + r"[^\n*]*?)\s*\n\s*\*/\s*\n"
    r"(?:\s*@\w+[^\n]*\n)*"                      # 可能夹着注解
    r"\s*(?:private|public|protected|final|static|transient|volatile|\s)+"
    r"[\w<>\[\],.\s]+?\s+(" + _FIELD_IDENT + r")\s*[;=]",
)

# 模式 2：行尾注释  private String consigneeArea; // 收货地区
_INLINE_FIELD = re.compile(
    r"^[ \t]*(?:private|public|protected|final|static|transient|volatile)"
    r"[\w<>\[\],.\s]+?\s+(" + _FIELD_IDENT + r")\s*[;=][^\n/]*?//\s*(" + _CN + r"[^\n]*)",
    re.MULTILINE,
)

# 模式 3：Vue/JS 对象属性行尾注释  consigneeArea: '', // 收货地区
_JS_PROP = re.compile(
    r"^[ \t]*[\"']?(" + _FIELD_IDENT + r")[\"']?\s*:[^\n/]*?//\s*(" + _CN + r"[^\n]*)",
    re.MULTILINE,
)

# 噪声中文注释（非业务词，抽了没用）
_NOISE = re.compile(r"(TODO|FIXME|以下|如下|例如|注意|默认|临时|测试|参数|返回|方法|构造)")
_STOP_IDENTS = {"serialVersionUID", "value", "data", "list", "result", "item", "temp", "obj"}


def _clean_cn(s: str) -> str:
    # 去掉结尾标点/说明，保留核心业务词
    s = re.split(r"[，。；：:,.\s（(]", s.strip(), 1)[0]
    return s.strip()


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def extract_from_source(src: str) -> list:
    """从单文件源码抽 (中文词, 标识符, 行号)。"""
    out = []
    for rx, cn_first in ((_JAVADOC_FIELD, False), (_INLINE_FIELD, True), (_JS_PROP, True)):
        for m in rx.finditer(src):
            ident, cn = (m.group(1), m.group(2)) if cn_first else (m.group(2), m.group(1))
            cn = _clean_cn(cn)
            if len(cn) < 2 or _NOISE.search(cn):
                continue
            if ident in _STOP_IDENTS or len(ident) < 3:
                continue
            out.append((cn, ident, _line_of(src, m.start())))
    return out


def build_glossary(root: str, max_files: int = 20000) -> dict:
    """遍历仓库抽术语表：中文词 -> [{ident, file, line}]（按 ident 去重）。"""
    glossary: dict = {}
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith(TEXT_EXTS):
                continue
            scanned += 1
            if scanned > max_files:
                break
            fp = os.path.join(dirpath, fn)
            try:
                src = open(fp, "r", encoding="utf-8", errors="ignore").read(400_000)
            except OSError:
                continue
            if not re.search(_CN, src):  # 无中文的文件跳过
                continue
            rel = os.path.relpath(fp, root)
            for cn, ident, line in extract_from_source(src):
                entries = glossary.setdefault(cn, [])
                if not any(e["ident"] == ident for e in entries):
                    entries.append({"ident": ident, "file": rel, "line": line})
    return glossary


def _cache_path(repo_name: str) -> str:
    d = os.path.join(repos_root(), "..", "glossary")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{repo_name}.json")


def load_or_build(repo_name: str, root: str, rebuild: bool = False) -> dict:
    path = _cache_path(repo_name)
    if not rebuild and os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    glossary = build_glossary(root)
    try:
        json.dump(glossary, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    except OSError:
        pass
    return glossary


def lookup(glossary: dict, query: str, max_terms: int = 8) -> list:
    """按中文词模糊匹配（子串双向），返回候选标识符 + 出处。"""
    q = query.strip()
    hits = []
    for cn, entries in glossary.items():
        if cn == q or cn in q or q in cn:
            for e in entries[:3]:
                hits.append({"cn": cn, **e})
    # 精确匹配优先，短词优先
    hits.sort(key=lambda h: (h["cn"] != q, len(h["cn"])))
    return hits[:max_terms]
