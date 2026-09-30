from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any, Optional
from zipfile import BadZipFile, ZipFile

from sqlalchemy import func, select

from ..database import session_scope
from ..models import AuditEvent, GradingJob, Submission
from ..runtime_config import runtime_config_store
from ..schemas import (
    GradeDecision,
    HumanDecisionUpdate,
    JobCreate,
    JobScope,
    JobView,
    Rubric,
    SubmissionView,
)
from .adapters import (
    AdapterError,
    AuthenticationRequired,
    PlatformAdapter,
    PostWriteVerificationError,
    RemoteSafetyError,
    get_adapter,
)
from .llm import GradeValidationError, LlmError, grade_validator, llm_client
from .pdf_processing import PdfProcessingError, pdf_processor


class JobError(RuntimeError):
    pass


ACTIVE_JOB_STATUSES = {"preparing", "running", "stopping"}
COMPLETED_SUBMISSION_STATUSES = {"written", "dry_run_complete"}
TERMINAL_SUBMISSION_STATUSES = {
    *COMPLETED_SUBMISSION_STATUSES,
    "skipped",
    "failed",
    "conflict",
    "rejected",
}

RECOVERABLE_SKIP_PREFIXES = (
    "大模型未返回有效 JSON",
    "大模型请求失败",
    "大模型请求超时",
    "大模型返回 HTTP",
    "大模型响应缺少",
    "大模型响应内容不是文本",
    "大模型返回值不是 JSON 对象",
    "大模型评分结构无效",
    "模型未返回评分置信度",
    "模型要求复核：模型未返回评分置信度",
    "模型标记为需复核，默认自动模式下已跳过",
    "大模型标记需复核但未说明原因",
    "模型返回未知评分项",
    "模型重复返回评分项",
    "模型缺少评分项",
    "模型未生成评语",
    "文档提取文本超过模型上下文限制",
    "PDF 提取文本超过模型上下文限制",
)

OVERWRITABLE_CONFLICT_PREFIXES = (
    "远端成绩与原任务记录不一致",
    "远端成绩已变化",
)
CONFLICT_OVERWRITE_PENDING_MESSAGE = "已允许覆盖冲突成绩，等待继续处理"


