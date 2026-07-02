import os
import logging
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from typing import List, Optional, Dict, Any, Literal
import json
from datetime import datetime
from pydantic import BaseModel, Field
import google.generativeai as genai
import asyncio
import time
import httpx

# Configure logging
from api.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


# Initialize FastAPI app
app = FastAPI(
    title="Streaming API",
    description="API for streaming chat completions"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Helper function to get adalflow root path
def get_adalflow_default_root_path():
    return os.path.expanduser(os.path.join("~", ".adalflow"))

# --- Pydantic Models ---
class WikiPage(BaseModel):
    """
    Model for a wiki page.
    """
    id: str
    title: str
    content: str
    filePaths: List[str]
    importance: str # Should ideally be Literal['high', 'medium', 'low']
    relatedPages: List[str]
    type: Optional[str] = None  # page archetype: overview|architecture|feature|reference|cross-cutting|guide|glossary
    edited: Optional[bool] = None       # True = manually edited (locked from full regeneration)
    updated_at: Optional[int] = None    # unix ms of the last edit / single-page regenerate
    prev_content: Optional[str] = None  # previous content, kept for one-level undo / revert

class ProcessedProjectEntry(BaseModel):
    id: str  # Filename
    owner: str
    repo: str
    name: str  # owner/repo
    repo_type: str # Renamed from type to repo_type for clarity with existing models
    submittedAt: int # Timestamp
    language: str # Extracted from filename
    repo_url: Optional[str] = None # Real repo URL (read from the cache file)

class RepoInfo(BaseModel):
    owner: str
    repo: str
    type: str
    token: Optional[str] = None
    localPath: Optional[str] = None
    repoUrl: Optional[str] = None


class WikiSection(BaseModel):
    """
    Model for the wiki sections.
    """
    id: str
    title: str
    pages: List[str]
    subsections: Optional[List[str]] = None


class WikiStructureModel(BaseModel):
    """
    Model for the overall wiki structure.
    """
    id: str
    title: str
    description: str
    pages: List[WikiPage]
    sections: Optional[List[WikiSection]] = None
    rootSections: Optional[List[str]] = None

class WikiCacheData(BaseModel):
    """
    Model for the data to be stored in the wiki cache.
    """
    wiki_structure: WikiStructureModel
    generated_pages: Dict[str, WikiPage]
    repo_url: Optional[str] = None  #compatible for old cache
    repo: Optional[RepoInfo] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    commit_id: Optional[str] = None       # git SHA the wiki was generated from
    default_branch: Optional[str] = None  # branch the commit_id is on
    generated_at: Optional[int] = None    # unix ms timestamp of generation

class WikiCacheRequest(BaseModel):
    """
    Model for the request body when saving wiki cache.
    """
    repo: RepoInfo
    language: str
    wiki_structure: WikiStructureModel
    generated_pages: Dict[str, WikiPage]
    provider: str
    model: str
    commit_id: Optional[str] = None
    default_branch: Optional[str] = None
    generated_at: Optional[int] = None

class WikiExportRequest(BaseModel):
    """
    Model for requesting a wiki export.
    """
    repo_url: str = Field(..., description="URL of the repository")
    pages: List[WikiPage] = Field(..., description="List of wiki pages to export")
    format: Literal["markdown", "json"] = Field(..., description="Export format (markdown or json)")

# --- Model Configuration Models ---
class Model(BaseModel):
    """
    Model for LLM model configuration
    """
    id: str = Field(..., description="Model identifier")
    name: str = Field(..., description="Display name for the model")

class Provider(BaseModel):
    """
    Model for LLM provider configuration
    """
    id: str = Field(..., description="Provider identifier")
    name: str = Field(..., description="Display name for the provider")
    models: List[Model] = Field(..., description="List of available models for this provider")
    supportsCustomModel: Optional[bool] = Field(False, description="Whether this provider supports custom models")

class ModelConfig(BaseModel):
    """
    Model for the entire model configuration
    """
    providers: List[Provider] = Field(..., description="List of available model providers")
    defaultProvider: str = Field(..., description="ID of the default provider")

class AuthorizationConfig(BaseModel):
    code: str = Field(..., description="Authorization code")

from api.config import configs, WIKI_AUTH_MODE, WIKI_AUTH_CODE

@app.get("/lang/config")
async def get_lang_config():
    return configs["lang_config"]

@app.get("/auth/status")
async def get_auth_status():
    """
    Check if authentication is required for the wiki.
    """
    return {"auth_required": WIKI_AUTH_MODE}

@app.post("/auth/validate")
async def validate_auth_code(request: AuthorizationConfig):
    """
    Check authorization code.
    """
    return {"success": WIKI_AUTH_CODE == request.code}

@app.get("/models/config", response_model=ModelConfig)
async def get_model_config():
    """
    Get available model providers and their models.

    This endpoint returns the configuration of available model providers and their
    respective models that can be used throughout the application.

    Returns:
        ModelConfig: A configuration object containing providers and their models
    """
    try:
        logger.info("Fetching model configurations")

        # Create providers from the config file
        providers = []
        default_provider = configs.get("default_provider", "google")

        # Add provider configuration based on config.py
        for provider_id, provider_config in configs["providers"].items():
            models = []
            # Add models from config
            for model_id in provider_config["models"].keys():
                # Get a more user-friendly display name if possible
                models.append(Model(id=model_id, name=model_id))

            # Add provider with its models
            providers.append(
                Provider(
                    id=provider_id,
                    name=f"{provider_id.capitalize()}",
                    supportsCustomModel=provider_config.get("supportsCustomModel", False),
                    models=models
                )
            )

        # Create and return the full configuration
        config = ModelConfig(
            providers=providers,
            defaultProvider=default_provider
        )
        return config

    except Exception as e:
        logger.error(f"Error creating model configuration: {str(e)}")
        # Return some default configuration in case of error
        return ModelConfig(
            providers=[
                Provider(
                    id="google",
                    name="Google",
                    supportsCustomModel=True,
                    models=[
                        Model(id="gemini-2.5-flash", name="Gemini 2.5 Flash")
                    ]
                )
            ],
            defaultProvider="google"
        )

@app.post("/export/wiki")
async def export_wiki(request: WikiExportRequest):
    """
    Export wiki content as Markdown or JSON.

    Args:
        request: The export request containing wiki pages and format

    Returns:
        A downloadable file in the requested format
    """
    try:
        logger.info(f"Exporting wiki for {request.repo_url} in {request.format} format")

        # Extract repository name from URL for the filename
        repo_parts = request.repo_url.rstrip('/').split('/')
        repo_name = repo_parts[-1] if len(repo_parts) > 0 else "wiki"

        # Get current timestamp for the filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if request.format == "markdown":
            # Generate Markdown content
            content = generate_markdown_export(request.repo_url, request.pages)
            filename = f"{repo_name}_wiki_{timestamp}.md"
            media_type = "text/markdown"
        else:  # JSON format
            # Generate JSON content
            content = generate_json_export(request.repo_url, request.pages)
            filename = f"{repo_name}_wiki_{timestamp}.json"
            media_type = "application/json"

        # Create response with appropriate headers for file download
        response = Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )

        return response

    except Exception as e:
        error_msg = f"Error exporting wiki: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@app.get("/local_repo/structure")
