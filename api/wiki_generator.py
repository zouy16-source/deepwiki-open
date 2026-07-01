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

LANGUAGE_LABELS = {
    "en": "English",
    "ja": "Japanese (日本語)",
    "zh": "Mandarin Chinese (中文)",
    "zh-tw": "Traditional Chinese (繁體中文)",
    "es": "Spanish (Español)",
    "kr": "Korean (한국어)",
    "vi": "Vietnamese (Tiếng Việt)",
    "pt-br": "Brazilian Portuguese (Português Brasileiro)",
    "fr": "Français (French)",
    "ru": "Русский (Russian)",
}


def language_label(code: str) -> str:
    return LANGUAGE_LABELS.get(code, "English")


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

# Localized labels for the "Relevant source files" <details> block so the header
# and intro line match the wiki's language.
_DETAILS_LABELS = {
    "zh": ("相关源文件", "以下文件用于生成本页面时作为上下文参考："),
    "zh-tw": ("相關原始檔", "以下檔案用於生成本頁面時作為上下文參考："),
    "en": ("Relevant source files", "The following files were used as context for generating this wiki page:"),
    "ja": ("関連ソースファイル", "このwikiページの生成にコンテキストとして使用されたファイル："),
    "es": ("Archivos fuente relevantes", "Los siguientes archivos se usaron como contexto para generar esta página:"),
    "kr": ("관련 소스 파일", "이 위키 페이지를 생성하는 데 사용된 파일:"),
    "vi": ("Tệp nguồn liên quan", "Các tệp sau được dùng làm ngữ cảnh để tạo trang wiki này:"),
    "pt-br": ("Arquivos-fonte relevantes", "Os seguintes arquivos foram usados como contexto para gerar esta página:"),
    "fr": ("Fichiers sources pertinents", "Les fichiers suivants ont servi de contexte pour générer cette page :"),
    "ru": ("Соответствующие исходные файлы", "Следующие файлы использованы как контекст для создания этой страницы:"),
}


