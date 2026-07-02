"""Wiki generation background-job system.

Implements the task system from docs/wiki-jobs-api.md: an in-memory job store +
manager that runs wiki generation as background asyncio tasks, with a global
concurrency semaphore, per-key dedup, cancellation, and a TTL cleanup of
finished jobs.

The *generation* itself is pluggable via a `runner` coroutine so the state
machine can be developed/tested independently of the real (ported) pipeline.
`make_fake_runner()` walks every phase with sleeps — that's what step 1 wires in.
The real runner (porting useWikiData orchestration → Python) drops in later
without touching this file's state machine.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, List, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# --- Status / phase vocabularies (see docs §3, §4) ---------------------------

ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"succeeded", "partial", "failed", "canceled"}

# phase -> (percent_start, percent_end). generating interpolates within its band
# by done_pages/total_pages; other phases use the band start (coarse climb).
PHASE_BANDS = {
    "fetching_repo": (0, 5),
    "indexing": (5, 25),
    "planning": (25, 35),
    "generating": (35, 95),
    "saving": (95, 100),
}


class JobCanceled(Exception):
    """Raised internally when a job is canceled cooperatively."""


class JobFailed(Exception):
    """Raised by a runner to fail a job with a specific error code (see docs §5)."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


# --- Request model (POST /api/wiki/generate body, see docs §2.1) -------------

class GenerateRequest(BaseModel):
    repo_url: str = ""
    repo_type: str = "github"
    owner: str
    repo: str
    language: str = "zh"  # cache-identity plumbing only — generated content is always Chinese
    comprehensive: bool = True
    provider: str = ""
    model: str = ""
    is_custom_model: bool = False
    custom_model: str = ""
    token: str = ""
    excluded_dirs: str = ""
    excluded_files: str = ""
    included_dirs: str = ""
    included_files: str = ""
    max_pages: int = 40  # upper bound on total pages in comprehensive mode
    plan_mode: str = "auto"  # "single" | "two_phase" | "auto" (auto: comprehensive => two_phase)
    max_modules: int = 40  # two-phase: upper bound on discovered modules
    max_pages_per_module: int = 3  # two-phase: upper bound on pages per module
    mode: str = "full"  # "full" | "incremental" (incremental: diff old commit -> regen affected pages)
    force: bool = False
    # Guaranteed foundational pages (overview, getting-started, architecture, deployment,
    # structure, configuration, glossary). "" = default set; "none"/"off" = disable;
    # else a comma list of ids/short-names. See wiki_generator.build_scaffold.
    foundational: str = ""


@dataclass(frozen=True)
class JobKey:
    """Job identity. Equals the wiki cache key + comprehensive (dedup granularity)."""

    repo_type: str
    owner: str
    repo: str
    language: str
    comprehensive: bool

    def canonical(self) -> str:
        return f"{self.repo_type}:{self.owner}:{self.repo}:{self.language}:{int(self.comprehensive)}"


def job_key(req: GenerateRequest) -> JobKey:
    return JobKey(req.repo_type, req.owner, req.repo, req.language, bool(req.comprehensive))


# --- Internal job state ------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Job:
    id: str
    key: JobKey
    repo_url: str
    provider: str
    model: str
    is_custom: bool
    force: bool

    status: str = "queued"
    phase: Optional[str] = None

    total_pages: Optional[int] = None
    done_pages: int = 0
    failed_pages: int = 0
    current_page: Optional[str] = None

    created_at: datetime = field(default_factory=_now)
    started_at: Optional[datetime] = None
    updated_at: datetime = field(default_factory=_now)
    finished_at: Optional[datetime] = None

    percent: int = 0
    eta_seconds: Optional[int] = None
    queue_position: Optional[int] = None
    cache_ready: bool = False
    error: Optional[Dict[str, str]] = None

    # bookkeeping (not serialized)
    seq: int = 0
    generating_started_at: Optional[datetime] = field(default=None, repr=False)

    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    def view(self) -> dict:
        """API-facing JSON (docs §1)."""
        def iso(dt: Optional[datetime]) -> Optional[str]:
            return dt.isoformat() if dt else None

        ref = self.started_at or self.created_at
        elapsed = int(((self.finished_at or _now()) - ref).total_seconds())
        return {
            "id": self.id,
            "key": {
                "owner": self.key.owner,
                "repo": self.key.repo,
                "repo_type": self.key.repo_type,
                "language": self.key.language,
                "comprehensive": self.key.comprehensive,
            },
            "repo_url": self.repo_url,
            "status": self.status,
            "phase": self.phase,
            "progress": {
                "percent": self.percent,
                "total_pages": self.total_pages,
                "done_pages": self.done_pages,
                "failed_pages": self.failed_pages,
                "current_page": self.current_page,
            },
            "timing": {
                "created_at": iso(self.created_at),
                "started_at": iso(self.started_at),
                "updated_at": iso(self.updated_at),
                "finished_at": iso(self.finished_at),
                "elapsed_seconds": max(0, elapsed),
                "eta_seconds": self.eta_seconds,
            },
            "queue_position": self.queue_position,
            "model": {"provider": self.provider, "model": self.model, "is_custom": self.is_custom},
            "cache_ready": self.cache_ready,
            "error": self.error,
        }


