"""字段追溯 v2 的代码检索工具层：grep / read_file / list_dir。

跑在服务器本地 clone（~/.adalflow/repos/<owner>_<repo>）上，同一套实现供两处使用：
  1. /api/field_trace 的 agent tool-loop（trace_agent.py）
  2. /mcp 端点（mcp_server.py），让开发者的 Cursor/Claude Code 直接复用

设计约束：
  - 所有结果都有硬上限（命中数/行数/字节数），防止把 LLM 上下文撑爆；
  - 路径一律 realpath 校验在 clone 根内，防 ../ 逃逸；
  - 纯只读、纯 stdlib（adalflow 仅用于取根路径，失败时退回 ~/.adalflow）。
"""

import fnmatch
import os
import re

# 与 v1 _grep_clone 相同的噪声目录；grep/list_dir/walk 共用
SKIP_DIRS = {"node_modules", ".git", "dist", "target", "build", ".next", ".nuxt", "__pycache__"}
# 可检索的文本文件后缀（代码 + 配置 + 文档）
TEXT_EXTS = (
    ".java", ".xml", ".vue", ".js", ".ts", ".jsx", ".tsx", ".sql", ".py",
    ".properties", ".yml", ".yaml", ".json", ".md", ".sh", ".html", ".css",
    ".scss", ".less", ".gradle", ".kt", ".go", ".txt",
)
MAX_FILE_BYTES = 400_000


def repos_root() -> str:
    """所有 clone 的根目录。"""
    try:
        from adalflow.utils import get_adalflow_default_root_path
        return os.path.join(get_adalflow_default_root_path(), "repos")
    except Exception:
        return os.path.join(os.path.expanduser("~"), ".adalflow", "repos")


def resolve_repo_root(repo_url: str, repo_type: str) -> str:
    """repo_url → 本地 clone 目录；不存在返回 ''。"""
    try:
        from api.data_pipeline import DatabaseManager
        name = DatabaseManager()._extract_repo_name_from_url(repo_url, repo_type)
    except Exception:
        return ""
    root = os.path.join(repos_root(), name)
    return root if os.path.isdir(root) else ""


def list_repos() -> list:
    """已有本地 clone 的仓库名列表（MCP 的入口工具）。"""
    root = repos_root()
    try:
        return sorted(d for d in os.listdir(root)
                      if os.path.isdir(os.path.join(root, d)) and not d.startswith("."))
    except FileNotFoundError:
        return []


def _safe_join(root: str, rel: str) -> str:
    """clone 根内的安全绝对路径；越界抛 ValueError。"""
    p = os.path.realpath(os.path.join(root, (rel or ".").lstrip("/")))
    real_root = os.path.realpath(root)
    if p != real_root and not p.startswith(real_root + os.sep):
        raise ValueError(f"路径越界：{rel}")
    return p


