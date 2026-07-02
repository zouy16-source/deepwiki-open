"""Real wiki-generation pipeline for the background job runner.

Ports the frontend orchestration (web/app/composables/useWikiData.ts +
web/app/utils/wikiPrompts.ts) to Python. Wired into JobManager as the `runner`
(replaces make_fake_runner). The state machine / endpoints in wiki_jobs.py and
api.py are untouched.

Strategy (see docs/wiki-jobs-api.md §9):
  fetching_repo — get file tree + README (gitlab/local endpoints; else derived
                  from the clone after indexing)
  indexing      — RAG.prepare_retriever IN-PROCESS (clone + embed + cache)
  planning      — structure prompt via loopback POST /chat/completions/stream
  generating    — one page prompt per page via the same chat endpoint
  saving        — loopback POST /api/wiki_cache

Only prepare_retriever runs in-process; planning/pages/save reuse the backend's
own HTTP endpoints (the exact pipeline the frontend used), so no refactor of the
700-line chat handler is needed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx

from api.wiki_jobs import GenerateRequest, JobContext, Job, JobFailed

logger = logging.getLogger(__name__)

SELF_BASE_URL = os.environ.get("SELF_BASE_URL") or f"http://127.0.0.1:{os.environ.get('PORT', '8001')}"

# How many pages to generate concurrently within a single job. Multiplies with the
# job-level concurrency (MAX_CONCURRENT_JOBS) against the LLM rate limit — keep modest.
PAGE_CONCURRENCY = int(os.environ.get("WIKI_PAGE_CONCURRENCY", "3"))

# How many modules to expand concurrently during two-phase planning.
PLAN_CONCURRENCY = int(os.environ.get("WIKI_PLAN_CONCURRENCY", "4"))

# Wikis are Chinese-only (China-region audience). The `language` field on requests
# remains as cache-identity plumbing (filenames end in `_zh`), but all generated
# content and prompt headings are hardcoded Chinese — no i18n switching.

# --- source-file URL resolver (ported from useWikiData.generateFileUrl) -------

def generate_file_url(repo_url: str, repo_type: str, default_branch: str, file_path: str) -> str:
    if repo_type == "local":
        return file_path
    if not repo_url:
        return file_path
    url = re.sub(r"^http://", "https://", repo_url, flags=re.I)
    kind = repo_type
    if kind not in ("github", "gitlab", "bitbucket"):
        try:
            host = (urlparse(url).hostname or "").lower()
            kind = "gitlab" if "gitlab" in host else "bitbucket" if "bitbucket" in host else "github"
        except Exception:
            kind = "github"
    clean = file_path.lstrip("/")
    if kind == "gitlab":
        return f"{url}/-/blob/{default_branch}/{clean}"
    if kind == "bitbucket":
        return f"{url}/src/{default_branch}/{clean}"
    return f"{url}/blob/{default_branch}/{clean}"


# --- prompts (ported verbatim from wikiPrompts.ts) ---------------------------

# Fixed Chinese labels for the "相关源文件" <details> block.
_DETAILS_SUMMARY = "相关源文件"
_DETAILS_INTRO = "以下文件用于生成本页面时作为上下文参考："


# --- page archetypes -----------------------------------------------------------
# A single rigid template applied to every page is what made wikis read the same
# ("功能架构 / 核心API / 数据模型 / 总结" on every module). Instead each page carries
# a TYPE (assigned during planning) that selects a DIFFERENT body structure. Shared
# concerns (auth, communication, config) live on ONE cross-cutting page others link
# to, rather than being re-explained on every module page.

PAGE_TYPES = ("overview", "architecture", "feature", "reference", "cross-cutting", "guide", "glossary")


def normalize_page_type(value: str) -> str:
    t = (value or "").strip().lower().replace("_", "-").replace(" ", "-")
    if t in ("crosscutting", "cross", "shared", "cross-cutting-concern"):
        t = "cross-cutting"
    if t in ("terms", "term", "terminology", "glossaries", "术语", "术语表"):
        t = "glossary"
    return t if t in PAGE_TYPES else "feature"


# Per-type body instructions (the middle of the page). All headings are FIXED
# Chinese — the model must copy them verbatim, never translate or anglicize.
_PAGE_BODY = {
    "feature": """This is a FEATURE / SCREEN / business-module page. Structure the WHOLE page as a traceable chain and use THESE THREE H2 sections in EXACTLY this order, with EXACTLY these Chinese headings copied VERBATIM (never English names like "Business Flow"). Do NOT merge, reorder, or replace them with a generic outline:

## 业务流程
- Describe what the feature does as a NUMBERED business/user flow — 步骤1、步骤2、… — including decision branches, the roles/actors involved, preconditions, and key business rules.
- MANDATORY: include at least one Mermaid flowchart (`graph TD`) that visualizes this flow with its steps and branches. If the flow crosses front-end / back-end / third-party systems, ALSO add a `sequenceDiagram`. A 业务流程 section with NO diagram is unacceptable.

## 代码职责
- Map EACH numbered business step above to the code that implements it, as a Markdown table with columns: 业务步骤 | 文件/组件/函数 | 职责与关键逻辑 | Sources.
- Show how the parts collaborate (e.g. page/component → API wrapper → backend endpoint); add a Mermaid `sequenceDiagram` or a call-chain `graph TD` when it clarifies the call path.
- Call out WHERE to change / extend behaviour (the key extension points).

## 测试流程
- Describe how to verify the feature as test scenarios that trace back to the business steps/rules above, as a Markdown table with columns: 场景 | 前置条件 | 步骤 | 预期结果.
- Cover the happy path AND edge / exception cases (empty data, no permission, role differences, concurrency, failure handling).
- Add a test flowchart (`graph TD`) when the flow has non-trivial conditional branches.

Keep the three sections traceable: the SAME numbered steps should be referenceable across 业务流程 → 代码职责 → 测试流程, so a reader can follow one step end to end.""",

    "reference": """This is a REFERENCE page (API / data model / configuration). Prefer STRUCTURED TABLES over prose — keep narrative to a minimum:
- API: one row per endpoint/method with request params, response fields, and error codes.
- Data model: entities, fields, types, constraints and relationships (add an `erDiagram` when it clarifies relationships).
- Configuration: one row per option with its default, effect and scope.
Document only what is specific here; do NOT re-explain cross-cutting mechanisms.""",

    "overview": """This is an OVERVIEW / entry page for ALL audiences (product, engineering, QA):
- What the project/module does, its core value, and who its users are (2-3 short paragraphs).
- A feature map: use a Mermaid `graph TD` to show the main modules and how they relate.
- "Where to go next": link to the detailed module/reference pages with `[Link Text](#page-anchor-or-id)`.
Keep it high-level and leave the details to the linked pages.""",

    "architecture": """This is an ARCHITECTURE page:
- The layers and main components, shown with a Mermaid architecture diagram (`graph TD`).
- Key data flows / call chains, shown with a Mermaid `sequenceDiagram` or flowchart.
- Technology choices and notable design decisions, each grounded in the source files.""",

    "cross-cutting": """This is the SINGLE AUTHORITATIVE page for a cross-cutting concern (e.g. authentication & permissions, front-end/back-end communication, environment/configuration). Every other page LINKS here instead of repeating it, so be COMPLETE:
- Explain the whole mechanism in one place, end to end.
- Show the overall flow with a Mermaid diagram.
- Explain how other modules integrate with / reuse it (what a feature page should link to rather than restate).""",

    "guide": """This is a HOW-TO / guide page (setup, deployment, common operational tasks). Make it ACTIONABLE:
- Prerequisites.
- Numbered, step-by-step instructions with concrete commands / config examples.
- Common problems and troubleshooting.""",

    "glossary": """This is the project GLOSSARY / business-terminology page. Be COMPREHENSIVE — readers expect FULL coverage, not a handful of terms; do NOT summarize or stop early.
- Enumerate EVERY distinct domain / business term, entity, status, role and acronym used across the project. Draw them from the documented module list AND the UI / i18n labels given in the ADDITIONAL CONTEXT below, plus entities, fields, enums and statuses in the source files.
- GROUP terms by domain (e.g. 账户、面单、单号与回收、销售、系统与权限 …) with a Chinese H2 or H3 per group; within each group use a Markdown table with columns: 术语 | 英文/缩写 | 定义 | 所属模块.
- Link the "where it is used" cell to the relevant wiki page with `[Link Text](#page-anchor-or-id)` when possible.
- Include acronyms and bilingual mappings (e.g. SSO, VIP, GIS; 面单 / waybill). Aim for breadth — a real business system has dozens of terms; if the context lists many labels, cover them.""",
}

# Appended to every page EXCEPT the cross-cutting page itself, to stop each module
# from re-describing shared mechanisms.
_DEDUP_RULE = """
AVOID DUPLICATION: shared mechanisms — authentication & permissions, front-end/back-end communication, environment/configuration, shared API conventions — are documented ONCE on their own dedicated cross-cutting pages. If this page touches any of them, LINK to that page with `[Link Text](#page-anchor-or-id)` instead of re-explaining it; describe only what is SPECIFIC to this page.
"""


def build_page_prompt(page_title: str, file_paths_list: str,
                      page_type: str = "feature", extra_context: str = "", instruction: str = "") -> str:
    ptype = normalize_page_type(page_type)
    body = _PAGE_BODY[ptype]
    dedup = "" if ptype == "cross-cutting" else _DEDUP_RULE
    extra = f"""
