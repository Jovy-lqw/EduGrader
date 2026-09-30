from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import initialize_database
from .runtime_config import (
    RuntimeConfigPublic,
    RuntimeConfigUpdate,
    runtime_config_store,
)
from .schemas import (
    ApiMessage,
    ConflictOverwriteUpdate,
    Course,
    Homework,
    HumanDecisionUpdate,
    JobCreate,
    JobView,
    Rubric,
    RubricFileParseResponse,
    RubricNormalizeRequest,
    SessionStatus,
    SubmissionView,
)
from .services.adapters import AdapterError, get_adapter
from .services.browser_session import BrowserSessionError, browser_session
from .services.jobs import JobError, job_service
from .services.llm import LlmError, llm_client
from .services.rubric_files import RubricFileError, rubric_file_parser


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    job_service.recover_interrupted_jobs()
    job_service.migrate_legacy_model_reviews()
    yield
    await browser_session.close()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@app.get("/api/config", response_model=RuntimeConfigPublic)
async def get_config() -> RuntimeConfigPublic:
    return runtime_config_store.public()


@app.put("/api/config", response_model=RuntimeConfigPublic)
async def update_config(update: RuntimeConfigUpdate) -> RuntimeConfigPublic:
    return runtime_config_store.save(update)


@app.post("/api/session/open-login", response_model=ApiMessage)
async def open_login() -> ApiMessage:
    try:
        await get_adapter().open_login()
    except BrowserSessionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ApiMessage(message="已打开智慧树官方登录页")


@app.get("/api/session/status", response_model=SessionStatus)
async def session_status() -> SessionStatus:
    try:
        return await get_adapter().session_status()
    except AdapterError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/courses", response_model=list[Course])
async def list_courses() -> list[Course]:
    try:
        return await get_adapter().list_courses()
    except AdapterError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/courses/{course_id}/homeworks", response_model=list[Homework])
async def list_homeworks(course_id: str) -> list[Homework]:
    try:
        return await get_adapter().list_homeworks(course_id)
    except AdapterError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/api/courses/{course_id}/homeworks/{homework_id}",
    response_model=Homework,
)
async def get_homework(course_id: str, homework_id: str) -> Homework:
    try:
        return await get_adapter().get_homework(course_id, homework_id)
    except AdapterError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/rubrics/normalize", response_model=Rubric)
async def normalize_rubric(request: RubricNormalizeRequest) -> Rubric:
    try:
        return await llm_client.normalize_rubric(request)
    except LlmError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/rubrics/parse-file", response_model=RubricFileParseResponse)
async def parse_rubric_file(
    file: Annotated[UploadFile, File()],
) -> RubricFileParseResponse:
    config = runtime_config_store.load()
    max_file_bytes = config.max_pdf_megabytes * 1024 * 1024
    try:
        body = await file.read(max_file_bytes + 1)
        parsed = await rubric_file_parser.parse(
            file.filename or "",
            body,
            max_file_bytes=max_file_bytes,
            max_characters=config.max_model_characters,
        )
    except RubricFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()
    return RubricFileParseResponse(
        filename=parsed.filename,
        file_type=parsed.file_type,
        text=parsed.text,
        characters=len(parsed.text),
    )


@app.get("/api/jobs", response_model=list[JobView])
async def list_jobs() -> list[JobView]:
    return job_service.list()


@app.post("/api/jobs", response_model=JobView)
async def create_job(request: JobCreate) -> JobView:
    try:
        return job_service.create(request)
    except JobError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}", response_model=JobView)
async def get_job(job_id: str) -> JobView:
    try:
        return job_service.get(job_id)
    except JobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/jobs/{job_id}/start", response_model=JobView)
async def start_job(job_id: str) -> JobView:
    try:
        return await job_service.start(job_id)
    except JobError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/jobs/{job_id}/pause", response_model=JobView)
async def pause_job(job_id: str) -> JobView:
    try:
        return job_service.request_pause(job_id)
    except JobError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.put("/api/jobs/{job_id}/conflict-overwrite", response_model=JobView)
async def update_conflict_overwrite(
    job_id: str,
    update: ConflictOverwriteUpdate,
) -> JobView:
    try:
        return job_service.set_conflict_overwrite(job_id, update.enabled)
    except JobError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/api/submissions/{submission_id}/manual-review",
    response_model=SubmissionView,
)
async def begin_manual_review(submission_id: str) -> SubmissionView:
    try:
        return await job_service.begin_manual_review(
            submission_id,
            get_adapter(),
        )
    except (JobError, AdapterError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/api/submissions/{submission_id}/approve",
    response_model=SubmissionView,
)
async def approve_submission(
    submission_id: str, update: HumanDecisionUpdate
) -> SubmissionView:
    try:
        return await job_service.approve(submission_id, update)
    except (JobError, AdapterError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get(
    "/api/submissions/{submission_id}/report",
)
async def get_submission_report(submission_id: str) -> Response:
    try:
        body, filename = await job_service.get_report_pdf(
            submission_id,
            get_adapter(),
        )
    except JobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AdapterError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(
        content=body,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f"inline; filename=\"report.pdf\"; filename*=UTF-8''{quote(filename)}"
            ),
            "Cache-Control": "private, no-store",
        },
    )


@app.post(
    "/api/submissions/{submission_id}/reject",
    response_model=SubmissionView,
)
async def reject_submission(submission_id: str) -> SubmissionView:
    try:
        return job_service.reject(submission_id)
    except JobError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


if settings.frontend_dist_dir.exists():
    assets_dir = settings.frontend_dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def frontend(full_path: str):
        dist_root = settings.frontend_dist_dir.resolve()
        requested = (dist_root / full_path).resolve()
        if (
            full_path
            and requested.is_file()
            and requested.is_relative_to(dist_root)
        ):
            return FileResponse(requested)
        return FileResponse(dist_root / "index.html")