async def get_local_repo_structure(path: str = Query(None, description="Path to local repository")):
    """Return the file tree and README content for a local repository."""
    if not path:
        return JSONResponse(
            status_code=400,
            content={"error": "No path provided. Please provide a 'path' query parameter."}
        )

    if not os.path.isdir(path):
        return JSONResponse(
            status_code=404,
            content={"error": f"Directory not found: {path}"}
        )

    try:
        logger.info(f"Processing local repository at: {path}")
        file_tree_lines = []
        readme_content = ""

        for root, dirs, files in os.walk(path):
            # Exclude hidden dirs/files and virtual envs
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__' and d != 'node_modules' and d != '.venv']
            for file in files:
                if file.startswith('.') or file == '__init__.py' or file == '.DS_Store':
                    continue
                rel_dir = os.path.relpath(root, path)
                rel_file = os.path.join(rel_dir, file) if rel_dir != '.' else file
                file_tree_lines.append(rel_file)
                # Find README.md (case-insensitive)
                if file.lower() == 'readme.md' and not readme_content:
                    try:
                        with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                            readme_content = f.read()
                    except Exception as e:
                        logger.warning(f"Could not read README.md: {str(e)}")
                        readme_content = ""

        file_tree_str = '\n'.join(sorted(file_tree_lines))
        return {"file_tree": file_tree_str, "readme": readme_content}
    except Exception as e:
        logger.error(f"Error processing local repository: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Error processing local repository: {str(e)}"}
        )

def generate_markdown_export(repo_url: str, pages: List[WikiPage]) -> str:
    """
    Generate Markdown export of wiki pages.

    Args:
        repo_url: The repository URL
        pages: List of wiki pages

    Returns:
        Markdown content as string
    """
    # Start with metadata
    markdown = f"# Wiki Documentation for {repo_url}\n\n"
    markdown += f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    # Add table of contents
    markdown += "## Table of Contents\n\n"
    for page in pages:
        markdown += f"- [{page.title}](#{page.id})\n"
    markdown += "\n"

    # Add each page
    for page in pages:
        markdown += f"<a id='{page.id}'></a>\n\n"
        markdown += f"## {page.title}\n\n"



        # Add related pages
        if page.relatedPages and len(page.relatedPages) > 0:
            markdown += "### Related Pages\n\n"
            related_titles = []
            for related_id in page.relatedPages:
                # Find the title of the related page
                related_page = next((p for p in pages if p.id == related_id), None)
                if related_page:
                    related_titles.append(f"[{related_page.title}](#{related_id})")

            if related_titles:
                markdown += "Related topics: " + ", ".join(related_titles) + "\n\n"

        # Add page content
        markdown += f"{page.content}\n\n"
        markdown += "---\n\n"

    return markdown

def generate_json_export(repo_url: str, pages: List[WikiPage]) -> str:
    """
    Generate JSON export of wiki pages.

    Args:
        repo_url: The repository URL
        pages: List of wiki pages

    Returns:
        JSON content as string
    """
    # Create a dictionary with metadata and pages
    export_data = {
        "metadata": {
            "repository": repo_url,
            "generated_at": datetime.now().isoformat(),
            "page_count": len(pages)
        },
        "pages": [page.model_dump() for page in pages]
    }

    # Convert to JSON string with pretty formatting
    return json.dumps(export_data, indent=2)

# Import the simplified chat implementation
from api.simple_chat import chat_completions_stream
from api.websocket_wiki import handle_websocket_chat

# Add the chat_completions_stream endpoint to the main app
app.add_api_route("/chat/completions/stream", chat_completions_stream, methods=["POST"])

# Add the WebSocket endpoint
app.add_websocket_route("/ws/chat", handle_websocket_chat)

# --- Wiki Cache Helper Functions ---

WIKI_CACHE_DIR = os.path.join(get_adalflow_default_root_path(), "wikicache")
os.makedirs(WIKI_CACHE_DIR, exist_ok=True)