ADDITIONAL CONTEXT (authoritative — use it to be accurate and COMPLETE; still cite concrete source files where relevant):
{extra_context}
""" if extra_context else ""
    guidance = f"""
REVISION GUIDANCE (HIGH PRIORITY) — this page is being regenerated to FIX a problem the reader reported. You MUST address this specifically; it is the whole point of this regeneration:
{instruction}
""" if instruction else ""
    return f"""You are an expert technical writer and software architect.
Your task is to generate a comprehensive and accurate technical wiki page in Markdown format about a specific feature, system, or module within a given software project.

You will be given:
1. The "[WIKI_PAGE_TOPIC]" for the page you need to create.
2. A list of "[RELEVANT_SOURCE_FILES]" from the project that you MUST use as the sole basis for the content. You have access to the full content of these files. You MUST use AT LEAST 5 relevant source files for comprehensive coverage - if fewer are provided, search for additional related files in the codebase.

CRITICAL STARTING INSTRUCTION:
Do NOT write any acknowledgements, disclaimers, apologies, or any preface. The VERY FIRST thing on the page MUST be a `<details>` block listing ALL the `[RELEVANT_SOURCE_FILES]` you used (AT LEAST 5; if fewer were provided, find additional related files). Output the block EXACTLY like this and put NOTHING inside it except the summary line, the intro line, and the file list (do NOT copy any of these instructions into the block):
<details>
<summary>{_DETAILS_SUMMARY}</summary>

{_DETAILS_INTRO}

{file_paths_list}
</details>

Immediately after the `<details>` block, the main title of the page should be a H1 Markdown heading: `# {page_title}`.

Then a concise 1-2 sentence introduction of "{page_title}" (its purpose and scope within the project), and after it the body below.
{guidance}
PAGE BODY — this page's type is "{ptype}". Follow the structure for THIS type. Do NOT fall back to a generic "architecture / core API / data model / summary" outline; use only the sections called for here, and ground every section ONLY in the `[RELEVANT_SOURCE_FILES]`:

{body}
{dedup}{extra}
FORMATTING RULES (apply to all of the above):

- **Mermaid Diagrams:** Use Mermaid diagrams where they clarify a flow, relationship, or schema (`flowchart TD`, `sequenceDiagram`, `classDiagram`, `erDiagram`, `graph TD`), derived directly from the source files, with a one-line explanation near each. All diagrams MUST follow strict vertical orientation:
   - Use "graph TD" (top-down) for flow diagrams; NEVER "graph LR" (left-right).
   - Maximum node width should be 3-4 words.
   - ALWAYS wrap node/edge labels in double quotes when they contain special characters such as @, /, (), :, or punctuation, e.g. E["@nuxtjs/axios"], N["serial/account"] — unquoted special characters break the Mermaid parser. Do NOT backslash-escape characters inside labels (write `A["call()"]`, never `A[call\\(\\)]`).
   - For sequence diagrams: start with "sequenceDiagram" on its own line; declare ALL participants first with "participant"; use correct arrows (->>, -->>, ->x, -)) with colon labels (A->>B: My Label); use loop/alt/opt/par and notes where helpful.
- **Tables:** Use Markdown tables to summarize APIs, parameters, configuration options, and data-model fields.
- **Code Snippets (OPTIONAL):** Short, relevant snippets straight from the source files, with a language identifier.
- **Source Citations (EXTREMELY IMPORTANT):**
    *   For EVERY piece of significant information, cite the specific source file(s) and line numbers.
    *   The source code in your context is shown with LEADING LINE NUMBERS (e.g. `  8: export const getAccountPage = ...`). You MUST use those ACTUAL line numbers in your citations — read the number at the start of the relevant lines. Do NOT guess, estimate, or invent line numbers.
    *   Use this exact format as PLAIN markdown text — range: Sources: [filename.ext:start_line-end_line](), single line: Sources: [filename.ext:line_number](), multiple: Sources: [file1.ext:1-10](), [file2.ext:5](). Keep the parentheses empty.
    *   Do NOT wrap the citation in backticks or a code span — write it as normal markdown so the links render as links.
    *   Cite AT LEAST 5 different source files throughout the page.
- **Technical Accuracy:** Derive everything SOLELY from the source files — do not infer or invent.
- **Clarity:** Clear, professional, concise technical language.

IMPORTANT: 全部内容必须使用中文撰写（包括所有章节标题、表格列名、图表说明）。不要出现英文标题（如 "Business Flow"、"Overview"）；代码标识符、文件路径、API 名称保持原样即可。

Remember:
- Ground every claim in the provided source files.
- Prioritize accuracy and direct representation of the code's functionality and structure.
- Use the type-specific structure above — do not homogenize every page into the same outline.
"""


_XML_COMPREHENSIVE = """<wiki_structure>
  <title>[Overall title for the wiki]</title>
  <description>[Brief description of the repository]</description>
  <sections>
    <section id="section-1">
      <title>[Section title]</title>
      <pages>
        <page_ref>page-1</page_ref>
        <page_ref>page-2</page_ref>
      </pages>
      <subsections>
        <section_ref>section-2</section_ref>
      </subsections>
    </section>
  </sections>
  <pages>
    <page id="page-1">
      <title>[Page title]</title>
      <description>[Brief description of what this page will cover]</description>
      <importance>high|medium|low</importance>
      <type>overview|architecture|feature|reference|cross-cutting|guide</type>
      <relevant_files>
        <file_path>[Path to a relevant file]</file_path>
      </relevant_files>
      <related_pages>
        <related>page-2</related>
      </related_pages>
      <parent_section>section-1</parent_section>
    </page>
  </pages>
</wiki_structure>"""

_XML_CONCISE = """<wiki_structure>
  <title>[Overall title for the wiki]</title>
  <description>[Brief description of the repository]</description>
  <pages>
    <page id="page-1">
      <title>[Page title]</title>
      <description>[Brief description of what this page will cover]</description>
      <importance>high|medium|low</importance>
      <type>overview|architecture|feature|reference|cross-cutting|guide</type>
      <relevant_files>
        <file_path>[Path to a relevant file]</file_path>
      </relevant_files>
      <related_pages>
        <related>page-2</related>
      </related_pages>
    </page>
  </pages>
</wiki_structure>"""

# Shared page-type vocabulary injected into planning prompts so each page is tagged
# with an archetype; build_page_prompt then picks a distinct structure per type.
_TYPE_VOCAB = """Classify EACH page with a <type> from: overview | architecture | feature | reference | cross-cutting | guide.
- feature: a screen / business feature (MOST module pages) — written as 业务流程 → 代码职责 → 测试流程, with a mandatory flowchart.
- reference: an API, data-model, or configuration reference (mostly tables).
- cross-cutting: a shared mechanism documented ONCE and linked from elsewhere (authentication & permissions, front-end/back-end communication, environment/config).
- overview / architecture / guide: foundational topics (project overview, system architecture, setup/deployment).
Create AT MOST ONE cross-cutting page per shared mechanism — do NOT repeat auth/communication/config on every module page."""


def build_structure_prompt(
    owner: str, repo: str, file_tree: str, readme: str, comprehensive: bool,
    max_pages: int = 40, functional_surface: str = "",
) -> str:
    if comprehensive:
        xml_format = _XML_COMPREHENSIVE
        coverage = f"""Create a COMPREHENSIVE, EXHAUSTIVE wiki that documents EVERY functional module of the system — not just the high-level or "core" themes.

Coverage requirements:
- Begin with a few foundational pages: Overview, System Architecture, and Setup/Configuration.
- Then create ONE page for EACH distinct FUNCTIONAL MODULE / business feature / screen. Be exhaustive: enumerate every module and do NOT stop at the core ones, and do NOT collapse several distinct modules into a single page. For a management/admin system this means every menu entry, route and management screen — e.g. each list view, each detail/edit page, approval/workflow, dictionaries, permissions & roles, reports, dashboards, settings, etc.
- Treat the repository's ROUTES / PAGES / MENU as the authoritative map of functional modules (the file tree, and the functional-surface listing below). Make sure each meaningful route/screen is represented by a page.
- Group related pages into sections by business domain.
- Also add cross-cutting pages where relevant: Data Model/Flow, API Integration, Authentication & Permissions, Deployment.