def _iter_files(root: str, path_glob: str = ""):
    """遍历 clone 内文本文件，跳过噪声目录。yield (abspath, relpath)。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if not fn.lower().endswith(TEXT_EXTS):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), root)
            if path_glob and not fnmatch.fnmatch(rel, path_glob) and not fnmatch.fnmatch(fn, path_glob):
                continue
            yield os.path.join(dirpath, fn), rel


def grep(root: str, pattern: str, path_glob: str = "", regex: bool = False,
         max_hits: int = 50, max_files: int = 4000) -> str:
    """全仓检索。默认大小写不敏感子串匹配；regex=True 时按正则。
    返回 `path:行号: 内容` 列表，命中/扫描量到上限即截断并注明。"""
    pattern = (pattern or "").strip()
    if len(pattern) < 2:
        return "（错误：pattern 至少 2 个字符）"
    if regex:
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return f"（错误：正则无效 {e}）"
        match = rx.search
    else:
        low = pattern.lower()
        match = lambda ln: low in ln.lower()  # noqa: E731
    hits, scanned = [], 0
    for fp, rel in _iter_files(root, path_glob):
        scanned += 1
        if scanned > max_files or len(hits) >= max_hits:
            break
        try:
            src = open(fp, "r", encoding="utf-8", errors="ignore").read(MAX_FILE_BYTES)
        except Exception:
            continue
        if not regex and low not in src.lower():
            continue
        for i, ln in enumerate(src.splitlines()):
            if match(ln):
                hits.append(f"{rel}:{i + 1}: {ln.strip()[:200]}")
                if len(hits) >= max_hits:
                    break
    if not hits:
        return f"（无命中：{pattern}" + (f"，范围 {path_glob}" if path_glob else "") + "）"
    out = "\n".join(hits)
    if len(hits) >= max_hits:
        out += f"\n（已截断：仅显示前 {max_hits} 条，可用 path_glob 缩小范围）"
    return out


def read_file(root: str, path: str, start_line: int = 1, end_line: int = 0,
              max_lines: int = 200) -> str:
    """读文件片段，带真实行号。默认从 start_line 起最多 max_lines 行。"""
    try:
        fp = _safe_join(root, path)
    except ValueError as e:
        return f"（错误：{e}）"
    if not os.path.isfile(fp):
        # 常见自我纠错场景：LLM 猜错路径 → 给出同名文件提示
        base = os.path.basename(path)
        cands = [rel for _, rel in _iter_files(root) if os.path.basename(rel) == base][:5]
        hint = ("；同名文件：" + "、".join(cands)) if cands else ""
        return f"（错误：文件不存在 {path}{hint}）"
    try:
        lines = open(fp, "r", encoding="utf-8", errors="ignore").read(MAX_FILE_BYTES).splitlines()
    except Exception as e:
        return f"（错误：读取失败 {e}）"
    start = max(1, int(start_line or 1))
    end = int(end_line or 0) or (start + max_lines - 1)
    end = min(end, start + max_lines - 1, len(lines))
    if start > len(lines):
        return f"（错误：起始行 {start} 超出文件总行数 {len(lines)}）"
    body = "\n".join(f"{i}: {lines[i - 1][:300]}" for i in range(start, end + 1))
    tail = f"\n（文件共 {len(lines)} 行，本次返回 {start}-{end} 行）"
    return body + tail


def list_dir(root: str, path: str = ".", max_entries: int = 200) -> str:
    """列目录：目录带 / 后缀，文件带大小。"""
    try:
        dp = _safe_join(root, path)
    except ValueError as e:
        return f"（错误：{e}）"
    if not os.path.isdir(dp):
        return f"（错误：目录不存在 {path}）"
    try:
        entries = sorted(os.listdir(dp))
    except Exception as e:
        return f"（错误：{e}）"
    out = []
    for name in entries:
        if name in SKIP_DIRS or name.startswith("."):
            continue
        if len(out) >= max_entries:
            out.append(f"（已截断：仅显示前 {max_entries} 项）")
            break
        full = os.path.join(dp, name)
        if os.path.isdir(full):
            out.append(name + "/")
        else:
            try:
                out.append(f"{name}  ({os.path.getsize(full)}B)")
            except OSError:
                out.append(name)
    return "\n".join(out) or "（空目录）"


# --- OpenAI function-calling schema（agent loop 用；MCP 在此之上加 repo 参数）---
TOOLS_SPEC = [
    {"type": "function", "function": {
        "name": "grep",
        "description": "在仓库全部代码中搜索字符串或正则，返回 文件:行号: 内容。用于定位字段、方法、SQL、接口路径的出现位置。",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "要搜索的字符串（默认大小写不敏感子串）或正则"},
            "path_glob": {"type": "string", "description": "可选，限定文件范围的 glob，如 *.java、src/**/*.vue"},
            "regex": {"type": "boolean", "description": "true 时按正则匹配，默认 false"},
        }, "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "读取仓库内某文件的片段（带真实行号，单次最多 200 行）。用于查看 grep 命中处的完整上下文、方法实现、调用链。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "仓库内相对路径，如 src/main/java/com/x/FeeService.java"},
            "start_line": {"type": "integer", "description": "起始行号，默认 1"},
            "end_line": {"type": "integer", "description": "结束行号，默认 start_line+199"},
        }, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "列出仓库内某目录的内容（子目录带 / 后缀）。用于了解工程结构、猜测模块位置。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "仓库内相对路径，默认仓库根目录"},
        }, "required": []}}},
]


def dispatch(root: str, name: str, args: dict) -> str:
    """按工具名执行（agent loop 与 MCP 共用的分发器）。任何异常转为可读错误文本，让 LLM 自我纠错。"""
    try:
        if name == "grep":
            return grep(root, args.get("pattern", ""), args.get("path_glob", "") or "",
                        bool(args.get("regex")))
        if name == "read_file":
            return read_file(root, args.get("path", ""), int(args.get("start_line") or 1),
                             int(args.get("end_line") or 0))
        if name == "list_dir":
            return list_dir(root, args.get("path") or ".")
        return f"（错误：未知工具 {name}）"
    except Exception as e:  # noqa: BLE001
        return f"（错误：{e}）"