def get_wiki_cache_path(owner: str, repo: str, repo_type: str, language: str) -> str:
    """Generates the file path for a given wiki cache."""
    filename = f"deepwiki_cache_{repo_type}_{owner}_{repo}_{language}.json"
    return os.path.join(WIKI_CACHE_DIR, filename)

async def read_wiki_cache(owner: str, repo: str, repo_type: str, language: str) -> Optional[WikiCacheData]:
    """Reads wiki cache data from the file system."""
    cache_path = get_wiki_cache_path(owner, repo, repo_type, language)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return WikiCacheData(**data)
        except Exception as e:
            logger.error(f"Error reading wiki cache from {cache_path}: {e}")
            return None
    return None

async def save_wiki_cache(data: WikiCacheRequest) -> bool:
    """Saves wiki cache data to the file system."""
    cache_path = get_wiki_cache_path(data.repo.owner, data.repo.repo, data.repo.type, data.language)
    logger.info(f"Attempting to save wiki cache. Path: {cache_path}")
    try:
        payload = WikiCacheData(
            wiki_structure=data.wiki_structure,
            generated_pages=data.generated_pages,
            repo=data.repo,
            repo_url=data.repo.repoUrl,
            provider=data.provider,
            model=data.model,
            commit_id=data.commit_id,
            default_branch=data.default_branch,
            generated_at=data.generated_at,
        )
        # Log size of data to be cached for debugging (avoid logging full content if large)
        try:
            payload_json = payload.model_dump_json()
            payload_size = len(payload_json.encode('utf-8'))
            logger.info(f"Payload prepared for caching. Size: {payload_size} bytes.")
        except Exception as ser_e:
            logger.warning(f"Could not serialize payload for size logging: {ser_e}")


        logger.info(f"Writing cache file to: {cache_path}")
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(payload.model_dump(), f, indent=2)
        logger.info(f"Wiki cache successfully saved to {cache_path}")
        return True
    except IOError as e:
        logger.error(f"IOError saving wiki cache to {cache_path}: {e.strerror} (errno: {e.errno})", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Unexpected error saving wiki cache to {cache_path}: {e}", exc_info=True)
        return False

# --- Wiki Cache API Endpoints ---

@app.get("/api/wiki_cache", response_model=Optional[WikiCacheData])
async def get_cached_wiki(
    owner: str = Query(..., description="Repository owner"),
    repo: str = Query(..., description="Repository name"),
    repo_type: str = Query(..., description="Repository type (e.g., github, gitlab)"),
    language: str = Query(..., description="Language of the wiki content")
):
    """
    Retrieves cached wiki data (structure and generated pages) for a repository.
    """
    # Language validation
    supported_langs = configs["lang_config"]["supported_languages"]
    if not supported_langs.__contains__(language):
        language = configs["lang_config"]["default"]

    logger.info(f"Attempting to retrieve wiki cache for {owner}/{repo} ({repo_type}), lang: {language}")
    cached_data = await read_wiki_cache(owner, repo, repo_type, language)
    if cached_data:
        return cached_data
    else:
        # Return 200 with null body if not found, as frontend expects this behavior
        # Or, raise HTTPException(status_code=404, detail="Wiki cache not found") if preferred
        logger.info(f"Wiki cache not found for {owner}/{repo} ({repo_type}), lang: {language}")
        return None

@app.post("/api/wiki_cache")
async def store_wiki_cache(request_data: WikiCacheRequest):
    """
    Stores generated wiki data (structure and pages) to the server-side cache.
    """
    # Language validation
    supported_langs = configs["lang_config"]["supported_languages"]

    if not supported_langs.__contains__(request_data.language):
        request_data.language = configs["lang_config"]["default"]

    logger.info(f"Attempting to save wiki cache for {request_data.repo.owner}/{request_data.repo.repo} ({request_data.repo.type}), lang: {request_data.language}")
    r = request_data.repo
    # Snapshot the prior cache to record generation history (only for pages that
    # actually changed — carried-over edited/unchanged pages get no new entry).
    prior = await read_wiki_cache(r.owner, r.repo, r.type, request_data.language)
    prior_pages = prior.generated_pages if prior else {}
    success = await save_wiki_cache(request_data)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save wiki cache")
    try:
        at = _now_ms()
        hist = _read_history(r.owner, r.repo, r.type, request_data.language)
        changed = 0
        for pid, pg in request_data.generated_pages.items():
            old = prior_pages.get(pid)
            if old is not None and old.content == pg.content:
                continue  # unchanged (e.g. edit-locked carry-over) — no timeline noise
            action = "regenerated" if old is not None else "generated"
            entries = hist.get(pid) or []
            entries.append({
                "at": at, "action": action, "source": "ai", "actor": None,
                "model": request_data.model, "provider": request_data.provider,
                "summary": "AI 生成" if action == "generated" else "AI 重新生成",
                "size": len(pg.content or ""), "content": pg.content,
            })
            hist[pid] = entries[-HISTORY_CAP:]
            changed += 1
        if changed:
            _write_history(r.owner, r.repo, r.type, request_data.language, hist)
    except Exception as e:  # noqa: BLE001 — history is best-effort, never fail the save
        logger.warning(f"Failed to record generation history: {e}")
    return {"message": "Wiki cache saved successfully"}

@app.delete("/api/wiki_cache")
async def delete_wiki_cache(
    owner: str = Query(..., description="Repository owner"),
    repo: str = Query(..., description="Repository name"),
    repo_type: str = Query(..., description="Repository type (e.g., github, gitlab)"),
    language: str = Query(..., description="Language of the wiki content"),
    authorization_code: Optional[str] = Query(None, description="Authorization code")
):
    """
    Deletes a specific wiki cache from the file system.
    """
    # Language validation
    supported_langs = configs["lang_config"]["supported_languages"]
    if not supported_langs.__contains__(language):
        raise HTTPException(status_code=400, detail="Language is not supported")

    if WIKI_AUTH_MODE:
        logger.info("check the authorization code")
        if not authorization_code or WIKI_AUTH_CODE != authorization_code:
            raise HTTPException(status_code=401, detail="Authorization code is invalid")

    logger.info(f"Attempting to delete wiki cache for {owner}/{repo} ({repo_type}), lang: {language}")
    cache_path = get_wiki_cache_path(owner, repo, repo_type, language)

    if os.path.exists(cache_path):
        try:
            os.remove(cache_path)
            logger.info(f"Successfully deleted wiki cache: {cache_path}")
            return {"message": f"Wiki cache for {owner}/{repo} ({language}) deleted successfully"}
        except Exception as e:
            logger.error(f"Error deleting wiki cache {cache_path}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to delete wiki cache: {str(e)}")
    else:
        logger.warning(f"Wiki cache not found, cannot delete: {cache_path}")
        raise HTTPException(status_code=404, detail="Wiki cache not found")


# --- Per-page edit / regenerate / revert (Wikipedia-style page refinement) ----
# The wiki cache stores one entry per page, so a single page can be updated without
# re-running the whole (slow) generation. Regenerate reuses the existing embedding
# index — one LLM call — and optionally takes a user instruction. Manual edits set
# `edited=True`, which a full regeneration skips (see wiki_generator).

def _now_ms() -> int:
    return int(time.time() * 1000)


def _write_cache_file(owner: str, repo: str, repo_type: str, language: str, cached: WikiCacheData) -> bool:
    cache_path = get_wiki_cache_path(owner, repo, repo_type, language)
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cached.model_dump(), f, indent=2)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to write wiki cache {cache_path}: {e}", exc_info=True)
        return False