Aim to cover the system FULLY. A real admin system typically needs 20-50 pages; produce as many as the modules genuinely warrant, up to {max_pages}. Do NOT artificially cap the count or merge distinct modules just to stay small. (Small repositories may need fewer — match the actual number of modules.)"""
        page_rule = f"Create as many pages as needed to cover EVERY functional module (up to {max_pages}); do NOT stop at high-level themes or merge distinct modules"
    else:
        xml_format = _XML_CONCISE
        coverage = "Create a concise wiki covering the most important aspects of the repository."
        page_rule = "Create 4-6 pages that would make a concise wiki for this repository"

    surface_block = ""
    if functional_surface:
        surface_block = f"""

3. The repository's functional surface — route / page / menu / view files. Treat EACH of these as a candidate functional module and ensure it is represented in the wiki structure:
<functional_surface>
{functional_surface}
</functional_surface>"""

    return f"""Analyze this repository {owner}/{repo} and create a wiki structure for it.

1. The complete file tree of the project:
<file_tree>
{file_tree}
</file_tree>

2. The README file of the project:
<readme>
{readme}
</readme>{surface_block}

{coverage}

{SKIP_FOUNDATIONAL_NOTE}

IMPORTANT: 所有页面标题（title）和描述（description）必须使用中文。

When designing the wiki structure, include pages that would benefit from visual diagrams (architecture overviews, data flow, component relationships, process workflows, state machines, class hierarchies).

{_TYPE_VOCAB}

Return your analysis in the following XML format:

{xml_format}

IMPORTANT FORMATTING INSTRUCTIONS:
- Return ONLY the valid XML structure specified above
- DO NOT wrap the XML in markdown code blocks (no ``` or ```xml)
- DO NOT include any explanation text before or after the XML
- Ensure the XML is properly formatted and valid
- Start directly with <wiki_structure> and end with </wiki_structure>

IMPORTANT:
1. {page_rule}
2. Each page should focus on a specific functional module or aspect — a concrete screen/route/feature, or a foundational topic (architecture, setup, data model)
3. The relevant_files must be actual files from the repository that would be used to generate that page
4. Return ONLY valid XML with the structure specified above, with no markdown code block delimiters"""


# --- functional surface extraction (route/page/menu files → module candidates) ---

_SURFACE_RE = re.compile(
    r"(^|/)(pages|views|screens|modules|features|router|routes|menus?|nav|navigation)(/|[._-]|$)"
    r"|(^|/)[^/]*(router|routes|menu|permission|nav)[^/]*\.(js|ts|jsx|tsx|vue|json)$",
    re.I,
)


_SURFACE_EXTS = (".js", ".ts", ".jsx", ".tsx", ".vue", ".json")
_CONFIG_RE = re.compile(r"(router|routes|menu|nav|permission)", re.I)


def extract_functional_surface(file_tree: str, limit: int = 400) -> str:
    """Filter the file tree down to route/page/menu/view source files — the concrete
    functional modules of an app — to steer the structure toward full coverage.
    Config files (router/menu/nav) come first: they're the authoritative module map."""
    configs, pages = [], []
    for line in file_tree.splitlines():
        p = line.strip()
        if not p or not _SURFACE_RE.search(p) or not p.lower().endswith(_SURFACE_EXTS):
            continue
        (configs if _CONFIG_RE.search(p) else pages).append(p)
    return "\n".join((configs + pages)[:limit])


# --- XML structure parse (ported from useWikiData.determineWikiStructure) -----

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")


def _text(el: Optional[ET.Element]) -> str:
    return (el.text or "").strip() if el is not None else ""


def parse_structure(response_text: str, comprehensive: bool) -> dict:
    text = re.sub(r"^```(?:xml)?\s*", "", response_text.strip(), flags=re.I)
    text = re.sub(r"```\s*$", "", text).strip()
    m = re.search(r"<wiki_structure>[\s\S]*?</wiki_structure>", text)
    if not m:
        raise JobFailed("planning_failed", "No valid <wiki_structure> XML found in response")
    xml_text = _CONTROL_CHARS.sub("", m.group(0))

    root = _parse_xml_lenient(xml_text)
    if root is None:
        raise JobFailed("planning_failed", "Could not parse wiki_structure XML")

    title = _text(root.find("title"))
    description = _text(root.find("description"))

    pages = []
    for i, page_el in enumerate(root.iter("page")):
        pid = page_el.get("id") or f"page-{i + 1}"
        p_title = _text(page_el.find("title"))
        imp = _text(page_el.find("importance"))
        importance = imp if imp in ("high", "low") else "medium"
        file_paths = [t for t in (_text(e) for e in page_el.iter("file_path")) if t]
        related = [t for t in (_text(e) for e in page_el.iter("related")) if t]
        pages.append({
            "id": pid, "title": p_title, "content": "",
            "filePaths": file_paths, "importance": importance, "relatedPages": related,
            "type": normalize_page_type(_text(page_el.find("type"))),
        })

    sections = []
    root_sections = []
    if comprehensive:
        section_els = list(root.iter("section"))
        referenced = set()
        for sec in section_els:
            for ref in sec.iter("section_ref"):
                if ref.text:
                    referenced.add(ref.text.strip())
        for i, sec in enumerate(section_els):
            sid = sec.get("id") or f"section-{i + 1}"
            s_title = _text(sec.find("title"))
            sec_pages = [t for t in (_text(e) for e in sec.iter("page_ref")) if t]
            subsections = [t for t in (_text(e) for e in sec.iter("section_ref")) if t]
            sections.append({
                "id": sid, "title": s_title, "pages": sec_pages,
                "subsections": subsections or None,
            })
            if sid not in referenced:
                root_sections.append(sid)

    return {
        "id": "wiki", "title": title, "description": description,
        "pages": pages, "sections": sections, "rootSections": root_sections,
    }


def _parse_xml_lenient(xml_text: str) -> Optional[ET.Element]:
    """ElementTree is strict; LLM XML sometimes has bare ampersands. Try as-is,
    then escape lone '&', then give up."""
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError:
        pass
    fixed = re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", xml_text)
    try:
        return ET.fromstring(fixed)
    except ET.ParseError as e:
        logger.warning("wiki_structure XML parse failed after sanitize: %s", e)
        return None


# --- repo structure fetch (fetching_repo phase) ------------------------------

async def fetch_structure(client: httpx.AsyncClient, base: str, req: GenerateRequest) -> Tuple[str, str, str]:
    """Returns (file_tree, readme, default_branch). Empty file_tree => derive from
    the clone after indexing."""
    try:
        if req.repo_type == "gitlab":
            params = {"repo_url": req.repo_url or f"{req.owner}/{req.repo}"}
            if req.token:
                params["token"] = req.token
            r = await client.get(f"{base}/api/gitlab/file_tree", params=params, timeout=60.0)
            r.raise_for_status()
            data = r.json()
            if data.get("error"):
                logger.warning("gitlab file_tree error: %s", data["error"])
                return "", "", "main"
            return data.get("file_tree") or "", data.get("readme") or "", data.get("default_branch") or "main"
        if req.repo_type == "local":
            local_path = req.repo_url
            r = await client.get(f"{base}/local_repo/structure", params={"path": local_path}, timeout=60.0)
            r.raise_for_status()
            data = r.json()
            return data.get("file_tree") or "", data.get("readme") or "", "main"
    except Exception as e:  # noqa: BLE001 — non-fatal: fall back to clone-derived tree
        logger.warning("fetch_structure(%s) failed, will derive from clone: %s", req.repo_type, e)
    return "", "", "main"


def derive_tree_from_clone(clone_dir: str) -> Tuple[str, str]:
    """Build a newline-joined file tree + README from a cloned repo dir. Provider
    agnostic — used when no file_tree endpoint applies (github/bitbucket)."""
    paths = []
    readme = ""
    for dirpath, dirnames, filenames in os.walk(clone_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "vendor", "__pycache__")]
        for fn in filenames:
            if fn.startswith("."):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), clone_dir)
            paths.append(rel.replace(os.sep, "/"))
    for name in ("README.md", "readme.md", "README", "README.rst"):
        p = os.path.join(clone_dir, name)
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    readme = f.read()
                break
            except Exception:
                pass
    paths.sort()
    return "\n".join(paths), readme


