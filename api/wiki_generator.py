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

def build_page_prompt(page_title: str, file_paths_list: str, language: str) -> str:
    lang = language_label(language)
    return f"""You are an expert technical writer and software architect.
Your task is to generate a comprehensive and accurate technical wiki page in Markdown format about a specific feature, system, or module within a given software project.

You will be given:
1. The "[WIKI_PAGE_TOPIC]" for the page you need to create.
2. A list of "[RELEVANT_SOURCE_FILES]" from the project that you MUST use as the sole basis for the content. You have access to the full content of these files. You MUST use AT LEAST 5 relevant source files for comprehensive coverage - if fewer are provided, search for additional related files in the codebase.

CRITICAL STARTING INSTRUCTION:
The very first thing on the page MUST be a `<details>` block listing ALL the `[RELEVANT_SOURCE_FILES]` you used to generate the content. There MUST be AT LEAST 5 source files listed - if fewer were provided, you MUST find additional related files to include.
Format it exactly like this:
<details>
<summary>Relevant source files</summary>

Remember, do not provide any acknowledgements, disclaimers, apologies, or any other preface before the `<details>` block. JUST START with the `<details>` block.
The following files were used as context for generating this wiki page:

{file_paths_list}
<!-- Add additional relevant files if fewer than 5 were provided -->
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
    *   Use the exact format: `Sources: [filename.ext:start_line-end_line]()` for a range, or `Sources: [filename.ext:line_number]()` for a single line. Multiple files: `Sources: [file1.ext:1-10](), [file2.ext:5]()`.
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

async def save_cache(client, base, req: GenerateRequest, structure: dict, generated: dict) -> None:
    body = {
        "repo": {
            "owner": req.owner, "repo": req.repo, "type": req.repo_type,
            "token": req.token or None, "localPath": None, "repoUrl": req.repo_url,
        },
        "language": req.language,
        "wiki_structure": {
            "id": structure["id"], "title": structure["title"], "description": structure["description"],
            "pages": structure["pages"], "sections": structure["sections"], "rootSections": structure["rootSections"],
        },
        "generated_pages": generated,
        "provider": req.provider,
        "model": req.model,
    }
    r = await client.post(f"{base}/api/wiki_cache", json=body, timeout=120.0)
    r.raise_for_status()


# --- the runner --------------------------------------------------------------

def make_real_runner(*, self_base_url: Optional[str] = None, page_retries: int = 1):
    base = self_base_url or SELF_BASE_URL

    async def runner(job: Job, ctx: JobContext, req: GenerateRequest) -> None:
        async with httpx.AsyncClient() as client:
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

            # planning (structure XML). Feed the route/page/menu surface so the LLM
            # covers every functional module, and raise the page ceiling.
            await ctx.set_phase("planning")
            surface = extract_functional_surface(file_tree)
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
            await save_cache(client, base, req, structure, generated)

    return runner