class JobService:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._task_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    def create(self, request: JobCreate) -> JobView:
        if request.write_enabled and request.rubric.total_score <= 0:
            raise JobError("评分总分必须大于 0")
        with session_scope() as db:
            source_job: Optional[GradingJob] = None
            rerun_from_job_id = request.scope.rerun_from_job_id
            if request.scope.overwrite_existing_scores and not rerun_from_job_id:
                raise JobError("覆盖已有成绩必须从历史任务发起")
            if rerun_from_job_id:
                source_job = db.get(GradingJob, rerun_from_job_id)
                if not source_job:
                    raise JobError("原批阅任务不存在")
                if source_job.status in ACTIVE_JOB_STATUSES:
                    raise JobError("原批阅任务仍在运行，不能发起重新批阅")
                if (
                    source_job.course_id != request.course_id
                    or source_job.homework_id != request.homework_id
                ):
                    raise JobError("重新批阅必须使用原任务的课程和作业")
                source_student_ids = {
                    submission.student_id for submission in source_job.submissions
                }
                selected_student_ids = set(request.scope.student_ids)
                if request.scope.status != "all" or not selected_student_ids:
                    raise JobError("重新批阅必须限定为原任务中的学生")
                if not selected_student_ids.issubset(source_student_ids):
                    raise JobError("重新批阅范围包含原任务之外的学生")
            job = GradingJob(
                course_id=request.course_id,
                course_name=request.course_name,
                homework_id=request.homework_id,
                homework_title=request.homework_title,
                rubric_json=_json_dump(request.rubric.model_dump(mode="json")),
                scope_json=_json_dump(request.scope.model_dump(mode="json")),
                require_human_confirmation=request.require_human_confirmation,
                write_enabled=request.write_enabled,
                publish_after_write=False,
            )
            db.add(job)
            db.flush()
            self._add_audit(
                db,
                job.id,
                None,
                "job_created",
                "批阅任务已创建",
                {
                    "write_enabled": request.write_enabled,
                    "require_human_confirmation": request.require_human_confirmation,
                    "publish_after_write": False,
                },
            )
            if source_job:
                self._add_audit(
                    db,
                    job.id,
                    None,
                    "rerun_job_created",
                    "已从历史任务创建重新批阅任务",
                    {
                        "source_job_id": source_job.id,
                        "student_count": len(request.scope.student_ids),
                        "overwrite_existing_scores": (
                            request.scope.overwrite_existing_scores
                        ),
                    },
                )
                self._add_audit(
                    db,
                    source_job.id,
                    None,
                    "replacement_job_created",
                    "已创建新的重新批阅任务",
                    {"replacement_job_id": job.id},
                )
            return _job_view(job, include_submissions=True)

    def recover_interrupted_jobs(self) -> None:
        with session_scope() as db:
            jobs = db.scalars(
                select(GradingJob).where(
                    GradingJob.status.in_(ACTIVE_JOB_STATUSES)
                )
            ).all()
            for job in jobs:
                recovered = 0
                for submission in job.submissions:
                    if submission.status in {"fetching", "parsing", "grading"}:
                        submission.status = "pending"
                        submission.status_message = "服务已重启，等待继续处理"
                        recovered += 1
                    elif submission.status == "writing":
                        submission.status = "conflict"
                        submission.status_message = (
                            "服务在写入期间重启，请先核对智慧树远端成绩"
                        )
                job.status = "paused"
                job.stop_requested = True
                job.error_message = ""
                statuses = [submission.status for submission in job.submissions]
                job.completed_count = sum(
                    status in {"written", "dry_run_complete"}
                    for status in statuses
                )
                job.skipped_count = sum(
                    status in {"skipped", "conflict", "rejected"}
                    for status in statuses
                )
                job.failed_count = sum(
                    status == "failed" for status in statuses
                )
                self._add_audit(
                    db,
                    job.id,
                    None,
                    "job_recovered_after_restart",
                    f"服务重启后任务已暂停，恢复 {recovered} 条处理中记录",
                )

    def migrate_legacy_model_reviews(self, job_id: Optional[str] = None) -> int:
        with session_scope() as db:
            query = select(Submission).where(
                Submission.status == "skipped",
                Submission.status_message.startswith("模型要求复核："),
            )
            if job_id:
                query = query.where(Submission.job_id == job_id)
            candidates = db.scalars(query).all()
            migrated = 0
            touched_jobs: set[str] = set()
            for submission in candidates:
                grade = _json_load(submission.grade_json)
                if not grade.get("criterion_scores"):
                    continue
                submission.status = "waiting_confirmation"
                submission.status_message = submission.status_message.replace(
                    "模型要求复核：",
                    "模型建议人工复核：",
                    1,
                )
                touched_jobs.add(submission.job_id)
                migrated += 1
                self._add_audit(
                    db,
                    submission.job_id,
                    submission.id,
                    "status_waiting_confirmation",
                    submission.status_message,
                    {"status": "waiting_confirmation", "migrated": True},
                )
            for job_id in touched_jobs:
                job = db.get(GradingJob, job_id)
                if not job:
                    continue
                self._refresh_counts_record(job)
                if job.status == "completed":
                    job.status = "waiting_confirmation"
                    job.completed_at = None
            return migrated

    def list(self) -> list[JobView]:
        with session_scope() as db:
            jobs = db.scalars(
                select(GradingJob).order_by(GradingJob.created_at.desc())
            ).all()
            return [_job_view(job, include_submissions=False) for job in jobs]

    def get(self, job_id: str) -> JobView:
        with session_scope() as db:
            job = db.get(GradingJob, job_id)
            if not job:
                raise JobError("任务不存在")
            events = db.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.job_id == job_id,
                    AuditEvent.submission_id.is_not(None),
                )
                .order_by(AuditEvent.created_at)
            ).all()
            events_by_submission: dict[str, list[AuditEvent]] = defaultdict(list)
            for event in events:
                if event.submission_id:
                    events_by_submission[event.submission_id].append(event)
            return _job_view(
                job,
                include_submissions=True,
                events_by_submission=events_by_submission,
            )

    def delete(self, job_id: str) -> None:
        task = self._tasks.get(job_id)
        if task and not task.done():
            raise JobError("任务仍在运行，请先暂停后再删除")
        with session_scope() as db:
            job = db.get(GradingJob, job_id)
            if not job:
                raise JobError("任务不存在")
            if job.status in ACTIVE_JOB_STATUSES:
                raise JobError("任务仍在运行，请先暂停后再删除")
            db.delete(job)

    async def get_report_pdf(
        self,
        submission_id: str,
        adapter: PlatformAdapter,
    ) -> tuple[bytes, str]:
        with session_scope() as db:
            submission = db.get(Submission, submission_id)
            if not submission:
                raise JobError("学生批阅记录不存在")
            selected_files = _json_load(submission.pdf_files_json)
            pdf_file = next(
                (
                    item
                    for item in selected_files
                    if str(item.get("document_type") or "").lower() == "pdf"
                    or Path(str(item.get("name") or "")).suffix.lower() == ".pdf"
                ),
                None,
            )
            if not pdf_file:
                raise JobError("该记录没有可预览的原始 PDF")
            snapshot = _json_load(submission.snapshot_json)

        max_bytes = runtime_config_store.load().max_pdf_megabytes * 1024 * 1024
        archive_entry = str(pdf_file.get("archive_entry") or "")
        if archive_entry:
            archive_name = str(pdf_file.get("archive_name") or "")
            archive_file = next(
                (
                    item
                    for item in snapshot.get("files") or []
                    if str(item.get("name") or "") == archive_name
                ),
                None,
            )
            if not archive_file:
                raise JobError("原始 ZIP 附件地址已丢失")
            archive_body, _ = await adapter.download_file(
                str(archive_file.get("url") or "")
            )
            if len(archive_body) > max_bytes:
                raise JobError("原始 ZIP 附件超过大小限制")
            try:
                with ZipFile(BytesIO(archive_body)) as archive:
                    info = archive.getinfo(archive_entry)
                    if info.file_size > max_bytes:
                        raise JobError("原始 PDF 超过大小限制")
                    with archive.open(info) as source:
                        body = source.read(max_bytes + 1)
            except (BadZipFile, KeyError) as exc:
                raise JobError("无法从原始 ZIP 中读取 PDF") from exc
        else:
            body, _ = await adapter.download_file(str(pdf_file.get("url") or ""))

        if len(body) > max_bytes:
            raise JobError("原始 PDF 超过大小限制")
        if not body.startswith(b"%PDF-"):
            raise JobError("原始附件内容不是有效 PDF")
        return body, Path(str(pdf_file.get("name") or "report.pdf")).name

    async def start(self, job_id: str) -> JobView:
        async with self._task_lock:
            existing = self._tasks.get(job_id)
            if existing and not existing.done():
                return self.get(job_id)
            with session_scope() as db:
                job = db.get(GradingJob, job_id)
                if not job:
                    raise JobError("任务不存在")
                if job.status == "cancelled":
                    raise JobError("任务已结束，不能再次启动")
                requeued = self._requeue_recoverable_submissions(db, job)
                if job.status == "completed" and requeued == 0:
                    raise JobError("当前没有可恢复项可重试")
                job.stop_requested = False
                job.status = "preparing"
                job.error_message = ""
                job.started_at = job.started_at or _utc_now()
                if requeued:
                    job.completed_at = None
                    self._add_audit(
                        db,
                        job.id,
                        None,
                        "recoverable_submissions_requeued",
                        f"已将 {requeued} 条可恢复记录重新加入队列",
                    )
            self._refresh_counts(job_id)
            task = asyncio.create_task(self._run(job_id), name=f"grading-job-{job_id}")
            self._tasks[job_id] = task
        return self.get(job_id)

    def request_pause(self, job_id: str) -> JobView:
        with session_scope() as db:
            job = db.get(GradingJob, job_id)
            if not job:
                raise JobError("任务不存在")
            if job.status not in ACTIVE_JOB_STATUSES:
                raise JobError("当前任务不在运行中")
            job.stop_requested = True
            job.status = "stopping"
            self._add_audit(db, job_id, None, "pause_requested", "用户请求暂停任务")
        return self.get(job_id)

    def set_conflict_overwrite(self, job_id: str, enabled: bool) -> JobView:
        with session_scope() as db:
            job = db.get(GradingJob, job_id)
            if not job:
                raise JobError("任务不存在")
            if job.status in ACTIVE_JOB_STATUSES:
                raise JobError("任务运行中，不能修改冲突覆盖设置")
            scope = JobScope.model_validate(_json_load(job.scope_json))
            if not scope.rerun_from_job_id or not scope.overwrite_existing_scores:
                raise JobError("仅重新批阅任务可以允许冲突继续写入")
            scope.allow_conflict_overwrite = enabled
            job.scope_json = _json_dump(scope.model_dump(mode="json"))

            requeued = 0
            restored = 0
            if enabled:
                for submission in job.submissions:
                    if not _is_overwritable_conflict(submission):
                        continue
                    previous_message = submission.status_message
                    submission.status = "pending"
                    submission.status_message = CONFLICT_OVERWRITE_PENDING_MESSAGE
                    self._add_audit(
                        db,
                        job.id,
                        submission.id,
                        "conflict_overwrite_requeued",
                        submission.status_message,
                        {"previous_message": previous_message},
                    )
                    requeued += 1
                if requeued:
                    job.status = "paused"
                    job.stop_requested = True
                    job.completed_at = None
            else:
                for submission in job.submissions:
                    if (
                        submission.status != "pending"
                        or submission.status_message
                        != CONFLICT_OVERWRITE_PENDING_MESSAGE
                    ):
                        continue
                    submission.status = "conflict"
                    submission.status_message = (
                        "远端成绩与原任务记录不一致，"
                        "已关闭冲突继续写入"
                    )
                    self._add_audit(
                        db,
                        job.id,
                        submission.id,
                        "conflict_overwrite_restored",
                        submission.status_message,
                    )
                    restored += 1

            self._refresh_counts_record(job)
            self._add_audit(
                db,
                job.id,
                None,
                "conflict_overwrite_updated",
                (
                    f"已允许冲突继续写入，重新加入队列 {requeued} 条"
                    if enabled
                    else f"已关闭冲突继续写入，恢复保护 {restored} 条"
                ),
                {
                    "enabled": enabled,
                    "requeued": requeued,
                    "restored": restored,
                },
            )
        self._refresh_job_state(job_id)
        return self.get(job_id)

    async def begin_manual_review(
        self,
        submission_id: str,
        adapter: PlatformAdapter,
    ) -> SubmissionView:
        with session_scope() as db:
            submission = db.get(Submission, submission_id)
            if not submission:
                raise JobError("学生批阅记录不存在")
            job = db.get(GradingJob, submission.job_id)
            if not job:
                raise JobError("任务不存在")
            if submission.status in COMPLETED_SUBMISSION_STATUSES:
                raise JobError("该记录已完成，不能转为手工评分")
            if job.status in ACTIVE_JOB_STATUSES:
                raise JobError("任务仍在运行，请先暂停后再手工评分")
            if submission.status == "waiting_confirmation":
                return self._get_submission_view(submission_id)
            job_id = job.id
            homework_id = job.homework_id
            student_id = submission.student_id
            previous_status = submission.status
            previous_message = submission.status_message
            selected_files = _json_load(submission.pdf_files_json)
            ignored_files = _json_load(submission.ignored_files_json)
            extracted_text = submission.extracted_text
            rubric = Rubric.model_validate_json(job.rubric_json)
            grade = _json_load(submission.grade_json)

        detail = await adapter.get_submission(homework_id, student_id)
        if _is_published(detail.get("publish_state")):
            raise JobError("当前成绩已发布，不能转为手工评分")

        preparation_note = ""
        if not selected_files:
            try:
                documents = await pdf_processor.collect_and_parse(
                    adapter,
                    job_id=job_id,
                    student_id=student_id,
                    files=list(detail.get("files") or []),
                )
                selected_files = documents.selected_files
                ignored_files = documents.ignored_files
                extracted_text = documents.text
            except PdfProcessingError as exc:
                preparation_note = str(exc)

        if not _has_complete_grade(grade, rubric):
            grade = _blank_manual_grade(rubric)

        status_message = "已转为手工评分"
        if preparation_note:
            status_message += f"（{preparation_note}）"

        with session_scope() as db:
            submission = db.get(Submission, submission_id)
            job = db.get(GradingJob, job_id)
            if not submission or not job:
                raise JobError("批阅记录已不存在")
            if submission.status in COMPLETED_SUBMISSION_STATUSES:
                raise JobError("该记录已完成，不能转为手工评分")
            if job.status in ACTIVE_JOB_STATUSES:
                raise JobError("任务仍在运行，请先暂停后再手工评分")
            submission.snapshot_json = _json_dump(detail)
            submission.snapshot_hash = _submission_fingerprint(detail)
            submission.initial_remote_score = str(detail.get("score") or "")
            submission.initial_publish_state = str(
                detail.get("publish_state") or ""
            )
            submission.pdf_files_json = _json_dump(selected_files)
            submission.ignored_files_json = _json_dump(ignored_files)
            submission.extracted_text = extracted_text
            submission.grade_json = _json_dump(grade)
            submission.status = "waiting_confirmation"
            submission.status_message = status_message
            job.completed_at = None
            self._add_audit(
                db,
                job_id,
                submission.id,
                "manual_review_started",
                status_message,
                {
                    "previous_status": previous_status,
                    "previous_message": previous_message,
                },
            )
        self._refresh_job_state(job_id)
        return self._get_submission_view(submission_id)

    async def approve(
        self, submission_id: str, update: HumanDecisionUpdate
    ) -> SubmissionView:
        with session_scope() as db:
            submission = db.get(Submission, submission_id)
            if not submission:
                raise JobError("学生批阅记录不存在")
            job = db.get(GradingJob, submission.job_id)
            if not job:
                raise JobError("任务不存在")
            if submission.status != "waiting_confirmation":
                raise JobError("该记录当前不等待人工确认")
            rubric = Rubric.model_validate_json(job.rubric_json)
            if update.manual_total_score is not None:
                if not submission.status_message.startswith("已转为手工评分"):
                    raise JobError("仅手工评分记录可以直接填写总分")
                decision = _manual_total_decision(
                    update.grade,
                    rubric,
                    update.manual_total_score,
                )
            else:
                decision = grade_validator.validate_and_adjust(
                    update.grade,
                    rubric,
                    is_delay=_json_load(submission.snapshot_json).get(
                        "is_delay", False
                    ),
                    is_resubmission=bool(
                        _json_load(submission.snapshot_json).get("redo", False)
                    ),
                )
            submission.grade_json = _json_dump(decision.model_dump(mode="json"))
            submission.status = "writing" if job.write_enabled else "dry_run_complete"
            submission.status_message = (
                "人工总分确认通过"
                if update.manual_total_score is not None
                else "人工确认通过"
            )
            job_id = job.id
            write_enabled = job.write_enabled
        if write_enabled:
            try:
                await self._write_one(job_id, submission_id, get_adapter())
            except PostWriteVerificationError as exc:
                self._update_submission(
                    submission_id, status="failed", status_message=str(exc)
                )
                self._audit(
                    job_id,
                    submission_id,
                    "post_write_verification_failed",
                    str(exc),
                )
                raise
            except RemoteSafetyError as exc:
                self._update_submission(
                    submission_id, status="conflict", status_message=str(exc)
                )
                self._audit(job_id, submission_id, "write_blocked", str(exc))
                raise
            except AdapterError as exc:
                self._update_submission(
                    submission_id,
                    status="waiting_confirmation",
                    status_message=f"写入失败，可重试：{exc}",
                )
                raise
            finally:
                self._refresh_job_state(job_id)
        else:
            self._refresh_job_state(job_id)
        return self._get_submission_view(submission_id)

    def reject(self, submission_id: str) -> SubmissionView:
        with session_scope() as db:
            submission = db.get(Submission, submission_id)
            if not submission:
                raise JobError("学生批阅记录不存在")
            if submission.status != "waiting_confirmation":
                raise JobError("该记录当前不等待人工确认")
            job = db.get(GradingJob, submission.job_id)
            if not job:
                raise JobError("任务不存在")
            grade = _json_load(submission.grade_json)
            is_model_review = bool(grade.get("needs_review")) and not (
                job.require_human_confirmation
            )
            submission.status = "skipped" if is_model_review else "rejected"
            submission.status_message = (
                "人工复核后维持跳过"
                if is_model_review
                else "人工拒绝写入"
            )
            job_id = submission.job_id
            self._add_audit(
                db,
                job_id,
                submission.id,
                "review_skipped" if is_model_review else "grade_rejected",
                submission.status_message,
            )
        self._refresh_job_state(job_id)
        return self._get_submission_view(submission_id)

    async def _run(self, job_id: str) -> None:
        adapter = get_adapter()
        try:
            job_view = self.get(job_id)
            homework = await adapter.get_homework(
                job_view.course_id, job_view.homework_id
            )
            if job_view.write_enabled and homework.auto_publish is not False:
                reason = (
                    "智慧树当前作业已开启自动发布"
                    if homework.auto_publish is True
                    else "无法确认智慧树当前作业已关闭自动发布"
                )
                raise RemoteSafetyError(
                    f"{reason}。请先在网站确认关闭自动发布后重试。"
                )
            scope = job_view.scope
            students = await adapter.list_students(
                job_view.homework_id,
                class_id=str(scope.get("class_id") or ""),
                status=str(scope.get("status") or "unreviewed"),
            )
            selected_ids = set(scope.get("student_ids") or [])
            if selected_ids:
                students = [student for student in students if student.id in selected_ids]
            self._prepare_submissions(job_id, students)
            self._set_job_status(job_id, "running")

            pending_ids = self._pending_submission_ids(job_id)
            concurrency = min(
                runtime_config_store.load().llm_concurrency,
                len(pending_ids),
            )
            halt_event = asyncio.Event()
            fatal_errors: list[Exception] = []
            queue: asyncio.Queue[str] = asyncio.Queue()
            for submission_id in pending_ids:
                queue.put_nowait(submission_id)

            async def worker() -> None:
                while not halt_event.is_set() and not self._stop_requested(job_id):
                    try:
                        submission_id = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    try:
                        await self._process_one(
                            job_id,
                            submission_id,
                            adapter,
                            homework.description,
                            halt_event=halt_event,
                        )
                    except (AuthenticationRequired, PostWriteVerificationError) as exc:
                        halt_event.set()
                        fatal_errors.append(exc)
                        return
                    finally:
                        queue.task_done()

            if concurrency:
                await asyncio.gather(
                    *(worker() for _ in range(concurrency))
                )
            if fatal_errors:
                raise fatal_errors[0]
            if self._stop_requested(job_id):
                self._set_job_status(job_id, "paused")
                return

            self._refresh_job_state(job_id)
        except AuthenticationRequired as exc:
            self._set_job_status(job_id, "paused", str(exc))
            self._audit(job_id, None, "authentication_required", str(exc))
        except (AdapterError, RemoteSafetyError) as exc:
            self._set_job_status(job_id, "failed", str(exc), completed=True)
            self._audit(job_id, None, "job_blocked", str(exc))
        except Exception as exc:
            self._set_job_status(
                job_id, "failed", f"任务执行失败：{exc}", completed=True
            )
            self._audit(job_id, None, "job_failed", str(exc))
        finally:
            async with self._task_lock:
                self._tasks.pop(job_id, None)

    async def _process_one(
        self,
        job_id: str,
        submission_id: str,
        adapter: PlatformAdapter,
        homework_description: str,
        *,
        halt_event: Optional[asyncio.Event] = None,
    ) -> None:
        submission = self._submission_record(submission_id)
        try:
            self._update_submission(
                submission_id,
                status="fetching",
                status_message="正在读取学生提交",
                increment_attempt=True,
            )
            detail = await adapter.get_submission(
                submission["homework_id"], submission["student_id"]
            )
            snapshot_hash = _submission_fingerprint(detail)
            self._update_submission(
                submission_id,
                snapshot_json=_json_dump(detail),
                snapshot_hash=snapshot_hash,
                initial_remote_score=str(detail.get("score") or ""),
                initial_publish_state=str(detail.get("publish_state") or ""),
                status="parsing",
                status_message="正在解析报告附件",
            )
            if _is_published(detail.get("publish_state")):
                raise RemoteSafetyError("当前成绩已发布，自动批阅不会覆盖已发布成绩")
            job = self.get(job_id)
            if job.write_enabled:
                self._validate_existing_remote_score(
                    job_id,
                    submission["student_id"],
                    detail.get("score"),
                )

            documents = await pdf_processor.collect_and_parse(
                adapter,
                job_id=job_id,
                student_id=submission["student_id"],
                files=list(detail.get("files") or []),
            )
            self._update_submission(
                submission_id,
                pdf_files_json=_json_dump(documents.selected_files),
                ignored_files_json=_json_dump(documents.ignored_files),
                extracted_text=documents.text,
                status="grading",
                status_message=(
                    (
                        f"文档原文共 {documents.original_characters} 字，"
                        f"已压缩为 {len(documents.text)} 字，正在调用大模型评分"
                    )
                    if documents.was_truncated
                    else (
                        f"文档解析完成，共 {len(documents.text)} 字，"
                        "正在调用大模型评分"
                    )
                ),
            )
            rubric = Rubric.model_validate(self.get(job_id).rubric)
            decision = await llm_client.grade(
                rubric,
                documents.text,
                assignment_description=homework_description,
            )
            decision = grade_validator.validate_and_adjust(
                decision,
                rubric,
                is_delay=bool(detail.get("is_delay")),
                is_resubmission=bool(detail.get("redo")),
            )
            self._update_submission(
                submission_id,
                grade_json=_json_dump(decision.model_dump(mode="json")),
            )
            self._audit(
                job_id,
                submission_id,
                "grade_generated",
                f"模型评分完成，给出 {decision.final_score} 分",
                {
                    "raw_score": str(decision.raw_score),
                    "final_score": str(decision.final_score),
                    "confidence": decision.confidence,
                    "needs_review": decision.needs_review,
                    "review_reasons": decision.review_reasons,
                    "detected_stage_id": decision.detected_stage_id,
                    "detected_stage_name": decision.detected_stage_name,
                    "stage_evidence": decision.stage_evidence,
                    "detected_score_band_id": decision.detected_score_band_id,
                    "detected_score_band_name": decision.detected_score_band_name,
                    "score_band_evidence": decision.score_band_evidence,
                },
            )
            if decision.needs_review:
                review_reason = "；".join(decision.review_reasons)
                self._update_submission(
                    submission_id,
                    status="waiting_confirmation",
                    status_message=(
                        f"模型建议人工复核：{review_reason}"
                        if review_reason
                        else "模型建议人工复核"
                    ),
                )
            elif job.require_human_confirmation:
                self._update_submission(
                    submission_id,
                    status="waiting_confirmation",
                    status_message="等待人工确认",
                )
            elif not job.write_enabled:
                self._update_submission(
                    submission_id,
                    status="dry_run_complete",
                    status_message="评分完成，试运行未写入",
                )
            else:
                async with self._write_lock:
                    if (
                        (halt_event and halt_event.is_set())
                        or self._stop_requested(job_id)
                    ):
                        self._update_submission(
                            submission_id,
                            status="pending",
                            status_message="批次已停止，等待继续处理",
                        )
                        return
                    await self._write_one(job_id, submission_id, adapter)
        except AuthenticationRequired as exc:
            if halt_event:
                halt_event.set()
            self._update_submission(
                submission_id,
                status="pending",
                status_message=f"{exc}，等待重新登录后继续",
            )
            raise
        except PostWriteVerificationError as exc:
            if halt_event:
                halt_event.set()
            self._update_submission(
                submission_id, status="failed", status_message=str(exc)
            )
            self._audit(job_id, submission_id, "post_write_verification_failed", str(exc))
            raise
        except RemoteSafetyError as exc:
            self._update_submission(
                submission_id, status="conflict", status_message=str(exc)
            )
            self._audit(job_id, submission_id, "write_blocked", str(exc))
        except PdfProcessingError as exc:
            self._update_submission(
                submission_id, status="skipped", status_message=str(exc)
            )
            self._audit(job_id, submission_id, "submission_skipped", str(exc))
        except (LlmError, GradeValidationError) as exc:
            self._update_submission(
                submission_id, status="failed", status_message=str(exc)
            )
            self._audit(job_id, submission_id, "submission_failed", str(exc))
        except AdapterError as exc:
            self._update_submission(
                submission_id, status="failed", status_message=str(exc)
            )
            self._audit(job_id, submission_id, "submission_failed", str(exc))
        except Exception as exc:
            self._update_submission(
                submission_id,
                status="failed",
                status_message=f"未知错误：{exc}",
            )
            self._audit(job_id, submission_id, "submission_failed", str(exc))
        finally:
            self._refresh_counts(job_id)

    async def _write_one(
        self,
        job_id: str,
        submission_id: str,
        adapter: PlatformAdapter,
    ) -> None:
        record = self._submission_record(submission_id)
        current = await adapter.get_submission(
            record["homework_id"], record["student_id"]
        )
        if _submission_fingerprint(current) != record["snapshot_hash"]:
            raise RemoteSafetyError("提交内容或重交状态已变化，已阻止写入")
        scope = self.get(job_id).scope
        if (
            str(current.get("score") or "") != record["initial_remote_score"]
            and not scope.get("allow_conflict_overwrite")
        ):
            raise RemoteSafetyError("远端成绩已变化，已阻止覆盖")
        if _is_published(current.get("publish_state")):
            raise RemoteSafetyError("远端成绩已发布，已阻止覆盖")
        self._validate_existing_remote_score(
            job_id,
            record["student_id"],
            current.get("score"),
        )

        decision = GradeDecision.model_validate(_json_load(record["grade_json"]))
        rubric = Rubric.model_validate(self.get(job_id).rubric)
        score_attributes: dict[str, Decimal] = {}
        platform_ids = [
            criterion.platform_score_attr_id
            for criterion in rubric.criteria
            if criterion.platform_score_attr_id
        ]
        if platform_ids and len(platform_ids) != len(rubric.criteria):
            raise RemoteSafetyError("平台分项评分映射不完整，已阻止写入")
        if decision.criterion_scores:
            score_by_criterion = {
                item.criterion_id: item.score for item in decision.criterion_scores
            }
            for criterion in rubric.criteria:
                if criterion.platform_score_attr_id:
                    score_attributes[criterion.platform_score_attr_id] = (
                        score_by_criterion[criterion.id]
                    )

        self._update_submission(
            submission_id, status="writing", status_message="正在写入未发布成绩"
        )
        receipt = await adapter.write_grade(
            record["homework_id"],
            record["student_id"],
            decision.final_score,
            decision.feedback,
            score_attributes,
        )
        after = await adapter.get_submission(
            record["homework_id"], record["student_id"]
        )
        if not _same_score(after.get("score"), decision.final_score):
            raise PostWriteVerificationError(
                "写入后远端分数校验不一致，任务已停止"
            )
        if _is_published(after.get("publish_state")):
            raise PostWriteVerificationError(
                "写入后成绩意外变为已发布，任务已停止，请立即检查平台设置"
            )
        self._update_submission(
            submission_id,
            status="written",
            status_message="成绩已写入并确认保持未发布",
            remote_receipt_json=_json_dump(receipt),
        )
        self._audit(
            job_id,
            submission_id,
            "grade_written",
            (
                "成绩已覆盖写入，未调用发布接口"
                if _has_score(current.get("score"))
                else "成绩已写入，未调用发布接口"
            ),
            {
                "score": str(decision.final_score),
                "previous_score": str(current.get("score") or ""),
                "overwrote_existing_score": _has_score(current.get("score")),
                "rerun_from_job_id": str(
                    self.get(job_id).scope.get("rerun_from_job_id") or ""
                ),
                "published": False,
            },
        )

    def _prepare_submissions(self, job_id: str, students: list[Any]) -> None:
        with session_scope() as db:
            job = db.get(GradingJob, job_id)
            if not job:
                raise JobError("任务不存在")
            existing = {
                item.student_id
                for item in db.scalars(
                    select(Submission).where(Submission.job_id == job_id)
                ).all()
            }
            for student in students:
                if student.id in existing:
                    continue
                submission = Submission(
                    job_id=job_id,
                    student_id=student.id,
                    student_name=student.name,
                    student_number_masked=_mask_student_number(
                        student.student_number
                    ),
                    class_name=student.class_name,
                    initial_remote_score=(
                        "" if student.score is None else str(student.score)
                    ),
                    initial_publish_state=student.publish_state,
                )
                db.add(submission)
                db.flush()
                self._add_audit(
                    db,
                    job_id,
                    submission.id,
                    "status_pending",
                    "已加入任务，等待开始处理",
                    {"status": "pending"},
                )
            job.total_count = db.scalar(
                select(func.count())
                .select_from(Submission)
                .where(Submission.job_id == job_id)
            ) or 0
            self._add_audit(
                db,
                job_id,
                None,
                "students_loaded",
                f"已加载 {len(students)} 名学生",
            )

    def _pending_submission_ids(self, job_id: str) -> list[str]:
        with session_scope() as db:
            return list(
                db.scalars(
                    select(Submission.id)
                    .where(
                        Submission.job_id == job_id,
                        Submission.status.in_(["pending", "failed"]),
                    )
                    .order_by(Submission.created_at)
                ).all()
            )

    def _requeue_recoverable_submissions(
        self,
        db: Any,
        job: GradingJob,
    ) -> int:
        candidates = db.scalars(
            select(Submission).where(
                Submission.job_id == job.id,
                Submission.status.in_(["failed", "skipped"]),
            )
        ).all()
        requeued = 0
        for submission in candidates:
            if not _is_recoverable_submission(submission):
                continue
            previous_message = submission.status_message
            submission.status = "pending"
            submission.status_message = "已加入重试队列，等待重新处理"
            submission.grade_json = "{}"
            self._add_audit(
                db,
                job.id,
                submission.id,
                "status_pending",
                submission.status_message,
                {
                    "status": "pending",
                    "previous_message": previous_message,
                },
            )
            requeued += 1
        return requeued

    def _submission_record(self, submission_id: str) -> dict[str, Any]:
        with session_scope() as db:
            submission = db.get(Submission, submission_id)
            if not submission:
                raise JobError("学生批阅记录不存在")
            job = db.get(GradingJob, submission.job_id)
            if not job:
                raise JobError("任务不存在")
            return {
                "id": submission.id,
                "job_id": job.id,
                "homework_id": job.homework_id,
                "student_id": submission.student_id,
                "snapshot_hash": submission.snapshot_hash,
                "snapshot_json": submission.snapshot_json,
                "grade_json": submission.grade_json,
                "initial_remote_score": submission.initial_remote_score,
            }

    def _validate_existing_remote_score(
        self,
        job_id: str,
        student_id: str,
        remote_score: Any,
    ) -> None:
        if not _has_score(remote_score):
            return
        scope = self.get(job_id).scope
        if not scope.get("overwrite_existing_scores"):
            raise RemoteSafetyError("远端已有未发布成绩，当前任务未授权覆盖")
        source_job_id = str(scope.get("rerun_from_job_id") or "")
        if not source_job_id:
            raise RemoteSafetyError("覆盖授权缺少原任务记录，已阻止覆盖")
        with session_scope() as db:
            source_submission = db.scalars(
                select(Submission).where(
                    Submission.job_id == source_job_id,
                    Submission.student_id == student_id,
                )
            ).first()
            if not source_submission or source_submission.status != "written":
                raise RemoteSafetyError(
                    "原任务没有该学生的已写入成绩，已阻止覆盖"
                )
            source_grade = _json_load(source_submission.grade_json)
        try:
            source_score = Decimal(str(source_grade["final_score"]))
        except (KeyError, TypeError, ValueError):
            raise RemoteSafetyError("原任务评分记录不完整，已阻止覆盖")
        if (
            not _same_score(remote_score, source_score)
            and not scope.get("allow_conflict_overwrite")
        ):
            raise RemoteSafetyError(
                "远端成绩与原任务记录不一致，可能已被人工修改，已阻止覆盖"
            )

    def _update_submission(self, submission_id: str, **values: Any) -> None:
        with session_scope() as db:
            submission = db.get(Submission, submission_id)
            if not submission:
                raise JobError("学生批阅记录不存在")
            previous_status = submission.status
            if values.pop("increment_attempt", False):
                submission.attempt_count += 1
            for key, value in values.items():
                setattr(submission, key, value)
            next_status = values.get("status")
            if next_status and next_status != previous_status:
                message = str(values.get("status_message") or next_status)
                self._add_audit(
                    db,
                    submission.job_id,
                    submission.id,
                    f"status_{next_status}",
                    message,
                    {"status": next_status},
                )

    def _stop_requested(self, job_id: str) -> bool:
        with session_scope() as db:
            job = db.get(GradingJob, job_id)
            return bool(job and job.stop_requested)

    def _set_job_status(
        self,
        job_id: str,
        status: str,
        error_message: str = "",
        *,
        completed: bool = False,
    ) -> None:
        with session_scope() as db:
            job = db.get(GradingJob, job_id)
            if not job:
                return
            job.status = status
            job.error_message = error_message
            if completed:
                job.completed_at = _utc_now()

    def _refresh_counts(self, job_id: str) -> None:
        with session_scope() as db:
            job = db.get(GradingJob, job_id)
            if not job:
                return
            self._refresh_counts_record(job)

    @staticmethod
    def _refresh_counts_record(job: GradingJob) -> None:
        statuses = [submission.status for submission in job.submissions]
        job.completed_count = sum(
            status in {"written", "dry_run_complete"} for status in statuses
        )
        job.skipped_count = sum(
            status in {"skipped", "conflict", "rejected"} for status in statuses
        )
        job.failed_count = sum(status == "failed" for status in statuses)

    def _refresh_job_state(self, job_id: str) -> None:
        self._refresh_counts(job_id)
        with session_scope() as db:
            job = db.get(GradingJob, job_id)
            if not job:
                return
            statuses = list(
                db.scalars(
                    select(Submission.status).where(Submission.job_id == job_id)
                ).all()
            )
            if any(
                status in {"pending", "fetching", "parsing", "grading", "writing"}
                for status in statuses
            ):
                job.status = "paused" if job.stop_requested else "running"
            elif any(status == "waiting_confirmation" for status in statuses):
                job.status = "waiting_confirmation"
            elif all(status in TERMINAL_SUBMISSION_STATUSES for status in statuses):
                job.status = "completed"
                job.completed_at = _utc_now()
            else:
                job.status = "running"

    def _audit(
        self,
        job_id: Optional[str],
        submission_id: Optional[str],
        event_type: str,
        message: str,
        detail: Optional[dict[str, Any]] = None,
    ) -> None:
        with session_scope() as db:
            self._add_audit(
                db, job_id, submission_id, event_type, message, detail
            )

    @staticmethod
    def _add_audit(
        db: Any,
        job_id: Optional[str],
        submission_id: Optional[str],
        event_type: str,
        message: str,
        detail: Optional[dict[str, Any]] = None,
    ) -> None:
        db.add(
            AuditEvent(
                job_id=job_id,
                submission_id=submission_id,
                event_type=event_type,
                message=message,
                detail_json=_json_dump(detail or {}),
            )
        )

    def _get_submission_view(self, submission_id: str) -> SubmissionView:
        with session_scope() as db:
            submission = db.get(Submission, submission_id)
            if not submission:
                raise JobError("学生批阅记录不存在")
            events = db.scalars(
                select(AuditEvent)
                .where(AuditEvent.submission_id == submission_id)
                .order_by(AuditEvent.created_at)
            ).all()
            return _submission_view(submission, events)