# --- Runner context ----------------------------------------------------------

class JobContext:
    """Handed to a runner so it can report progress without knowing the store."""

    def __init__(self, manager: "JobManager", job: Job, req: GenerateRequest):
        self._m = manager
        self.job = job
        self.req = req

    async def set_phase(self, phase: str) -> None:
        self.job.phase = phase
        if phase == "generating" and self.job.generating_started_at is None:
            self.job.generating_started_at = _now()
        self._m._touch(self.job)

    def set_total_pages(self, n: int) -> None:
        self.job.total_pages = n
        self._m._touch(self.job)

    def set_current_page(self, title: Optional[str]) -> None:
        self.job.current_page = title
        self._m._touch(self.job)

    def page_done(self, failed: bool = False) -> None:
        if failed:
            self.job.failed_pages += 1
        self.job.done_pages += 1
        self._m._touch(self.job)

    async def sleep(self, seconds: float) -> None:
        # Cancellation-aware: cancel() cancels the task → CancelledError here.
        await asyncio.sleep(seconds)


Runner = Callable[[Job, JobContext, GenerateRequest], Awaitable[None]]


# --- Manager -----------------------------------------------------------------

class JobManager:
    def __init__(
        self,
        *,
        max_concurrent: int = 3,
        cache_exists: Optional[Callable[[JobKey], bool]] = None,
        runner: Optional[Runner] = None,
        finished_ttl_seconds: int = 600,
        page_retries: int = 1,
    ):
        self._jobs: Dict[str, Job] = {}
        self._key_index: Dict[str, str] = {}  # key.canonical() -> job_id
        self._tasks: Dict[str, asyncio.Task] = {}
        self._sem = asyncio.Semaphore(max_concurrent)
        self.max_concurrent = max_concurrent
        self._cache_exists = cache_exists or (lambda key: False)
        self._runner = runner or make_fake_runner()
        self._ttl = finished_ttl_seconds
        self.page_retries = page_retries
        self._seq = 0

    # ---- public API ----

    async def submit(self, req: GenerateRequest) -> tuple[Job, bool]:
        """Returns (job, created). created=False when joining/cache-hit."""
        self._gc()
        key = job_key(req)
        kstr = key.canonical()

        # dedup: an active job for this key
        existing = self._jobs.get(self._key_index.get(kstr, ""))
        if existing and existing.is_active() and not req.force:
            return existing, False

        # already cached -> synthetic succeeded job. Skipped for force (regenerate)
        # and incremental (which REQUIRES the existing cache and updates it in place).
        if not req.force and req.mode != "incremental" and self._cache_exists(key):
            return self._synthetic_cached(req, key), False

        # force: cancel any active job for this key first
        if req.force and existing and existing.is_active():
            await self.cancel(existing.id)

        self._seq += 1
        job = Job(
            id=f"job_{uuid.uuid4().hex[:12]}",
            key=key,
            repo_url=req.repo_url,
            provider=req.provider,
            model=req.model,
            is_custom=req.is_custom_model,
            force=req.force,
            seq=self._seq,
        )
        self._jobs[job.id] = job
        self._key_index[kstr] = job.id
        self._touch(job)
        self._tasks[job.id] = asyncio.create_task(self._run(job, req))
        return job, True

    def get(self, job_id: str) -> Optional[Job]:
        self._gc()
        self._refresh_queue_positions()
        return self._jobs.get(job_id)

    def list_view(
        self,
        *,
        status: Optional[str] = None,
        owner: Optional[str] = None,
        repo: Optional[str] = None,
        limit: int = 100,
    ) -> dict:
        self._gc()
        self._refresh_queue_positions()
        wanted = set(s.strip() for s in status.split(",")) if status else None
        jobs = list(self._jobs.values())
        if wanted:
            jobs = [j for j in jobs if j.status in wanted]
        if owner:
            jobs = [j for j in jobs if j.key.owner == owner]
        if repo:
            jobs = [j for j in jobs if j.key.repo == repo]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        active = sum(1 for j in self._jobs.values() if j.is_active())
        return {
            "jobs": [j.view() for j in jobs[: max(0, limit)]],
            "active": active,
            "capacity": self.max_concurrent,
        }

    async def cancel(self, job_id: str) -> Optional[Job]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        if job.status in TERMINAL_STATUSES:
            return job
        task = self._tasks.get(job_id)
        if task and not task.done():
            task.cancel()
        # Reflect immediately; _run's finalizer is idempotent.
        self._finalize(job, "canceled", error={"code": "canceled", "message": "Job canceled"})
        return job

    # ---- internals ----

    def _synthetic_cached(self, req: GenerateRequest, key: JobKey) -> Job:
        self._seq += 1
        job = Job(
            id=f"job_{uuid.uuid4().hex[:12]}",
            key=key,
            repo_url=req.repo_url,
            provider=req.provider,
            model=req.model,
            is_custom=req.is_custom_model,
            force=False,
            seq=self._seq,
            status="succeeded",
            phase=None,
            percent=100,
            cache_ready=True,
            started_at=_now(),
            finished_at=_now(),
        )
        # Not stored / not indexed: it's a stateless "already done" answer.
        return job

    async def _run(self, job: Job, req: GenerateRequest) -> None:
        try:
            # queued until a concurrency slot is free
            async with self._sem:
                if job.status in TERMINAL_STATUSES:  # canceled while queued
                    return
                job.status = "running"
                job.started_at = _now()
                job.queue_position = None
                self._touch(job)

                ctx = JobContext(self, job, req)
                await self._runner(job, ctx, req)

                # success / partial
                job.cache_ready = True
                status = "partial" if job.failed_pages > 0 else "succeeded"
                self._finalize(job, status)
        except (asyncio.CancelledError, JobCanceled):
            self._finalize(job, "canceled", error={"code": "canceled", "message": "Job canceled"})
            # Swallow: cancellation is an expected terminal path, not an error.
        except JobFailed as e:
            self._finalize(job, "failed", error={"code": e.code, "message": e.message})
        except Exception as e:  # noqa: BLE001
            logger.exception("Wiki job %s crashed", job.id)
            self._finalize(job, "failed", error={"code": "internal_error", "message": str(e)})
        finally:
            self._tasks.pop(job.id, None)

    def _finalize(self, job: Job, status: str, error: Optional[Dict[str, str]] = None) -> None:
        if job.status in TERMINAL_STATUSES:
            return  # already finalized (idempotent for the cancel race)
        job.status = status
        job.phase = None
        job.current_page = None
        job.finished_at = _now()
        job.queue_position = None
        if error:
            job.error = error
        if status in ("succeeded", "partial"):
            job.percent = 100
        self._touch(job)

    def _touch(self, job: Job) -> None:
        job.updated_at = _now()
        job.percent = self._compute_percent(job)
        job.eta_seconds = self._compute_eta(job)

    def _refresh_queue_positions(self) -> None:
        """Queue position is a read-time projection: rank among *currently* queued
        jobs by submit order. Recomputed on every read so it shrinks as jobs ahead
        start running."""
        queued = sorted(
            (j for j in self._jobs.values() if j.status == "queued"), key=lambda j: j.seq
        )
        for i, j in enumerate(queued):
            j.queue_position = i + 1
        for j in self._jobs.values():
            if j.status != "queued":
                j.queue_position = None

    @staticmethod
    def _compute_percent(job: Job) -> int:
        if job.status in ("succeeded", "partial"):
            return 100
        if job.status in ("failed", "canceled"):
            return job.percent  # freeze where it stopped
        if not job.phase:
            return 0
        start, end = PHASE_BANDS.get(job.phase, (0, 0))
        if job.phase == "generating" and job.total_pages:
            frac = min(1.0, job.done_pages / job.total_pages)
            return int(start + (end - start) * frac)
        return int(start)

    @staticmethod
    def _compute_eta(job: Job) -> Optional[int]:
        if (
            job.phase == "generating"
            and job.total_pages
            and job.done_pages > 0
            and job.generating_started_at
        ):
            elapsed = (_now() - job.generating_started_at).total_seconds()
            avg = elapsed / job.done_pages
            remaining = max(0, job.total_pages - job.done_pages)
            return int(round(remaining * avg))
        return None

    def _gc(self) -> None:
        """Drop finished jobs past the TTL."""
        now = _now()
        for jid in list(self._jobs.keys()):
            job = self._jobs[jid]
            if job.status in TERMINAL_STATUSES and job.finished_at:
                if (now - job.finished_at).total_seconds() > self._ttl:
                    self._jobs.pop(jid, None)
                    if self._key_index.get(job.key.canonical()) == jid:
                        self._key_index.pop(job.key.canonical(), None)


# --- Fake runner (step 1: exercise the full state machine) -------------------

def make_fake_runner(
    *, fetch: float = 1.0, index: float = 2.0, plan: float = 1.0,
    per_page: float = 1.2, save: float = 0.6, pages: int = 6,
) -> Runner:
    """A stand-in generation pipeline that walks every phase with sleeps.

    Lets us verify queued→running→phases→succeeded, concurrency queueing,
    cancellation, dedup and ETA before the real pipeline is ported.
    """

    async def runner(job: Job, ctx: JobContext, req: GenerateRequest) -> None:
        await ctx.set_phase("fetching_repo")
        await ctx.sleep(fetch)
        await ctx.set_phase("indexing")
        await ctx.sleep(index)
        await ctx.set_phase("planning")
        await ctx.sleep(plan)
        ctx.set_total_pages(pages)
        await ctx.set_phase("generating")
        for i in range(pages):
            ctx.set_current_page(f"示例页面 {i + 1}")
            await ctx.sleep(per_page)
            ctx.page_done()
        ctx.set_current_page(None)
        await ctx.set_phase("saving")
        await ctx.sleep(save)

    return runner