def build_page_prompt(page_title: str, file_paths_list: str, language: str) -> str:
    lang = language_label(language)
    summary_label, intro_line = _DETAILS_LABELS.get(language, _DETAILS_LABELS["en"])
    return f"""You are an expert technical writer and software architect.
Your task is to generate a comprehensive and accurate technical wiki page in Markdown format about a specific feature, system, or module within a given software project.

You will be given:
1. The "[WIKI_PAGE_TOPIC]" for the page you need to create.
2. A list of "[RELEVANT_SOURCE_FILES]" from the project that you MUST use as the sole basis for the content. You have access to the full content of these files. You MUST use AT LEAST 5 relevant source files for comprehensive coverage - if fewer are provided, search for additional related files in the codebase.

CRITICAL STARTING INSTRUCTION:
Do NOT write any acknowledgements, disclaimers, apologies, or any preface. The VERY FIRST thing on the page MUST be a `<details>` block listing ALL the `[RELEVANT_SOURCE_FILES]` you used (AT LEAST 5; if fewer were provided, find additional related files). Output the block EXACTLY like this and put NOTHING inside it except the summary line, the intro line, and the file list (do NOT copy any of these instructions into the block):
<details>
<summary>{summary_label}</summary>

{intro_line}

{file_paths_list}
</details>

Immediately after the `<details>` block, the main title of the page should be a H1 Markdown heading: `# {page_title}`.

Based ONLY on the content of the `[RELEVANT_SOURCE_FILES]`:

1.  **Introduction:** Start with a concise introduction (1-2 paragraphs) explaining the purpose, scope, and high-level overview of "{page_title}" within the context of the overall project. If relevant, and if information is available in the provided files, link to other potential wiki pages using the format `[Link Text](#page-anchor-or-id)`.

2.  **Detailed Sections:** Break down "{page_title}" into logical sections using H2 (`##`) and H3 (`###`) Markdown headings. For each section:
    *   Explain the architecture, components, data flow, or logic relevant to the section's focus, as evidenced in the source files.
    *   Identify key functions, classes, data structures, API endpoints, or configuration elements pertinent to that section.

3.  **Mermaid Diagrams:**
    *   EXTENSIVELY use Mermaid diagrams (e.g., `flowchart TD`, `sequenceDiagram`, `classDiagram`, `erDiagram`, `graph TD`) to visually represent architectures, flows, relationships, and schemas found in the source files.
    *   Ensure diagrams are accurate and directly derived from information in the `[RELEVANT_SOURCE_FILES]`.
    *   Provide a brief explanation before or after each diagram to give context.
    *   CRITICAL: All diagrams MUST follow strict vertical orientation:
       - Use "graph TD" (top-down) directive for flow diagrams
       - NEVER use "graph LR" (left-right)
       - Maximum node width should be 3-4 words
       - ALWAYS wrap node/edge labels in double quotes when they contain special characters such as @, /, (), :, or punctuation, e.g. E["@nuxtjs/axios"], N["serial/account"] — unquoted special characters break the Mermaid parser
       - For sequence diagrams:
         - Start with "sequenceDiagram" directive on its own line
         - Define ALL participants at the beginning using "participant" keyword
         - Use the correct Mermaid arrow syntax (->>, -->>, ->x, -)) with colons for labels: A->>B: My Label
         - Use structural elements (loop/alt/opt/par) and notes where helpful

4.  **Tables:**
    *   Use Markdown tables to summarize key features, API parameters, configuration options, and data model fields.

5.  **Code Snippets (ENTIRELY OPTIONAL):**
    *   Include short, relevant code snippets directly from the `[RELEVANT_SOURCE_FILES]` with appropriate language identifiers.

6.  **Source Citations (EXTREMELY IMPORTANT):**
    *   For EVERY piece of significant information, you MUST cite the specific source file(s) and relevant line numbers.
    *   Use this exact format as PLAIN markdown text — for a range: Sources: [filename.ext:start_line-end_line](), for a single line: Sources: [filename.ext:line_number](), multiple files: Sources: [file1.ext:1-10](), [file2.ext:5](). Keep the parentheses empty.
    *   CRITICAL: Do NOT wrap the citation in backticks (`) or a code span/code block. Write it as normal markdown on its own so the links render as links, not as literal code.
    *   You MUST cite AT LEAST 5 different source files throughout the wiki page.

7.  **Technical Accuracy:** All information must be derived SOLELY from the `[RELEVANT_SOURCE_FILES]`. Do not infer or invent.

8.  **Clarity and Conciseness:** Use clear, professional, and concise technical language suitable for other developers.

9.  **Conclusion/Summary:** End with a brief summary paragraph if appropriate for "{page_title}".

IMPORTANT: Generate the content in {lang} language.

Remember:
- Ground every claim in the provided source files.
- Prioritize accuracy and direct representation of the code's functionality and structure.
- Structure the document logically for easy understanding by other developers.
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
      <relevant_files>
        <file_path>[Path to a relevant file]</file_path>
      </relevant_files>
      <related_pages>
        <related>page-2</related>
      </related_pages>
    </page>
  </pages>
</wiki_structure>"""


def build_structure_prompt(
    owner: str, repo: str, file_tree: str, readme: str, language: str, comprehensive: bool,
    max_pages: int = 40, functional_surface: str = "",
) -> str:
    lang = language_label(language)

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

IMPORTANT: The wiki content will be generated in {lang} language.

When designing the wiki structure, include pages that would benefit from visual diagrams (architecture overviews, data flow, component relationships, process workflows, state machines, class hierarchies).

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


async def _gen_page(client, base, req, page, default_branch, retries: int) -> Tuple[str, bool]:
    file_paths_list = "\n".join(
        f"- [{p}]({generate_file_url(req.repo_url, req.repo_type, default_branch, p)})" for p in page["filePaths"]
    )
    prompt = build_page_prompt(page["title"], file_paths_list, req.language)
    last_err = ""
    for attempt in range(retries + 1):
        try:
            content = _strip_md_fence(await stream_chat(client, base, req, prompt))
            if content.strip():
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

def build_discover_prompt(owner: str, repo: str, file_tree: str, readme: str, language: str,
                          max_modules: int, functional_surface: str = "") -> str:
    lang = language_label(language)
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

List every module: each menu entry, route and management screen (lists, detail/edit pages, approval/workflow, dictionaries, permissions & roles, reports, dashboards, settings, etc.), plus foundational topics (Overview, Architecture, Setup, Data Model, API Integration, Auth & Permissions, Deployment). Use the routes/pages/menu above as the authoritative map. Produce as many modules as the system genuinely has, up to {max_modules}.