def git_commit_id(clone_dir: str) -> str:
    """HEAD commit SHA of the clone (empty string if unavailable). Recorded in the
    cache so later runs can diff against the latest commit (incremental updates)."""
    try:
        out = subprocess.run(["git", "-C", clone_dir, "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=15)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


# --- indexing (in-process RAG.prepare_retriever) -----------------------------

def _split_filter(value: str) -> Optional[list]:
    if not value:
        return None
    parts = [p.strip() for p in re.split(r"[\n,]", value) if p.strip()]
    return parts or None


def index_repo(req: GenerateRequest) -> str:
    """Clone + embed the repo (blocking; run in a thread). Returns the clone dir."""
    from api.rag import RAG  # local import: heavy deps, keep module import cheap

    rag = RAG(provider=req.provider or "google", model=req.model or None)
    rag.prepare_retriever(
        req.repo_url,
        req.repo_type,
        req.token or None,
        excluded_dirs=_split_filter(req.excluded_dirs),
        excluded_files=_split_filter(req.excluded_files),
        included_dirs=_split_filter(req.included_dirs),
        included_files=_split_filter(req.included_files),
    )
    try:
        return (rag.db_manager.repo_paths or {}).get("save_repo_dir", "")
    except Exception:
        return ""


# --- chat (planning + pages) via loopback HTTP -------------------------------

async def stream_chat(client: httpx.AsyncClient, base: str, req: GenerateRequest, prompt: str) -> str:
    body = {
        "repo_url": req.repo_url,
        "type": req.repo_type,
        "messages": [{"role": "user", "content": prompt}],
        "token": req.token or None,
        "provider": req.provider or "google",
        "model": req.model or None,
        "language": req.language,
        "excluded_dirs": req.excluded_dirs or None,
        "excluded_files": req.excluded_files or None,
        "included_dirs": req.included_dirs or None,
        "included_files": req.included_files or None,
    }
    r = await client.post(f"{base}/chat/completions/stream", json=body, timeout=httpx.Timeout(600.0, connect=15.0))
    r.raise_for_status()
    return r.text


def _strip_md_fence(content: str) -> str:
    content = re.sub(r"^```markdown\s*", "", content.strip(), flags=re.I)
    content = re.sub(r"```\s*$", "", content)
    return content


# --- mandatory business-flow diagram enforcement (feature pages) --------------
# The "Business Flow" section MUST carry a Mermaid flowchart, but the prompt's
# MANDATORY is only a soft constraint (~14% of feature pages skipped it). After
# generation we detect a feature page whose FIRST section lacks a mermaid block and
# do ONE targeted repair call, accepting the result only if it's actually improved.
_FLOW_REPAIR = os.environ.get("WIKI_FLOW_REPAIR", "1").lower() not in ("0", "false", "no", "off")
_MERMAID_FENCE = re.compile(r"```[ \t]*mermaid", re.I)


def _first_h2_section(content: str) -> Optional[str]:
    """Body of the first H2 section (Business Flow, by template order), up to the
    next H2. None when the page has no H2 headings at all."""
    m = re.search(r"(?m)^##[ \t]+\S.*$", content)
    if not m:
        return None
    start = m.end()
    nxt = re.search(r"(?m)^##[ \t]+\S", content[start:])
    return content[start: start + nxt.start()] if nxt else content[start:]


def _feature_missing_flow_diagram(content: str) -> bool:
    sec = _first_h2_section(content)
    if sec is None:
        return True
    return _MERMAID_FENCE.search(sec) is None


def build_flow_repair_prompt(page_title: str, content: str) -> str:
    return f"""The wiki page below is missing its MANDATORY business-flow diagram. Its FIRST section (the 业务流程 section) MUST contain at least one Mermaid flowchart (graph TD) that visualizes the numbered steps and their branches.

Return the COMPLETE page again in Chinese (中文), IDENTICAL to the input EXCEPT that you insert ONE correct Mermaid flowchart into the 业务流程 section (right after its step list). Do NOT change any other section, wording, or the `Sources:` citations, and do NOT drop content.

Mermaid rules: use `graph TD` (top-down, never LR), max 3-4 words per node, wrap any label containing special characters (@ / ( ) : etc.) in double quotes, and do NOT backslash-escape characters inside labels. Output ONLY the markdown page — no code fence around the whole page, no preface.

<page_to_fix>
{content}
</page_to_fix>"""


async def _maybe_repair_flow(client, base, req, page, content: str) -> str:
    """For a feature page missing its business-flow diagram, try one repair call.
    Returns the repaired page only if it now has the diagram and kept its substance;
    otherwise the original content (never worse)."""
    if not _FLOW_REPAIR or normalize_page_type(page.get("type", "feature")) != "feature":
        return content
    if not _feature_missing_flow_diagram(content):
        return content
    try:
        fixed = _strip_md_fence(await stream_chat(
            client, base, req, build_flow_repair_prompt(page.get("title", ""), content)))
    except Exception as e:  # noqa: BLE001
        logger.warning("flow-repair for '%s' failed: %s", page.get("title"), e)
        return content
    if fixed.strip() and not _feature_missing_flow_diagram(fixed) and len(fixed) >= 0.7 * len(content):
        logger.info("flow-repair added a business-flow diagram to '%s'", page.get("title"))
        return fixed
    logger.info("flow-repair did not improve '%s'; keeping original", page.get("title"))
    return content


async def _gen_page(client, base, req, page, default_branch, retries: int, extra_context: str = "",
                    instruction: str = "") -> Tuple[str, bool]:
    file_paths_list = "\n".join(
        f"- [{p}]({generate_file_url(req.repo_url, req.repo_type, default_branch, p)})" for p in page["filePaths"]
    )
    prompt = build_page_prompt(page["title"], file_paths_list, page.get("type", "feature"),
                               extra_context, instruction)
    last_err = ""
    for attempt in range(retries + 1):
        try:
            content = _strip_md_fence(await stream_chat(client, base, req, prompt))
            if content.strip():
                content = await _maybe_repair_flow(client, base, req, page, content)
                return content, True
            last_err = "empty response"
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            logger.warning("page '%s' attempt %d failed: %s", page["title"], attempt + 1, last_err)
    return f"Error generating content: {last_err}", False


# --- save (saving phase) via loopback HTTP -----------------------------------

async def save_cache(client, base, req: GenerateRequest, structure: dict, generated: dict,
                     commit_id: str = "", default_branch: str = "", generated_at: Optional[int] = None) -> None:
    body = {
        "repo": {
            "owner": req.owner, "repo": req.repo, "type": req.repo_type,
            "token": req.token or None, "localPath": None, "repoUrl": req.repo_url,
        },
        "language": req.language,
        "wiki_structure": {
            "id": structure.get("id", "wiki"), "title": structure.get("title", ""),
            "description": structure.get("description", ""), "pages": structure.get("pages", []),
            "sections": structure.get("sections") or [], "rootSections": structure.get("rootSections") or [],
        },
        "generated_pages": generated,
        "provider": req.provider,
        "model": req.model,
        "commit_id": commit_id or None,
        "default_branch": default_branch or None,
        "generated_at": generated_at,
    }
    r = await client.post(f"{base}/api/wiki_cache", json=body, timeout=120.0)
    r.raise_for_status()


# --- two-phase planning (discover modules -> expand each into pages) ----------

def build_discover_prompt(owner: str, repo: str, file_tree: str, readme: str,
                          max_modules: int, functional_surface: str = "") -> str:
    surface_block = ""
    if functional_surface:
        surface_block = f"""

The repository's functional surface — route / page / menu / view files. Treat EACH as a candidate module:
<functional_surface>
{functional_surface}
</functional_surface>"""
    return f"""Analyze this repository {owner}/{repo} and identify EVERY distinct FUNCTIONAL MODULE / business feature / screen it contains. This is the FIRST of two passes — here you only enumerate the modules; their pages are planned later, so be EXHAUSTIVE and do NOT merge distinct modules.

1. The complete file tree:
<file_tree>
{file_tree}
</file_tree>

2. The README:
<readme>
{readme}
</readme>{surface_block}

List every FUNCTIONAL / BUSINESS module: each menu entry, route and management screen (lists, detail/edit pages, approval/workflow, dictionaries, permissions & roles, reports, dashboards, settings, etc.), plus genuinely cross-cutting concerns that are NOT foundational (e.g. Data Model, API Integration, Authentication & Permissions). Use the routes/pages/menu above as the authoritative map. Produce as many modules as the system genuinely has, up to {max_modules}.

{SKIP_FOUNDATIONAL_NOTE}

所有模块标题（title）和描述（description）必须使用中文。

Return ONLY this XML (no markdown fences, no prose before/after):
<modules>
  <title>[Overall wiki title]</title>
  <description>[Brief description of the repository]</description>
  <module id="module-1">
    <title>[Module name]</title>
    <description>[What this module does, 1 sentence]</description>
    <relevant_files>
      <file_path>[a real file that belongs to this module]</file_path>
    </relevant_files>
  </module>
</modules>

Rules:
- Start directly with <modules> and end with </modules>. No ``` fences, no extra text.
- Give each module a unique id like module-1, module-2, …
- relevant_files must be ACTUAL files from the file tree."""


def build_expand_prompt(owner: str, repo: str, module_title: str, module_description: str,
                        module_files: list, max_pages_per_module: int) -> str:
    files_block = "\n".join(f"- {f}" for f in module_files) if module_files else "(discover the relevant files from the codebase)"
    return f"""For the module "{module_title}" of repository {owner}/{repo}, plan its wiki pages. This is the SECOND pass — decompose THIS module only.

Module description: {module_description}

Candidate files for this module:
{files_block}

Create 1 to {max_pages_per_module} wiki pages that fully document this module. If the module is simple, ONE page is enough; if it has several distinct sub-features, split them into separate pages. Do NOT invent unrelated pages, and do NOT split every module into the same generic "architecture / API / data model" pages — pick pages (and their type) that fit THIS module.

{_TYPE_VOCAB}

所有页面标题（title）和描述（description）必须使用中文。

Return ONLY this XML (no markdown fences, no prose before/after):
<pages>
  <page id="page-1">
    <title>[Page title]</title>
    <description>[Brief description]</description>
    <importance>high|medium|low</importance>
    <type>overview|architecture|feature|reference|cross-cutting|guide</type>
    <relevant_files>
      <file_path>[a real file for this page]</file_path>
    </relevant_files>
    <related_pages>
      <related>[another page id, optional]</related>
    </related_pages>
  </page>
</pages>

Rules:
- Start directly with <pages> and end with </pages>. No ``` fences, no extra text.
- relevant_files must be ACTUAL files from the repository (prefer the candidates above)."""


def parse_modules(response_text: str) -> Tuple[dict, list]:
    text = re.sub(r"^```(?:xml)?\s*", "", response_text.strip(), flags=re.I)
    text = re.sub(r"```\s*$", "", text).strip()
    m = re.search(r"<modules>[\s\S]*?</modules>", text)
    if not m:
        raise JobFailed("planning_failed", "No valid <modules> XML found in discovery response")
    root = _parse_xml_lenient(_CONTROL_CHARS.sub("", m.group(0)))
    if root is None:
        raise JobFailed("planning_failed", "Could not parse <modules> XML")
    meta = {"title": _text(root.find("title")), "description": _text(root.find("description"))}
    modules = []
    for i, el in enumerate(root.iter("module")):
        mid = el.get("id") or f"module-{i + 1}"
        modules.append({
            "id": mid,
            "title": _text(el.find("title")),
            "description": _text(el.find("description")),
            "files": [t for t in (_text(e) for e in el.iter("file_path")) if t],
        })
    return meta, modules


def parse_module_pages(response_text: str, module_id: str) -> list:
    text = re.sub(r"^```(?:xml)?\s*", "", response_text.strip(), flags=re.I)
    text = re.sub(r"```\s*$", "", text).strip()
    m = re.search(r"<pages>[\s\S]*?</pages>", text)
    block = m.group(0) if m else None
    if not block:  # lenient: gather bare <page>...</page> and wrap
        pgs = re.findall(r"<page\b[\s\S]*?</page>", text)
        if not pgs:
            return []
        block = "<pages>" + "".join(pgs) + "</pages>"
    root = _parse_xml_lenient(_CONTROL_CHARS.sub("", block))
    if root is None:
        return []
    pages = []
    for i, page_el in enumerate(root.iter("page")):
        imp = _text(page_el.find("importance"))
        pages.append({
            "id": f"{module_id}-p{i + 1}",  # globally unique
            "title": _text(page_el.find("title")),
            "content": "",
            "filePaths": [t for t in (_text(e) for e in page_el.iter("file_path")) if t],
            "importance": imp if imp in ("high", "low") else "medium",
            "relatedPages": [t for t in (_text(e) for e in page_el.iter("related")) if t],
            "type": normalize_page_type(_text(page_el.find("type"))),
        })
    return pages


def _assemble_two_phase(meta: dict, module_results: list, max_pages: int) -> dict:
    pages, sections, root_sections = [], [], []
    for mod, mod_pages in module_results:
        page_ids = []
        for pg in mod_pages:
            if len(pages) >= max_pages:
                break
            if not pg.get("title"):
                continue
            pages.append(pg)
            page_ids.append(pg["id"])
        if page_ids:
            sections.append({"id": mod["id"], "title": mod["title"], "pages": page_ids, "subsections": None})
            root_sections.append(mod["id"])
        if len(pages) >= max_pages:
            break
    return {
        "id": "wiki", "title": meta.get("title", ""), "description": meta.get("description", ""),
        "pages": pages, "sections": sections, "rootSections": root_sections,
    }


def _use_two_phase(req: GenerateRequest) -> bool:
    if req.plan_mode == "two_phase":
        return True
    if req.plan_mode == "single":
        return False
    return bool(req.comprehensive)  # auto


async def plan_two_phase(client, base, req: GenerateRequest, file_tree: str, readme: str, surface: str) -> dict:
    """Discover all modules (one focused call), then expand each into pages
    concurrently. Falls back to single-phase if discovery yields no modules."""
    dxml = await stream_chat(client, base, req,
                             build_discover_prompt(req.owner, req.repo, file_tree, readme,
                                                   req.max_modules, surface))
    meta, modules = parse_modules(dxml)
    modules = modules[: req.max_modules]
    if not modules:
        logger.warning("two-phase discovery found no modules; falling back to single-phase")
        xml = await stream_chat(client, base, req,
                                build_structure_prompt(req.owner, req.repo, file_tree, readme,
                                                       req.comprehensive, req.max_pages, surface))
        return parse_structure(xml, req.comprehensive)

    sem = asyncio.Semaphore(PLAN_CONCURRENCY)

    async def expand(mod):
        async with sem:
            try:
                xml = await stream_chat(client, base, req,
                                        build_expand_prompt(req.owner, req.repo, mod["title"], mod["description"],
                                                            mod["files"], req.max_pages_per_module))
                mp = parse_module_pages(xml, mod["id"])
                if mp:
                    return mod, mp
            except Exception as e:  # noqa: BLE001
                logger.warning("expand module '%s' failed: %s", mod.get("title"), e)
            # fallback: the module becomes a single page
            return mod, [{
                "id": f"{mod['id']}-p1", "title": mod["title"], "content": "",
                "filePaths": mod["files"][:8], "importance": "medium", "relatedPages": [],
                "type": "feature",
            }]

    results = await asyncio.gather(*(expand(m) for m in modules))
    return _assemble_two_phase(meta, results, req.max_pages)


# --- incremental update (Phase B: diff old commit -> regen affected pages) ----

async def _load_cache(client, base: str, req: GenerateRequest) -> Optional[dict]:
    params = {"owner": req.owner, "repo": req.repo, "repo_type": req.repo_type, "language": req.language}
    r = await client.get(f"{base}/api/wiki_cache", params=params, timeout=60.0)
    if r.status_code != 200:
        return None
    return r.json()  # WikiCacheData dict, or null


async def _compare_files(client, base: str, req: GenerateRequest, from_sha: str, to_ref: str) -> dict:
    params = {"repo_url": req.repo_url, "from_sha": from_sha, "to_ref": to_ref}
    if req.token:
        params["token"] = req.token
    r = await client.get(f"{base}/api/gitlab/compare_files", params=params, timeout=60.0)
    r.raise_for_status()
    return r.json()


def _affected_pages(pages: list, changed_paths) -> list:
    """Pages to regenerate: any whose relevant file — or a sibling in the same
    directory (module proximity, since filePaths only approximates dependencies) —
    changed. filePaths reference the OLD tree, so match against the changed set."""
    changed = set(changed_paths)
    changed_dirs = {os.path.dirname(p) for p in changed if os.path.dirname(p)}
    out = []
    for pg in pages:
        fps = pg.get("filePaths") or []
        if any(fp in changed for fp in fps) or any(os.path.dirname(fp) in changed_dirs for fp in fps if os.path.dirname(fp)):
            out.append(pg)
    return out


def refresh_index(req: GenerateRequest) -> Tuple[str, str]:
    """Force a fresh clone (latest code) + re-embed, so regeneration sees new code.
    Returns (clone_dir, new_commit_id). For URL repos the clone + DB are wiped; for
    local repos only the embedding DB is dropped (never touch the user's files)."""
    from api.data_pipeline import DatabaseManager  # local import: heavy deps
    from adalflow.utils import get_adalflow_default_root_path

    root = get_adalflow_default_root_path()
    if req.repo_url.startswith(("http://", "https://")):
        repo_name = DatabaseManager()._extract_repo_name_from_url(req.repo_url, req.repo_type)
        clone_dir = os.path.join(root, "repos", repo_name)
        db_file = os.path.join(root, "databases", f"{repo_name}.pkl")
        shutil.rmtree(clone_dir, ignore_errors=True)  # remove stale clone -> re-clone latest
    else:
        repo_name = os.path.basename(req.repo_url.rstrip("/"))
        db_file = os.path.join(root, "databases", f"{repo_name}.pkl")  # local: keep files, drop DB
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except OSError:
            pass
    return index_repo(req), ""


# --- incremental Phase C: new modules from added files, prune deleted ----------

def build_new_modules_prompt(owner: str, repo: str, added_files: list, existing_titles: list,
                             max_modules: int) -> str:
    existing = "\n".join(f"- {t}" for t in existing_titles if t) or "(none)"
    files = "\n".join(f"- {f}" for f in added_files)
    return f"""New files were added to repository {owner}/{repo}. Identify any NEW functional modules they introduce that are NOT already documented.

Newly added files:
{files}

The wiki ALREADY documents these modules — do NOT duplicate them:
{existing}

Return ONLY modules that are genuinely NEW (a new screen/route/feature not covered above). If the added files merely extend an existing module, return an EMPTY <modules></modules>.

所有模块标题（title）和描述（description）必须使用中文。

Return ONLY this XML (no fences, no prose):
<modules>
  <title>New modules</title>
  <description>-</description>
  <module id="module-1">
    <title>[New module name]</title>
    <description>[what it does, 1 sentence]</description>
    <relevant_files><file_path>[one of the added files]</file_path></relevant_files>
  </module>
</modules>

Rules: start with <modules>, end with </modules>. Up to {max_modules} modules. If nothing is genuinely new, return exactly <modules></modules>."""


def _unique_id(base: str, taken: set) -> str:
    if base not in taken:
        return base
    i = 2
    while f"{base}-{i}" in taken:
        i += 1
    return f"{base}-{i}"


async def _discover_new(client, base: str, req: GenerateRequest, added: set, structure: dict) -> Tuple[list, list]:
    """From the added files, discover genuinely-new functional modules (not in dirs
    already covered by existing pages) and plan pages for them. Returns
    (new_page_shells, new_sections). Shells have content='' (filled by the caller)."""
    existing_files, existing_dirs = set(), set()
    for pg in structure.get("pages") or []:
        for fp in pg.get("filePaths") or []:
            existing_files.add(fp)
            if os.path.dirname(fp):
                existing_dirs.add(os.path.dirname(fp))
    surface_added = [
        f for f in sorted(added)
        if _SURFACE_RE.search(f) and f.lower().endswith(_SURFACE_EXTS)
        and f not in existing_files and os.path.dirname(f) not in existing_dirs
    ]
    if not surface_added:
        return [], []

    existing_titles = [pg.get("title", "") for pg in structure.get("pages") or []]
    dxml = await stream_chat(client, base, req,
                             build_new_modules_prompt(req.owner, req.repo, surface_added, existing_titles,
                                                      req.max_modules))
    try:
        _, modules = parse_modules(dxml)
    except JobFailed:
        return [], []
    if not modules:
        return [], []

    taken = {pg["id"] for pg in structure.get("pages") or []} | {s["id"] for s in structure.get("sections") or []}
    sem = asyncio.Semaphore(PLAN_CONCURRENCY)

    async def expand(mod, idx):
        async with sem:
            try:
                xml = await stream_chat(client, base, req,
                                        build_expand_prompt(req.owner, req.repo, mod["title"], mod["description"],
                                                            mod["files"] or surface_added,
                                                            req.max_pages_per_module))
                mp = parse_module_pages(xml, f"newmod-{idx}")
            except Exception as e:  # noqa: BLE001
                logger.warning("expand new module '%s' failed: %s", mod.get("title"), e)
                mp = []
            if not mp:
                mp = [{"id": f"newmod-{idx}-p1", "title": mod["title"], "content": "",
                       "filePaths": (mod["files"] or [])[:8], "importance": "medium", "relatedPages": [],
                       "type": "feature"}]
            return mod, mp

    results = await asyncio.gather(*(expand(m, i) for i, m in enumerate(modules)))

    shells, sections = [], []
    for mod, mp in results:
        sec_id = _unique_id(f"newsec-{mod['id']}", taken)
        taken.add(sec_id)
        pids = []
        for pg in mp:
            pg["id"] = _unique_id(pg["id"], taken)
            taken.add(pg["id"])
            pg["content"] = ""
            shells.append(pg)
            pids.append(pg["id"])
        if pids:
            sections.append({"id": sec_id, "title": mod["title"], "pages": pids, "subsections": None})
    logger.info("incremental new-modules: %d added surface files -> %d new pages",
                len(surface_added), len(shells))
    return shells, sections


def _prune_deleted(structure: dict, generated: dict, deleted: set) -> int:
    """Drop pages whose relevant files were ALL deleted (module removed). Returns count."""
    if not deleted:
        return 0
    removed = set()
    kept = []
    for pg in structure.get("pages") or []:
        fps = pg.get("filePaths") or []
        if fps and all(fp in deleted for fp in fps):
            removed.add(pg["id"])
        else:
            kept.append(pg)
    if not removed:
        return 0
    structure["pages"] = kept
    for rid in removed:
        generated.pop(rid, None)
    new_sections = []
    for sec in structure.get("sections") or []:
        sp = [pid for pid in (sec.get("pages") or []) if pid not in removed]
        if sp:
            sec["pages"] = sp
            new_sections.append(sec)
    kept_ids = {s["id"] for s in new_sections}
    structure["sections"] = new_sections
    structure["rootSections"] = [sid for sid in (structure.get("rootSections") or []) if sid in kept_ids]
    logger.info("incremental prune: removed %d pages (deleted modules)", len(removed))
    return len(removed)


async def _run_incremental(job: Job, ctx: JobContext, req: GenerateRequest, client, base: str, page_retries: int) -> None:
    # baseline
    await ctx.set_phase("fetching_repo")
    cached = await _load_cache(client, base, req)
    if not cached or not cached.get("commit_id"):
        raise JobFailed("repo_fetch_failed",
                        "No baseline wiki with a commit id — run a full generation first, then incremental.")
    old_sha = cached["commit_id"]
    branch = cached.get("default_branch") or "main"
    structure = cached.get("wiki_structure") or {}
    generated = dict(cached.get("generated_pages") or {})

    cmp = await _compare_files(client, base, req, old_sha, branch)
    if cmp.get("error"):
        raise JobFailed("repo_fetch_failed", f"compare failed: {cmp['error']}")
    changed = set(cmp.get("changed") or [])
    new_sha = cmp.get("new_sha") or old_sha

    if not changed or new_sha == old_sha:
        # already up to date — just refresh commit_id/timestamp, nothing to regenerate.
        ctx.set_total_pages(0)
        await ctx.set_phase("saving")
        await save_cache(client, base, req, structure, generated,
                         commit_id=new_sha, default_branch=branch, generated_at=int(time.time() * 1000))
        return

    # re-index to the new code (fresh clone + re-embed)
    await ctx.set_phase("indexing")
    try:
        clone_dir, _ = await asyncio.to_thread(refresh_index, req)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "OPENAI_API_KEY" in msg or "GOOGLE_API_KEY" in msg or "embedding" in msg.lower():
            raise JobFailed("embedding_failed", msg)
        raise JobFailed("repo_fetch_failed", msg)
    fresh_sha = await asyncio.to_thread(git_commit_id, clone_dir) if clone_dir else ""
    if fresh_sha:
        new_sha = fresh_sha

    # affected existing pages + newly-added modules (Phase C)
    affected = _affected_pages(structure.get("pages") or [], changed)
    new_shells, new_sections = await _discover_new(client, base, req, set(cmp.get("added") or []), structure)
    to_gen = affected + new_shells
    logger.info("incremental %s/%s: %d changed -> %d affected + %d new pages",
                req.owner, req.repo, len(changed), len(affected), len(new_shells))
    ctx.set_total_pages(len(to_gen))

    if to_gen:
        await ctx.set_phase("generating")
        sem = asyncio.Semaphore(PAGE_CONCURRENCY)

        async def gen(pg):
            async with sem:
                ctx.set_current_page(pg.get("title"))
                content, ok = await _gen_page(client, base, req, pg, branch, page_retries)
                generated[pg["id"]] = {
                    "id": pg["id"], "title": pg.get("title", ""), "content": content,
                    "filePaths": pg.get("filePaths") or [], "importance": pg.get("importance", "medium"),
                    "relatedPages": pg.get("relatedPages") or [], "type": pg.get("type", "feature"),
                }
                ctx.page_done(failed=not ok)

        await asyncio.gather(*(gen(p) for p in to_gen))
        ctx.set_current_page(None)

    # merge new pages/sections into the structure (page meta carries empty content)
    if new_shells:
        structure["pages"] = (structure.get("pages") or []) + [{**p, "content": ""} for p in new_shells]
        structure["sections"] = (structure.get("sections") or []) + new_sections
        structure["rootSections"] = (structure.get("rootSections") or []) + [s["id"] for s in new_sections]

    # prune pages whose module's files were entirely deleted
    _prune_deleted(structure, generated, set(cmp.get("deleted") or []))

    await ctx.set_phase("saving")
    await save_cache(client, base, req, structure, generated,
                     commit_id=new_sha, default_branch=branch, generated_at=int(time.time() * 1000))


# --- foundational scaffold (guaranteed onboarding / architecture / ops pages) ---
# Relying on LLM "module discovery" to also surface foundational pages does NOT work
# in practice (business modules crowd them out — real wikis came back with ZERO
# overview/architecture/deployment pages). So we GUARANTEE a fixed set of foundational
# pages, auto-pick their source files from the file tree, and prepend them to the wiki.

SCAFFOLD_STRUCTURE_ID = "found-structure"  # this page gets the file tree injected
SCAFFOLD_GLOSSARY_ID = "found-glossary"    # this page gets i18n labels + module map injected

# Ordered spec. `patterns` (regex, case-insensitive) are matched against file-tree
# lines in priority order to pick each page's relevant_files. `section` groups pages.
_FOUNDATIONAL = [
    {"id": "found-overview", "type": "overview", "section": "intro",
     "title": "项目概述",
     "patterns": [r"(^|/)README", r"(^|/)package\.json$", r"(^|/)pyproject\.toml$", r"nuxt\.config\.", r"(^|/)composer\.json$"]},
    {"id": "found-getting-started", "type": "guide", "section": "intro",
     "title": "快速上手",
     "patterns": [r"本地开发", r"本地開發", r"CONTRIBUTING", r"(^|/)run\.sh$", r"(^|/)Makefile$", r"(^|/)package\.json$",
                  r"\.env", r"docker-compose", r"(^|/)README"]},
    {"id": SCAFFOLD_STRUCTURE_ID, "type": "reference", "section": "intro",
     "title": "项目结构与目录地图",
     "patterns": [r"(^|/)package\.json$", r"nuxt\.config\.", r"(^|/)api/main\.py$", r"(^|/)api/api\.py$",
                  r"(^|/)main\.(py|ts|js|go)$", r"(^|/)README"]},
    {"id": SCAFFOLD_GLOSSARY_ID, "type": "glossary", "section": "intro",
     "title": "术语表与业务名词",
     "patterns": [r"(^|/)i18n", r"(^|/)locales?(/|$)", r"(dict|dictionary|字典)", r"(enum|const(ant)?s?|types?)\.",
                  r"(router|routes|menu)", r"(^|/)README"]},
    {"id": "found-architecture", "type": "architecture", "section": "ops",
     "title": "系统架构",
     "patterns": [r"nuxt\.config\.", r"(^|/)api/main\.py$", r"(^|/)api/api\.py$", r"(^|/)main\.(py|ts|js|go)$",
                  r"docker-compose", r"(^|/)README"]},
    {"id": "found-configuration", "type": "reference", "section": "ops",
     "title": "配置与环境变量",
     "patterns": [r"\.env", r"(^|/)api/config\.py$", r"nuxt\.config\.", r"litellm-config", r"(^|/)config(/|\.|$)",
                  r"\.ya?ml$", r"(^|/)settings\."]},
    {"id": "found-deployment", "type": "guide", "section": "ops",
     "title": "部署与运维",
     "patterns": [r"(^|/)Dockerfile", r"docker-compose", r"(^|/)run\.sh$", r"\.github/workflows", r"(gitlab-ci|Jenkinsfile)",
                  r"(^|/)api/config\.py$"]},
]

_SCAFFOLD_SECTIONS = {
    "intro": {"id": "found-intro", "title": "概述与入门"},
    "ops": {"id": "found-arch-ops", "title": "架构与部署"},
}

_DEFAULT_FOUNDATIONAL = [s["id"] for s in _FOUNDATIONAL]

# The topics discovery must NOT re-create (they are scaffolded), and near-exact titles
# used to drop any that slip through. Cross-cutting concerns (auth, API, data model) are
# intentionally absent — those stay discoverable and become cross-cutting pages.
SKIP_FOUNDATIONAL_NOTE = (
    "Do NOT create foundational/onboarding pages — project overview, getting started / setup, "
    "system architecture, deployment / operations, project structure, configuration / environment, "
    "or glossary. Those are generated separately. List ONLY the actual functional / business modules."
)

_FOUNDATIONAL_ALIASES = {
    "项目概述", "概述", "项目简介", "简介", "overview", "projectoverview", "introduction",
    "快速上手", "快速开始", "入门", "gettingstarted", "quickstart", "setup", "installation",
    "系统架构", "架构设计", "架构", "系統架構", "architecture", "systemarchitecture",
    "部署", "部署与运维", "部署与部署", "部署運維", "deployment", "deploymentoperations", "deploy",
    "项目结构", "目录结构", "目录地图", "專案結構", "projectstructure", "codebasemap", "directorystructure",
    "配置", "配置与环境变量", "环境变量", "設定與環境變數", "configuration", "configurationenvironment", "environment",
    "术语表", "术语", "術語表", "glossary", "terminology",
}


def _norm_title(t: str) -> str:
    return re.sub(r"[\s\-_/:：、，,.。()（）]+", "", (t or "")).lower()


def _detect_files(file_tree: str, patterns: list, limit: int = 8) -> list:
    """Pick up to `limit` file-tree paths matching `patterns`, in pattern priority
    order (so authoritative files like README/run.sh/Dockerfile come first)."""
    lines = [ln.strip() for ln in (file_tree or "").splitlines() if ln.strip()]
    out, seen = [], set()
    for pat in patterns:
        rx = re.compile(pat, re.I)
        for ln in lines:
            if ln in seen:
                continue
            if rx.search(ln):
                out.append(ln)
                seen.add(ln)
                if len(out) >= limit:
                    return out
    return out


def selected_foundational(spec_value: str) -> list:
    """Parse GenerateRequest.foundational -> list of scaffold ids. "" => all; a
    comma list selects specific ones (short names like "overview" allowed)."""
    raw = (spec_value or "").strip().lower()
    if raw in ("none", "off", "0", "false", "no"):
        return []
    if not raw:
        return list(_DEFAULT_FOUNDATIONAL)
    wanted = {p.strip() for p in raw.split(",") if p.strip()}
    wanted = {w if w.startswith("found-") else f"found-{w}" for w in wanted}
    return [s["id"] for s in _FOUNDATIONAL if s["id"] in wanted]


def build_scaffold(file_tree: str, include_ids: Optional[list] = None):
    """Return (pages, sections) for the guaranteed foundational pages. Each page is a
    normal page dict (empty content, filled during generation)."""
    include = set(_DEFAULT_FOUNDATIONAL if include_ids is None else include_ids)
    pages, section_pages = [], {}
    for spec in _FOUNDATIONAL:
        if spec["id"] not in include:
            continue
        pages.append({
            "id": spec["id"], "title": spec["title"], "content": "",
            "filePaths": _detect_files(file_tree, spec["patterns"]),
            "importance": "high", "relatedPages": [], "type": spec["type"],
        })
        section_pages.setdefault(spec["section"], []).append(spec["id"])
    sections = []
    for skey in ("intro", "ops"):
        pids = section_pages.get(skey)
        if not pids:
            continue
        sdef = _SCAFFOLD_SECTIONS[skey]
        sections.append({"id": sdef["id"], "title": sdef["title"],
                         "pages": pids, "subsections": None})
    return pages, sections


def prepend_scaffold(structure: dict, scaffold_pages: list, scaffold_sections: list) -> dict:
    """Put the scaffold pages/sections at the TOP of the wiki and drop any discovered
    page whose title is (near-)exactly a foundational one, so we don't duplicate."""
    if not scaffold_pages:
        return structure
    found_titles = {_norm_title(p["title"]) for p in scaffold_pages} | _FOUNDATIONAL_ALIASES
    orig_pages = structure.get("pages") or []
    dropped = {p["id"] for p in orig_pages if _norm_title(p.get("title", "")) in found_titles}
    kept_pages = [p for p in orig_pages if p["id"] not in dropped]
    structure["pages"] = scaffold_pages + kept_pages

    scaffold_ids = {s["id"] for s in scaffold_sections}
    new_secs = []
    for sec in structure.get("sections") or []:
        if sec["id"] in scaffold_ids:
            continue  # never happens, but keep scaffold authoritative
        sp = [pid for pid in (sec.get("pages") or []) if pid not in dropped]
        if sp:
            sec["pages"] = sp
            new_secs.append(sec)
    structure["sections"] = scaffold_sections + new_secs
    kept_root = [sid for sid in (structure.get("rootSections") or []) if sid in {s["id"] for s in new_secs}]
    structure["rootSections"] = [s["id"] for s in scaffold_sections] + kept_root
    return structure


def _trim_tree(file_tree: str, max_lines: int = 300) -> str:
    lines = [ln for ln in (file_tree or "").splitlines() if ln.strip()]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[:max_lines]) + f"\n… (+{len(lines) - max_lines} more files)"


# --- glossary enrichment: i18n labels + module map -> comprehensive term source ---

_I18N_RE = re.compile(r"(^|/)(i18n|locales?|lang|translations?)(/|$)", re.I)
_LOCALE_FILE_RE = re.compile(r"(^|/)(zh|zh-cn|zh-tw|en|en-us|ja|ko|kr|fr|es|ru|vi|pt|pt-br)\.json$", re.I)


def _flatten_labels(obj, out: list, seen: set, limit: int) -> None:
    """Collect (leaf-key, short-string-value) pairs from a nested locale object."""
    if len(out) >= limit:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten_labels(v, out, seen, limit)
            if len(out) >= limit:
                return
    elif isinstance(obj, list):
        for v in obj:
            _flatten_labels(v, out, seen, limit)
    elif isinstance(obj, str):
        s = obj.strip()
        if s and len(s) <= 40 and s not in seen:
            seen.add(s)
            out.append(s)


def _collect_i18n_labels(clone_dir: str, file_tree: str, limit: int = 500) -> list:
    """Flatten locale/i18n JSON files (key→label dictionaries) into a deduped list of
    short human labels — the richest source of business terms for the glossary."""
    if not clone_dir or not os.path.isdir(clone_dir):
        return []
    files = [ln.strip() for ln in (file_tree or "").splitlines()
             if ln.strip().lower().endswith(".json") and (_I18N_RE.search(ln) or _LOCALE_FILE_RE.search(ln.strip()))]
    files.sort(key=lambda p: 0 if "zh" in p.lower() else 1)  # prefer Chinese locale files
    out, seen = [], set()
    for rel in files[:20]:
        try:
            with open(os.path.join(clone_dir, rel), "r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
        except Exception:  # noqa: BLE001 — skip unparseable locale files
            continue
        _flatten_labels(data, out, seen, limit)
        if len(out) >= limit:
            break
    return out


def build_glossary_context(clone_dir: str, file_tree: str, structure: dict,
                           max_labels: int = 500) -> str:
    """Authoritative term sources for the glossary page: the full module/page map plus
    the project's i18n labels. Injected as extra context so the term list is complete."""
    parts = []
    titles = [p.get("title", "") for p in (structure.get("pages") or []) if p.get("title")]
    if titles:
        parts.append("Documented modules / pages (each is a domain area — extract its key terms):\n"
                     + "\n".join(f"- {t}" for t in titles[:200]))
    labels = _collect_i18n_labels(clone_dir, file_tree, max_labels)
    if labels:
        parts.append("UI / i18n labels (authoritative business terms — cover these):\n"
                     + "\n".join(f"- {s}" for s in labels))
    return "\n\n".join(parts)


# --- the runner --------------------------------------------------------------

def make_real_runner(*, self_base_url: Optional[str] = None, page_retries: int = 1):
    base = self_base_url or SELF_BASE_URL

    async def runner(job: Job, ctx: JobContext, req: GenerateRequest) -> None:
        async with httpx.AsyncClient() as client:
            if req.mode == "incremental":
                await _run_incremental(job, ctx, req, client, base, page_retries)
                return

            # fetching_repo
            await ctx.set_phase("fetching_repo")
            file_tree, readme, default_branch = await fetch_structure(client, base, req)

            # indexing (clone + embed, in-process). A forced regenerate rebuilds the
            # embedding index too (fresh clone + re-embed) so re-indexing/prompt changes
            # actually take effect; a plain first-time gen reuses any cached index.
            await ctx.set_phase("indexing")
            try:
                if req.force:
                    clone_dir, _ = await asyncio.to_thread(refresh_index, req)
                else:
                    clone_dir = await asyncio.to_thread(index_repo, req)
            except JobFailed:
                raise
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if "OPENAI_API_KEY" in msg or "GOOGLE_API_KEY" in msg or "embedding" in msg.lower():
                    raise JobFailed("embedding_failed", msg)
                if "Ollama" in msg and "not found" in msg:
                    raise JobFailed("embedding_model_not_found", msg)
                raise JobFailed("repo_fetch_failed", msg)

            if not file_tree and clone_dir:
                file_tree, readme2 = await asyncio.to_thread(derive_tree_from_clone, clone_dir)
                readme = readme or readme2
            if not file_tree:
                raise JobFailed("repo_fetch_failed", "Could not determine repository file tree")

            # Record the commit we're generating from (provenance for incremental updates).
            commit_id = await asyncio.to_thread(git_commit_id, clone_dir) if clone_dir else ""

            # planning. Two-phase (discover modules -> expand each into pages) for
            # comprehensive coverage; single-pass otherwise. Feed the route/page/menu
            # surface either way.
            await ctx.set_phase("planning")
            surface = extract_functional_surface(file_tree)
            if _use_two_phase(req):
                structure = await plan_two_phase(client, base, req, file_tree, readme, surface)
            else:
                xml = await stream_chat(client, base, req,
                                        build_structure_prompt(req.owner, req.repo, file_tree, readme,
                                                               req.comprehensive, req.max_pages, surface))
                structure = parse_structure(xml, req.comprehensive)

            # Prepend the guaranteed foundational pages (overview, getting-started,
            # architecture, deployment, structure, config, glossary) — discovery alone
            # doesn't reliably produce them.
            scaffold_pages, scaffold_sections = build_scaffold(
                file_tree, selected_foundational(req.foundational))
            structure = prepend_scaffold(structure, scaffold_pages, scaffold_sections)

            pages = structure["pages"]
            ctx.set_total_pages(len(pages))
            if not pages:
                raise JobFailed("planning_failed", "Wiki structure contained no pages")

            # Extra grounding for two scaffold pages: the structure page gets the file
            # tree; the glossary page gets the module map + i18n labels (so it's complete).
            tree_ctx = ("Project file tree (authoritative for directory structure and paths):\n"
                        f"<file_tree>\n{_trim_tree(file_tree)}\n</file_tree>")
            glossary_ctx = await asyncio.to_thread(
                build_glossary_context, clone_dir, file_tree, structure)

            def _extra_ctx(page):
                if page["id"] == SCAFFOLD_STRUCTURE_ID:
                    return tree_ctx
                if page["id"] == SCAFFOLD_GLOSSARY_ID:
                    return glossary_ctx
                return ""

            # Edit protection: carry over any page the user hand-edited (edited=True in
            # the previous cache, matched by title) instead of regenerating & overwriting
            # it. This also saves the LLM call for those pages.
            locked = {}
            try:
                old = await _load_cache(client, base, req)
                for op in ((old or {}).get("generated_pages") or {}).values():
                    if op.get("edited"):
                        locked[_norm_title(op.get("title", ""))] = op
            except Exception:  # noqa: BLE001 — protection is best-effort
                locked = {}
            if locked:
                logger.info("full regen: carrying over %d manually-edited page(s)", len(locked))

            # generating — pages in parallel (bounded), since a comprehensive wiki can
            # be dozens of pages and sequential generation would take far too long.
            await ctx.set_phase("generating")
            generated = {}
            now_ms = int(time.time() * 1000)
            sem = asyncio.Semaphore(PAGE_CONCURRENCY)

            async def gen_one(page):
                async with sem:
                    ctx.set_current_page(page["title"])
                    lk = locked.get(_norm_title(page.get("title", "")))
                    if lk is not None:  # keep the manual edit, skip the LLM
                        generated[page["id"]] = {
                            "id": page["id"], "title": page["title"], "content": lk.get("content", ""),
                            "filePaths": page["filePaths"], "importance": page["importance"],
                            "relatedPages": page["relatedPages"], "type": page.get("type", "feature"),
                            "edited": True, "updated_at": lk.get("updated_at"),
                            "prev_content": lk.get("prev_content"),
                        }
                        ctx.page_done()
                        return
                    content, ok = await _gen_page(client, base, req, page, default_branch, page_retries, _extra_ctx(page))
                    generated[page["id"]] = {
                        "id": page["id"], "title": page["title"], "content": content,
                        "filePaths": page["filePaths"], "importance": page["importance"],
                        "relatedPages": page["relatedPages"], "type": page.get("type", "feature"),
                        "edited": False, "updated_at": now_ms,
                    }
                    ctx.page_done(failed=not ok)

            await asyncio.gather(*(gen_one(p) for p in pages))
            ctx.set_current_page(None)

            if job.failed_pages >= len(pages):
                raise JobFailed("all_pages_failed", "Every page failed to generate")

            # saving
            await ctx.set_phase("saving")
            await save_cache(client, base, req, structure, generated,
                             commit_id=commit_id, default_branch=default_branch,
                             generated_at=int(time.time() * 1000))

    return runner