def _mirror_structure_meta(cached: WikiCacheData, page: WikiPage) -> None:
    """Keep the sidebar copy (wiki_structure.pages) in sync with edit/regenerate
    metadata (title/type/edited/updated_at) — content itself lives in generated_pages."""
    for sp in cached.wiki_structure.pages:
        if sp.id == page.id:
            sp.title = page.title
            sp.type = page.type
            sp.edited = page.edited
            sp.updated_at = page.updated_at
            break


# --- per-page history / audit timeline (stored in a SEPARATE file, loaded on demand
# so it never bloats the main cache) -------------------------------------------------
# Each entry answers who / when / what: action + source(ai|human) + actor(null until
# auth) + model (the AI "who") + a content snapshot for diff & revert-to-any-version.
HISTORY_CAP = 10  # snapshots kept per page (oldest dropped)


class HistoryEntry(BaseModel):
    at: int                          # unix ms
    action: str                      # generated | regenerated | edited | reverted
    source: str                      # ai | human
    actor: Optional[str] = None      # username/email — null until an auth system exists
    model: Optional[str] = None      # AI model that produced it (the "who" for ai)
    provider: Optional[str] = None
    summary: str = ""                # e.g. the regenerate instruction, or "手动编辑"
    size: int = 0                    # content length (quick timeline stat)
    content: Optional[str] = None    # snapshot, for diffing and revert-to-this-version


def get_history_path(owner: str, repo: str, repo_type: str, language: str) -> str:
    return os.path.join(WIKI_CACHE_DIR, f"deepwiki_history_{repo_type}_{owner}_{repo}_{language}.json")


def _read_history(owner: str, repo: str, repo_type: str, language: str) -> Dict[str, Any]:
    path = get_history_path(owner, repo, repo_type, language)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error reading history {path}: {e}")
    return {}


def _write_history(owner: str, repo: str, repo_type: str, language: str, data: Dict[str, Any]) -> None:
    path = get_history_path(owner, repo, repo_type, language)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Error writing history {path}: {e}", exc_info=True)


def _record_history(owner: str, repo: str, repo_type: str, language: str, page_id: str, *,
                    action: str, source: str, content: str, at: Optional[int] = None,
                    summary: str = "", model: Optional[str] = None,
                    provider: Optional[str] = None, actor: Optional[str] = None) -> None:
    """Append one timeline entry for a page (read-modify-write the history file)."""
    data = _read_history(owner, repo, repo_type, language)
    entries = data.get(page_id) or []
    entries.append({
        "at": at or _now_ms(), "action": action, "source": source, "actor": actor,
        "model": model, "provider": provider, "summary": summary,
        "size": len(content or ""), "content": content,
    })
    data[page_id] = entries[-HISTORY_CAP:]
    _write_history(owner, repo, repo_type, language, data)


class PageEditRequest(BaseModel):
    owner: str
    repo: str
    repo_type: str = "github"
    language: str = "zh"
    page_id: str
    content: str
    title: Optional[str] = None


class PageRevertRequest(BaseModel):
    owner: str
    repo: str
    repo_type: str = "github"
    language: str = "zh"
    page_id: str
    at: Optional[int] = None  # target history-entry timestamp; None = one-level (prev_content)


class PageRegenerateRequest(BaseModel):
    owner: str
    repo: str
    repo_type: str = "github"
    language: str = "zh"
    page_id: str
    repo_url: str = ""
    token: str = ""
    provider: str = ""
    model: str = ""
    instruction: str = ""  # optional reader guidance ("the flow is wrong, …", "add edge cases")