The wiki content will be generated in {lang} language.

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
                        module_files: list, language: str, max_pages_per_module: int) -> str:
    lang = language_label(language)
    files_block = "\n".join(f"- {f}" for f in module_files) if module_files else "(discover the relevant files from the codebase)"
    return f"""For the module "{module_title}" of repository {owner}/{repo}, plan its wiki pages. This is the SECOND pass — decompose THIS module only.

Module description: {module_description}

Candidate files for this module:
{files_block}

Create 1 to {max_pages_per_module} wiki pages that fully document this module (its screens, sub-features, data flow, key APIs). If the module is simple, ONE page is enough; if it has several distinct sub-features, split them into separate pages. Do NOT invent unrelated pages.

The wiki content will be generated in {lang} language.

Return ONLY this XML (no markdown fences, no prose before/after):
<pages>
  <page id="page-1">
    <title>[Page title]</title>
    <description>[Brief description]</description>
    <importance>high|medium|low</importance>
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
                             build_discover_prompt(req.owner, req.repo, file_tree, readme, req.language,
                                                   req.max_modules, surface))
    meta, modules = parse_modules(dxml)
    modules = modules[: req.max_modules]
    if not modules:
        logger.warning("two-phase discovery found no modules; falling back to single-phase")
        xml = await stream_chat(client, base, req,
                                build_structure_prompt(req.owner, req.repo, file_tree, readme, req.language,
                                                       req.comprehensive, req.max_pages, surface))
        return parse_structure(xml, req.comprehensive)

    sem = asyncio.Semaphore(PLAN_CONCURRENCY)

    async def expand(mod):
        async with sem:
            try:
                xml = await stream_chat(client, base, req,
                                        build_expand_prompt(req.owner, req.repo, mod["title"], mod["description"],
                                                            mod["files"], req.language, req.max_pages_per_module))
                mp = parse_module_pages(xml, mod["id"])
                if mp:
                    return mod, mp
            except Exception as e:  # noqa: BLE001
                logger.warning("expand module '%s' failed: %s", mod.get("title"), e)
            # fallback: the module becomes a single page
            return mod, [{
                "id": f"{mod['id']}-p1", "title": mod["title"], "content": "",
                "filePaths": mod["files"][:8], "importance": "medium", "relatedPages": [],
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
                             language: str, max_modules: int) -> str:
    lang = language_label(language)
    existing = "\n".join(f"- {t}" for t in existing_titles if t) or "(none)"
    files = "\n".join(f"- {f}" for f in added_files)
    return f"""New files were added to repository {owner}/{repo}. Identify any NEW functional modules they introduce that are NOT already documented.

Newly added files:
{files}

The wiki ALREADY documents these modules — do NOT duplicate them:
{existing}

Return ONLY modules that are genuinely NEW (a new screen/route/feature not covered above). If the added files merely extend an existing module, return an EMPTY <modules></modules>.

The wiki content will be generated in {lang} language.

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
                                                      req.language, req.max_modules))
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
                                                            mod["files"] or surface_added, req.language,
                                                            req.max_pages_per_module))
                mp = parse_module_pages(xml, f"newmod-{idx}")
            except Exception as e:  # noqa: BLE001
                logger.warning("expand new module '%s' failed: %s", mod.get("title"), e)
                mp = []
            if not mp:
                mp = [{"id": f"newmod-{idx}-p1", "title": mod["title"], "content": "",
                       "filePaths": (mod["files"] or [])[:8], "importance": "medium", "relatedPages": []}]
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
                    "relatedPages": pg.get("relatedPages") or [],
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

            # indexing (clone + embed, in-process)
            await ctx.set_phase("indexing")
            try:
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
                                        build_structure_prompt(req.owner, req.repo, file_tree, readme, req.language,
                                                               req.comprehensive, req.max_pages, surface))
                structure = parse_structure(xml, req.comprehensive)
            pages = structure["pages"]
            ctx.set_total_pages(len(pages))
            if not pages:
                raise JobFailed("planning_failed", "Wiki structure contained no pages")

            # generating — pages in parallel (bounded), since a comprehensive wiki can
            # be dozens of pages and sequential generation would take far too long.
            await ctx.set_phase("generating")
            generated = {}
            sem = asyncio.Semaphore(PAGE_CONCURRENCY)

            async def gen_one(page):
                async with sem:
                    ctx.set_current_page(page["title"])
                    content, ok = await _gen_page(client, base, req, page, default_branch, page_retries)
                    generated[page["id"]] = {
                        "id": page["id"], "title": page["title"], "content": content,
                        "filePaths": page["filePaths"], "importance": page["importance"],
                        "relatedPages": page["relatedPages"],
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