def _job_view(
    job: GradingJob,
    *,
    include_submissions: bool,
    events_by_submission: Optional[dict[str, list[AuditEvent]]] = None,
) -> JobView:
    return JobView(
        id=job.id,
        course_id=job.course_id,
        course_name=job.course_name,
        homework_id=job.homework_id,
        homework_title=job.homework_title,
        rubric=_json_load(job.rubric_json),
        scope=JobScope.model_validate(_json_load(job.scope_json)).model_dump(
            mode="json"
        ),
        require_human_confirmation=job.require_human_confirmation,
        write_enabled=job.write_enabled,
        publish_after_write=job.publish_after_write,
        status=job.status,
        error_message=job.error_message,
        total_count=job.total_count,
        completed_count=job.completed_count,
        skipped_count=job.skipped_count,
        failed_count=job.failed_count,
        review_count=sum(
            item.status == "waiting_confirmation" for item in job.submissions
        ),
        recoverable_count=sum(
            _is_recoverable_submission(item) for item in job.submissions
        ),
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        submissions=(
            [
                _submission_view(
                    item,
                    (events_by_submission or {}).get(item.id, []),
                )
                for item in job.submissions
            ]
            if include_submissions
            else []
        ),
    )


def _submission_view(
    submission: Submission,
    events: Optional[list[AuditEvent]] = None,
) -> SubmissionView:
    return SubmissionView(
        id=submission.id,
        student_id=submission.student_id,
        student_name=submission.student_name,
        student_number_masked=submission.student_number_masked,
        class_name=submission.class_name,
        status=submission.status,
        status_message=submission.status_message,
        attempt_count=submission.attempt_count,
        pdf_files=_json_load(submission.pdf_files_json),
        ignored_files=_json_load(submission.ignored_files_json),
        grade=_json_load(submission.grade_json),
        remote_receipt=_json_load(submission.remote_receipt_json),
        events=[
            {
                "event_type": event.event_type,
                "message": event.message,
                "detail": _json_load(event.detail_json),
                "created_at": event.created_at,
            }
            for event in events or []
        ],
        updated_at=submission.updated_at,
    )