async def _load_page_or_404(req) -> tuple:
    cached = await read_wiki_cache(req.owner, req.repo, req.repo_type, req.language)
    if not cached:
        raise HTTPException(status_code=404, detail="Wiki cache not found")
    page = cached.generated_pages.get(req.page_id)
    if page is None:
        raise HTTPException(status_code=404, detail=f"Page '{req.page_id}' not found")
    return cached, page


@app.put("/api/wiki/page")
async def edit_wiki_page(req: PageEditRequest):
    """Save a manually-edited page. Marks it `edited` (locked from full regeneration)
    and keeps the previous content for one-level revert."""
    cached, page = await _load_page_or_404(req)
    page.prev_content = page.content
    page.content = req.content
    if req.title:
        page.title = req.title
    page.edited = True
    page.updated_at = _now_ms()
    _mirror_structure_meta(cached, page)
    if not _write_cache_file(req.owner, req.repo, req.repo_type, req.language, cached):
        raise HTTPException(status_code=500, detail="Failed to save page")
    _record_history(req.owner, req.repo, req.repo_type, req.language, req.page_id,
                    action="edited", source="human", content=page.content,
                    at=page.updated_at, summary="手动编辑")
    return {"message": "Page saved", "page": page}


@app.post("/api/wiki/page/revert")
async def revert_wiki_page(req: PageRevertRequest):
    """Restore a previous version. With `at`, restore that history snapshot
    (revert-to-any-version); without, swap the one-level prev_content."""
    cached, page = await _load_page_or_404(req)
    if req.at is not None:
        entries = _read_history(req.owner, req.repo, req.repo_type, req.language).get(req.page_id) or []
        target = next((e for e in entries if e.get("at") == req.at), None)
        if not target or target.get("content") is None:
            raise HTTPException(status_code=404, detail="History version not found")
        new_content = target["content"]
        summary = f"回滚到 {datetime.fromtimestamp(req.at / 1000).strftime('%Y-%m-%d %H:%M')}"
    else:
        if not page.prev_content:
            raise HTTPException(status_code=400, detail="No previous version to revert to")
        new_content = page.prev_content
        summary = "回滚到上一版"
    page.prev_content = page.content
    page.content = new_content
    page.edited = True
    page.updated_at = _now_ms()
    _mirror_structure_meta(cached, page)
    if not _write_cache_file(req.owner, req.repo, req.repo_type, req.language, cached):
        raise HTTPException(status_code=500, detail="Failed to save page")
    _record_history(req.owner, req.repo, req.repo_type, req.language, req.page_id,
                    action="reverted", source="human", content=new_content,
                    at=page.updated_at, summary=summary)
    return {"message": "Page reverted", "page": page}


@app.post("/api/wiki/page/regenerate")
async def regenerate_wiki_page(req: PageRegenerateRequest):
    """Regenerate ONE page with a single LLM call, reusing the existing embedding
    index. Optional `instruction` steers the fix. Overwrites content (edited=False)
    but keeps the previous version for revert."""
    cached, page = await _load_page_or_404(req)

    page_dict = {
        "id": page.id,
        "title": page.title,
        "type": page.type or "feature",
        "filePaths": page.filePaths or [],
        "importance": page.importance or "medium",
        "relatedPages": page.relatedPages or [],
    }
    gen_req = GenerateRequest(
        owner=req.owner, repo=req.repo, repo_type=req.repo_type, language=req.language,
        repo_url=req.repo_url or (cached.repo.repoUrl if cached.repo else None) or cached.repo_url or "",
        token=req.token or (cached.repo.token if cached.repo else None) or "",
        provider=req.provider or cached.provider or "",
        model=req.model or cached.model or "",
    )
    default_branch = cached.default_branch or "main"

    async with httpx.AsyncClient() as client:
        content, ok = await _gen_page(
            client, SELF_BASE_URL, gen_req, page_dict, default_branch, 1,
            extra_context="", instruction=req.instruction,
        )
    if not ok:
        raise HTTPException(status_code=502, detail=f"Regeneration failed: {content}")

    page.prev_content = page.content
    page.content = content
    page.edited = False  # freshly AI-generated
    page.updated_at = _now_ms()
    _mirror_structure_meta(cached, page)
    if not _write_cache_file(req.owner, req.repo, req.repo_type, req.language, cached):
        raise HTTPException(status_code=500, detail="Failed to save regenerated page")
    _record_history(req.owner, req.repo, req.repo_type, req.language, req.page_id,
                    action="regenerated", source="ai", content=content, at=page.updated_at,
                    model=gen_req.model or cached.model, provider=gen_req.provider or cached.provider,
                    summary=(req.instruction.strip() or "重新生成"))
    return {"message": "Page regenerated", "content": content, "page": page}


@app.get("/api/wiki/page/history")
async def get_wiki_page_history(
    owner: str = Query(...),
    repo: str = Query(...),
    repo_type: str = Query(...),
    language: str = Query(...),
    page_id: str = Query(...),
):
    """Return a page's change timeline (oldest→newest), each entry with a content
    snapshot for client-side diff and revert-to-version."""
    entries = _read_history(owner, repo, repo_type, language).get(page_id) or []
    return {"entries": entries}


# --- Wiki Generation Job System --- (background tasks; see docs/wiki-jobs-api.md)
from api.wiki_jobs import JobManager, GenerateRequest, make_fake_runner, JobKey
from api.wiki_generator import make_real_runner, _gen_page, SELF_BASE_URL


def _wiki_cache_exists(key: JobKey) -> bool:
    """A wiki is 'already generated' if its cache file exists. Cache identity is
    (repo_type, owner, repo, language) — comprehensive is not part of the file name."""
    return os.path.exists(get_wiki_cache_path(key.owner, key.repo, key.repo_type, key.language))


# Real pipeline (ported from the frontend orchestration). Set WIKI_JOBS_FAKE=1 to
# swap in the fake runner (walks phases with sleeps) for state-machine testing.
_use_fake = os.environ.get("WIKI_JOBS_FAKE", "").lower() in ("1", "true", "t")
_job_runner = make_fake_runner() if _use_fake else make_real_runner(page_retries=1)
wiki_job_manager = JobManager(
    max_concurrent=int(os.environ.get("MAX_CONCURRENT_JOBS", "3")),
    cache_exists=_wiki_cache_exists,
    runner=_job_runner,
    page_retries=1,
)


def _check_job_auth(authorization_code: Optional[str]) -> None:
    if WIKI_AUTH_MODE and (not authorization_code or WIKI_AUTH_CODE != authorization_code):
        raise HTTPException(status_code=401, detail="Authorization code is invalid")


@app.post("/api/wiki/generate")
async def start_wiki_generation(
    request_data: GenerateRequest,
    response: Response,
    authorization_code: Optional[str] = Query(None, description="Authorization code"),
):
    """Start (or join) a background wiki-generation job. Returns immediately.

    202 = a new job was started; 200 = joined an in-flight job or the wiki is
    already cached (dedup / cache-hit, see docs §2.1)."""
    _check_job_auth(authorization_code)
    job, created = await wiki_job_manager.submit(request_data)
    response.status_code = 202 if created else 200
    return job.view()


@app.get("/api/wiki/jobs")
async def list_wiki_jobs(
    status: Optional[str] = Query(None, description="Comma-separated status filter, e.g. queued,running"),
    owner: Optional[str] = Query(None, description="Filter by owner"),
    repo: Optional[str] = Query(None, description="Filter by repo"),
    limit: int = Query(100, ge=1, le=500),
):
    """List generation jobs (active + recently finished within TTL). For list polling."""
    return wiki_job_manager.list_view(status=status, owner=owner, repo=repo, limit=limit)


@app.get("/api/wiki/jobs/{job_id}")
async def get_wiki_job(job_id: str):
    """Single job detail (for the detail page / focused polling)."""
    job = wiki_job_manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.view()


@app.delete("/api/wiki/jobs/{job_id}")
async def cancel_wiki_job(
    job_id: str,
    authorization_code: Optional[str] = Query(None, description="Authorization code"),
):
    """Cancel a queued/running job."""
    _check_job_auth(authorization_code)
    job = await wiki_job_manager.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.view()


def _gitlab_update_status(repo_url: str, cached_commit: str, branch: str, token: str = "") -> dict:
    """Compare the cached commit against the latest on `branch` via the GitLab
    compare API. Returns behind_count + changed_files (the latter seeds Phase B)."""
    import os
    import requests
    import urllib3
    from urllib.parse import urlparse, quote
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    tok = token or os.environ.get("GITLAB_TOKEN", "")
    headers = {"PRIVATE-TOKEN": tok} if tok else {}
    parsed = urlparse(repo_url)
    if parsed.netloc:
        base = f"https://{parsed.netloc}"
        project_path = parsed.path.strip("/").replace(".git", "")
    else:
        base = (os.environ.get("GITLAB_URL") or "https://gitlab.com").rstrip("/")
        project_path = repo_url.strip("/").replace(".git", "")
    api = f"{base}/api/v4/projects/{quote(project_path, safe='')}"

    try:
        r = requests.get(f"{api}/repository/compare", params={"from": cached_commit, "to": branch},
                         headers=headers, verify=False, timeout=25)
        if r.status_code == 200:
            data = r.json()
            latest = (data.get("commit") or {}).get("id") or cached_commit
            behind = len(data.get("commits") or [])
            return {
                "status": "up_to_date" if behind == 0 else "behind",
                "cached_commit": cached_commit,
                "latest_commit": latest,
                "behind_count": behind,
                "changed_files": len(data.get("diffs") or []),
            }
        # compare failed (e.g. cached commit was rebased away): fall back to latest tip.
        c = requests.get(f"{api}/repository/commits", params={"ref_name": branch, "per_page": 1},
                         headers=headers, verify=False, timeout=25)
        if c.status_code == 200 and c.json():
            latest = c.json()[0].get("id")
            return {"status": "behind" if latest != cached_commit else "up_to_date",
                    "cached_commit": cached_commit, "latest_commit": latest, "behind_count": None}
        return {"status": "unknown", "cached_commit": cached_commit, "error": f"compare HTTP {r.status_code}"}
    except Exception as e:  # noqa: BLE001
        logger.warning("update_status compare failed for %s: %s", repo_url, e)
        return {"status": "unknown", "cached_commit": cached_commit, "error": str(e)}


@app.get("/api/wiki/update_status")
async def wiki_update_status(
    owner: str = Query(...),
    repo: str = Query(...),
    repo_type: str = Query(...),
    language: str = Query(...),
):
    """Is the cached wiki behind the repo's latest commit? Compares the stored
    commit_id against the remote branch tip (see docs/wiki-jobs-api.md — Phase A)."""
    cached = await read_wiki_cache(owner, repo, repo_type, language)
    if not cached:
        raise HTTPException(status_code=404, detail="Wiki cache not found")
    cached_commit = cached.commit_id
    branch = cached.default_branch or "main"
    repo_url = cached.repo_url or (cached.repo.repoUrl if cached.repo else None)
    if not cached_commit or not repo_url:
        return {"status": "unknown", "cached_commit": cached_commit,
                "reason": "cache has no commit_id/repo_url (generated before provenance tracking)"}
    if repo_type != "gitlab":
        return {"status": "unknown", "cached_commit": cached_commit, "reason": "only gitlab supported for now"}
    return _gitlab_update_status(repo_url, cached_commit, branch)