def _submission_fingerprint(detail: dict[str, Any]) -> str:
    files = [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "size": item.get("size"),
            "suffix": item.get("suffix"),
        }
        for item in detail.get("files") or []
    ]
    stable = {
        "answer_content": detail.get("answer_content"),
        "files": files,
        "redo": detail.get("redo"),
        "is_delay": detail.get("is_delay"),
        "submit_time": detail.get("submit_time"),
    }
    encoded = json.dumps(
        stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _manual_total_decision(
    original: GradeDecision,
    rubric: Rubric,
    total: Decimal,
) -> GradeDecision:
    if total != total.to_integral_value():
        raise JobError("手工总分必须为整数")
    if total > rubric.total_score:
        raise JobError(f"手工总分不能超过作业总分 {rubric.total_score}")

    matched_band = next(
        (
            band
            for band in rubric.score_bands
            if (
                band.min_score <= total < band.max_score
                or (
                    band.max_score == rubric.total_score
                    and total == band.max_score
                )
            )
        ),
        None,
    )
    return original.model_copy(
        deep=True,
        update={
            "criterion_scores": [],
            "raw_score": total,
            "final_score": total,
            "detected_score_band_id": matched_band.id if matched_band else "",
            "detected_score_band_name": (
                matched_band.name if matched_band else ""
            ),
            "score_band_evidence": [f"教师手工直接给出总分 {total} 分"],
            "confidence": 1,
            "needs_review": False,
            "review_reasons": [],
            "adjustments": ["教师手工直接给出总分"],
        },
    )


def _has_complete_grade(grade: dict[str, Any], rubric: Rubric) -> bool:
    scores = grade.get("criterion_scores")
    if not isinstance(scores, list):
        return False
    criterion_ids = {
        str(item.get("criterion_id") or "")
        for item in scores
        if isinstance(item, dict)
    }
    return criterion_ids == {criterion.id for criterion in rubric.criteria}


def _blank_manual_grade(rubric: Rubric) -> dict[str, Any]:
    return {
        "criterion_scores": [
            {
                "criterion_id": criterion.id,
                "score": 0,
                "evidence": [],
                "deductions": [],
                "explanation": "",
            }
            for criterion in rubric.criteria
        ],
        "raw_score": 0,
        "final_score": 0,
        "detected_stage_id": "",
        "detected_stage_name": "",
        "stage_evidence": [],
        "detected_score_band_id": "",
        "detected_score_band_name": "",
        "score_band_evidence": [],
        "feedback": "",
        "confidence": 0,
        "needs_review": False,
        "review_reasons": [],
        "adjustments": [],
    }


def _is_overwritable_conflict(submission: Submission) -> bool:
    if submission.status != "conflict":
        return False
    message = (submission.status_message or "").strip()
    return message.startswith(OVERWRITABLE_CONFLICT_PREFIXES)


def _is_recoverable_submission(submission: Submission) -> bool:
    if submission.status == "failed":
        return True
    if submission.status != "skipped":
        return False

    message = (submission.status_message or "").strip()
    if message.startswith(RECOVERABLE_SKIP_PREFIXES):
        return True
    if message != "未找到 PDF 报告":
        return False

    snapshot = _json_load(submission.snapshot_json)
    return any(
        _file_suffix(file) in {"docx", "zip"}
        for file in snapshot.get("files") or []
    )


def _file_suffix(file: dict[str, Any]) -> str:
    name_suffix = Path(str(file.get("name") or "")).suffix.lower().lstrip(".")
    return name_suffix or str(file.get("suffix") or "").lower().lstrip(".")


def _is_published(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {
        "1",
        "true",
        "published",
        "publish",
        "released",
        "已发布",
    }


def _has_score(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _same_score(value: Any, expected: Decimal) -> bool:
    try:
        return Decimal(str(value)).quantize(Decimal("0.1")) == expected.quantize(
            Decimal("0.1")
        )
    except Exception:
        return False


def _mask_student_number(value: str) -> str:
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _json_load(value: str) -> Any:
    try:
        return json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


job_service = JobService()