def _gitlab_changed_files(repo_url: str, from_sha: str, to_ref: str, token: str = "") -> dict:
    """Files changed between `from_sha` and `to_ref` via the GitLab compare API.
    Powers incremental updates (Phase B): changed files -> affected wiki pages."""
    import os
    import requests
    import urllib3
    from urllib.parse import urlparse, quote
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    tok = token or os.environ.get("GITLAB_TOKEN", "")
    headers = {"PRIVATE-TOKEN": tok} if tok else {}
    parsed = urlparse(repo_url)
    if parsed.netloc:
        base = f"https://{parsed.netloc}"
        project_path = parsed.path.strip("/").replace(".git", "")
    else:
        base = (os.environ.get("GITLAB_URL") or "https://gitlab.com").rstrip("/")
        project_path = repo_url.strip("/").replace(".git", "")
    api = f"{base}/api/v4/projects/{quote(project_path, safe='')}"

    r = requests.get(f"{api}/repository/compare", params={"from": from_sha, "to": to_ref},
                     headers=headers, verify=False, timeout=30)
    r.raise_for_status()
    data = r.json()
    new_sha = (data.get("commit") or {}).get("id") or from_sha
    changed, added, deleted, renamed = set(), set(), set(), set()
    for d in data.get("diffs") or []:
        op, np = d.get("old_path"), d.get("new_path")
        if d.get("new_file") and np:
            added.add(np)
        elif d.get("deleted_file") and op:
            deleted.add(op)
        elif d.get("renamed_file"):
            renamed.update(p for p in (op, np) if p)
        for p in (op, np):
            if p:
                changed.add(p)
    return {"new_sha": new_sha, "changed": sorted(changed), "added": sorted(added),
            "deleted": sorted(deleted), "renamed": sorted(renamed)}


@app.get("/api/gitlab/compare_files")
def gitlab_compare_files(repo_url: str, from_sha: str, to_ref: str, token: str = ""):
    """Changed files between two commits/refs (for incremental wiki updates)."""
    try:
        return _gitlab_changed_files(repo_url, from_sha, to_ref, token)
    except Exception as e:  # noqa: BLE001
        logger.warning("compare_files failed for %s: %s", repo_url, e)
        return {"error": str(e), "new_sha": from_sha, "changed": [], "added": [], "deleted": [], "renamed": []}


@app.get("/health")
async def health_check():
    """Health check endpoint for Docker and monitoring"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "deepwiki-api"
    }

@app.get("/")
async def root():
    """Root endpoint to check if the API is running and list available endpoints dynamically."""
    # Collect routes dynamically from the FastAPI app
    endpoints = {}
    for route in app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            # Skip docs and static routes
            if route.path in ["/openapi.json", "/docs", "/redoc", "/favicon.ico"]:
                continue
            # Group endpoints by first path segment
            path_parts = route.path.strip("/").split("/")
            group = path_parts[0].capitalize() if path_parts[0] else "Root"
            method_list = list(route.methods - {"HEAD", "OPTIONS"})
            for method in method_list:
                endpoints.setdefault(group, []).append(f"{method} {route.path}")

    # Optionally, sort endpoints for readability
    for group in endpoints:
        endpoints[group].sort()

    return {
        "message": "Welcome to Streaming API",
        "version": "1.0.0",
        "endpoints": endpoints
    }

# --- GitLab Project Catalog Endpoint ---
@app.get("/api/gitlab/projects")
def list_gitlab_projects(search: str = "", page: int = 1):
    """List GitLab projects the server token can access (repo-catalog feature).

    Uses server-side GITLAB_URL / GITLAB_TOKEN. When `search` is given, scans pages
    and fuzzy-matches path/name/description (GitLab's own search only covers name/path).
    """
    import os
    import requests
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    base = (os.environ.get("GITLAB_URL") or "https://gitlab.com").rstrip("/")
    token = os.environ.get("GITLAB_TOKEN", "")
    if not token:
        return {"projects": [], "nextPage": None, "error": "Server GITLAB_TOKEN not configured"}

    api = f"{base}/api/v4/projects"
    headers = {"PRIVATE-TOKEN": token}

    def fetch_page(p: int, per_page: int):
        url = (f"{api}?membership=true&simple=true&order_by=last_activity_at"
               f"&per_page={per_page}&page={p}")
        r = requests.get(url, headers=headers, verify=False, timeout=20)
        r.raise_for_status()
        nxt = r.headers.get("X-Next-Page")
        return r.json(), (int(nxt) if nxt else None)

    def to_item(pr: dict):
        return {
            "pathWithNamespace": pr.get("path_with_namespace"),
            "name": pr.get("name"),
            "description": pr.get("description"),
            "defaultBranch": pr.get("default_branch"),
            "starCount": pr.get("star_count", 0),
            "webUrl": pr.get("web_url"),
        }

    try:
        if not search:
            data, nxt = fetch_page(max(1, page), 30)
            return {"projects": [to_item(x) for x in data], "nextPage": nxt}
        scanned = []
        p = 1
        while p and len(scanned) < 600:
            batch, nxt = fetch_page(p, 100)
            scanned.extend(batch)
            p = nxt
        q = search.lower()
        matched = [to_item(x) for x in scanned
                   if q in (x.get("path_with_namespace") or "").lower()
                   or q in (x.get("name") or "").lower()
                   or q in (x.get("description") or "").lower()]
        return {"projects": matched, "nextPage": None}
    except Exception as e:
        logger.error(f"Failed to list GitLab projects: {e}")
        return {"projects": [], "nextPage": None, "error": str(e)}


# --- GitLab File Tree Endpoint (server-side, avoids browser http/https/CORS issues) ---
@app.get("/api/gitlab/file_tree")
def gitlab_file_tree(repo_url: str, token: str = ""):
    """Return the file tree (+ README, default branch) of a GitLab repo, fetched
    server-side. The frontend calls this instead of hitting the GitLab API from the
    browser (which breaks on self-hosted http/https + redirects). Falls back to the
    server GITLAB_TOKEN/GITLAB_URL when not provided.
    """
    import os
    import requests
    import urllib3
    from urllib.parse import urlparse, quote

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    tok = token or os.environ.get("GITLAB_TOKEN", "")
    headers = {"PRIVATE-TOKEN": tok} if tok else {}

    parsed = urlparse(repo_url)
    if parsed.netloc:
        base = f"https://{parsed.netloc}"          # force https for reliability
        project_path = parsed.path.strip("/").replace(".git", "")
    else:
        base = (os.environ.get("GITLAB_URL") or "https://gitlab.com").rstrip("/")
        project_path = repo_url.strip("/").replace(".git", "")
    encoded = quote(project_path, safe="")
    api = f"{base}/api/v4/projects/{encoded}"

    try:
        default_branch = "main"
        info = requests.get(api, headers=headers, verify=False, timeout=20)
        if info.status_code == 200:
            default_branch = info.json().get("default_branch") or "main"
        elif info.status_code in (401, 403, 404):
            return {"error": f"GitLab project info error: HTTP {info.status_code}",
                    "file_tree": "", "default_branch": "main", "readme": ""}

        paths = []
        page = 1
        while True:
            r = requests.get(
                f"{api}/repository/tree?recursive=true&per_page=100&page={page}",
                headers=headers, verify=False, timeout=30)
            r.raise_for_status()
            for it in r.json():
                if it.get("type") == "blob" and it.get("path"):
                    paths.append(it["path"])
            nxt = r.headers.get("X-Next-Page")
            if nxt:
                page = int(nxt)
            else:
                break
            if page > 1000:
                break

        readme = ""
        try:
            rr = requests.get(
                f"{api}/repository/files/README.md/raw?ref={quote(default_branch, safe='')}",
                headers=headers, verify=False, timeout=20)
            if rr.status_code == 200:
                readme = rr.text
        except Exception:
            pass

        return {"file_tree": "\n".join(paths), "default_branch": default_branch, "readme": readme}
    except Exception as e:
        logger.error(f"Failed to fetch GitLab file tree: {e}")
        return {"error": str(e), "file_tree": "", "default_branch": "main", "readme": ""}


# --- Processed Projects Endpoint --- (New Endpoint)
@app.get("/api/processed_projects", response_model=List[ProcessedProjectEntry])
async def get_processed_projects():
    """
    Lists all processed projects found in the wiki cache directory.
    Projects are identified by files named like: deepwiki_cache_{repo_type}_{owner}_{repo}_{language}.json
    """
    project_entries: List[ProcessedProjectEntry] = []
    # WIKI_CACHE_DIR is already defined globally in the file

    try:
        if not os.path.exists(WIKI_CACHE_DIR):
            logger.info(f"Cache directory {WIKI_CACHE_DIR} not found. Returning empty list.")
            return []

        logger.info(f"Scanning for project cache files in: {WIKI_CACHE_DIR}")
        filenames = await asyncio.to_thread(os.listdir, WIKI_CACHE_DIR) # Use asyncio.to_thread for os.listdir

        for filename in filenames:
            if filename.startswith("deepwiki_cache_") and filename.endswith(".json"):
                file_path = os.path.join(WIKI_CACHE_DIR, filename)
                try:
                    stats = await asyncio.to_thread(os.stat, file_path) # Use asyncio.to_thread for os.stat
                    parts = filename.replace("deepwiki_cache_", "").replace(".json", "").split('_')

                    # Expecting repo_type_owner_repo_language
                    # Example: deepwiki_cache_github_AsyncFuncAI_deepwiki-open_en.json
                    # parts = [github, AsyncFuncAI, deepwiki-open, en]
                    if len(parts) >= 4:
                        repo_type = parts[0]
                        owner = parts[1]
                        language = parts[-1] # language is the last part
                        repo = "_".join(parts[2:-1]) # repo can contain underscores

                        # Read the real repo URL from the cache file. owner/repo above
                        # may be a flattened nested-group path (underscores), so the
                        # frontend uses this to build correct source links.
                        def _read_repo_url(p):
                            with open(p, 'r', encoding='utf-8') as f:
                                data = json.load(f)
                            return data.get('repo_url') or (data.get('repo') or {}).get('repoUrl')
                        try:
                            repo_url = await asyncio.to_thread(_read_repo_url, file_path)
                        except Exception:
                            repo_url = None

                        project_entries.append(
                            ProcessedProjectEntry(
                                id=filename,
                                owner=owner,
                                repo=repo,
                                name=f"{owner}/{repo}",
                                repo_type=repo_type,
                                submittedAt=int(stats.st_mtime * 1000), # Convert to milliseconds
                                language=language,
                                repo_url=repo_url
                            )
                        )
                    else:
                        logger.warning(f"Could not parse project details from filename: {filename}")
                except Exception as e:
                    logger.error(f"Error processing file {file_path}: {e}")
                    continue # Skip this file on error

        # Sort by most recent first
        project_entries.sort(key=lambda p: p.submittedAt, reverse=True)
        logger.info(f"Found {len(project_entries)} processed project entries.")
        return project_entries

    except Exception as e:
        logger.error(f"Error listing processed projects from {WIKI_CACHE_DIR}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list processed projects from server cache.")
