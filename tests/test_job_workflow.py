import asyncio
import json
from decimal import Decimal
from io import BytesIO
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch
from zipfile import ZipFile

from backend.app.database import initialize_database, session_scope
from backend.app.models import AuditEvent, GradingJob, Submission
from backend.app.schemas import (
    GradeCriterion,
    GradeDecision,
    HumanDecisionUpdate,
    JobCreate,
    JobScope,
    Rubric,
    RubricCriterion,
    RubricScoreBand,
)
from backend.app.services.adapters import MockAdapter, RemoteSafetyError
from backend.app.services.jobs import JobError, JobService, _submission_fingerprint


class JobWorkflowTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        initialize_database()
        self.service = JobService()
        self.created_job_ids: list[str] = []

    def tearDown(self) -> None:
        with session_scope() as db:
            for job_id in self.created_job_ids:
                job = db.get(GradingJob, job_id)
                if job:
                    db.delete(job)

    async def test_mock_job_writes_scores_without_publishing(self) -> None:
        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容质量",
                    max_score=Decimal("100"),
                )
            ],
        )
        job = self.service.create(
            JobCreate(
                course_id="demo-course",
                course_name="演示课程",
                homework_id="demo-homework",
                homework_title="演示作业",
                rubric=rubric,
                write_enabled=True,
            )
        )
        self.created_job_ids.append(job.id)
        adapter = MockAdapter()

        async def fake_grade(*_args, **_kwargs) -> GradeDecision:
            return GradeDecision(
                criterion_scores=[
                    GradeCriterion(
                        criterion_id="content",
                        score=Decimal("88"),
                        evidence=["报告包含实验方法与结果"],
                    )
                ],
                raw_score=Decimal("88"),
                final_score=Decimal("88"),
                feedback="实验完整，建议补充误差分析。",
                confidence=0.9,
            )

        with patch(
            "backend.app.services.jobs.get_adapter", return_value=adapter
        ), patch(
            "backend.app.services.jobs.llm_client.grade",
            side_effect=fake_grade,
        ):
            await self.service.start(job.id)
            for _ in range(100):
                current = self.service.get(job.id)
                if current.status in {"completed", "failed"}:
                    break
                await asyncio.sleep(0.02)

        current = self.service.get(job.id)
        self.assertEqual(current.status, "completed")
        self.assertEqual(current.completed_count, 2)
        self.assertEqual(current.failed_count, 0)
        self.assertEqual(
            {submission.status for submission in current.submissions},
            {"written"},
        )
        for submission in current.submissions:
            self.assertEqual(submission.grade["final_score"], "88.0")
            self.assertFalse(
                submission.remote_receipt["data"]["published"]
            )
            event_types = {event.event_type for event in submission.events}
            self.assertIn("status_fetching", event_types)
            self.assertIn("status_grading", event_types)
            self.assertIn("grade_generated", event_types)
            self.assertIn("status_written", event_types)

    async def test_stops_batch_when_platform_publishes_after_write(self) -> None:
        class AutoPublishingAdapter(MockAdapter):
            async def get_submission(self, homework_id, student_id):
                detail = await super().get_submission(homework_id, student_id)
                if student_id in self._scores:
                    detail["publish_state"] = "published"
                return detail

        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容质量",
                    max_score=Decimal("100"),
                )
            ],
        )
        job = self.service.create(
            JobCreate(
                course_id="demo-course",
                homework_id="demo-homework",
                rubric=rubric,
            )
        )
        self.created_job_ids.append(job.id)

        async def fake_grade(*_args, **_kwargs) -> GradeDecision:
            return GradeDecision(
                criterion_scores=[
                    GradeCriterion(
                        criterion_id="content", score=Decimal("80")
                    )
                ],
                raw_score=Decimal("80"),
                final_score=Decimal("80"),
                feedback="测试评语",
                confidence=0.8,
            )

        with patch(
            "backend.app.services.jobs.get_adapter",
            return_value=AutoPublishingAdapter(),
        ), patch(
            "backend.app.services.jobs.llm_client.grade",
            side_effect=fake_grade,
        ):
            await self.service.start(job.id)
            for _ in range(100):
                current = self.service.get(job.id)
                if current.status == "failed":
                    break
                await asyncio.sleep(0.02)

        current = self.service.get(job.id)
        self.assertEqual(current.status, "failed")
        self.assertEqual(current.submissions[0].status, "failed")
        self.assertEqual(current.submissions[1].status, "pending")

    async def test_model_review_can_be_approved_or_kept_skipped(self) -> None:
        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容质量",
                    max_score=Decimal("100"),
                )
            ],
        )
        job = self.service.create(
            JobCreate(
                course_id="demo-course",
                homework_id="demo-homework",
                rubric=rubric,
                write_enabled=False,
                require_human_confirmation=False,
            )
        )
        self.created_job_ids.append(job.id)
        adapter = MockAdapter()

        async def fake_grade(*_args, **_kwargs) -> GradeDecision:
            return GradeDecision(
                criterion_scores=[
                    GradeCriterion(
                        criterion_id="content",
                        score=Decimal("45"),
                        evidence=["仅包含部分实验说明"],
                    )
                ],
                raw_score=Decimal("45"),
                final_score=Decimal("45"),
                feedback="报告内容不完整。",
                confidence=0.4,
                needs_review=True,
                review_reasons=["关键测试章节缺失"],
            )

        with patch(
            "backend.app.services.jobs.get_adapter", return_value=adapter
        ), patch(
            "backend.app.services.jobs.llm_client.grade",
            side_effect=fake_grade,
        ):
            await self.service.start(job.id)
            for _ in range(100):
                current = self.service.get(job.id)
                if current.status == "waiting_confirmation":
                    break
                await asyncio.sleep(0.02)

        current = self.service.get(job.id)
        self.assertEqual(current.review_count, 2)
        self.assertEqual(current.skipped_count, 0)
        self.assertEqual(
            {submission.status for submission in current.submissions},
            {"waiting_confirmation"},
        )

        first, second = current.submissions
        await self.service.approve(
            first.id,
            HumanDecisionUpdate(
                grade=GradeDecision.model_validate(first.grade)
            ),
        )
        rejected = self.service.reject(second.id)

        self.assertEqual(rejected.status, "skipped")
        self.assertEqual(rejected.status_message, "人工复核后维持跳过")
        current = self.service.get(job.id)
        self.assertEqual(current.status, "completed")
        self.assertEqual(current.completed_count, 1)
        self.assertEqual(current.skipped_count, 1)
        self.assertEqual(current.review_count, 0)

    async def test_all_incomplete_statuses_can_enter_manual_review(self) -> None:
        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容质量",
                    max_score=Decimal("100"),
                )
            ],
        )
        job = self.service.create(
            JobCreate(
                course_id="demo-course",
                homework_id="demo-homework",
                rubric=rubric,
                write_enabled=False,
            )
        )
        self.created_job_ids.append(job.id)
        adapter = MockAdapter()
        submission_ids: dict[str, str] = {}
        with session_scope() as db:
            for index, status in enumerate(
                ["pending", "failed", "skipped", "conflict", "rejected"],
                start=1,
            ):
                submission = Submission(
                    job_id=job.id,
                    student_id=f"manual-{index}",
                    student_name=f"学生{index}",
                    status=status,
                    status_message=f"原状态：{status}",
                    pdf_files_json=json.dumps(
                        [
                            {
                                "name": f"manual-{index}.pdf",
                                "url": f"mock://manual-{index}/report.pdf",
                                "document_type": "pdf",
                            }
                        ]
                    ),
                )
                db.add(submission)
                db.flush()
                submission_ids[status] = submission.id
            completed = Submission(
                job_id=job.id,
                student_id="completed",
                status="written",
            )
            db.add(completed)
            db.flush()
            completed_id = completed.id

        for status, submission_id in submission_ids.items():
            with self.subTest(status=status):
                prepared = await self.service.begin_manual_review(
                    submission_id,
                    adapter,
                )
                self.assertEqual(prepared.status, "waiting_confirmation")
                self.assertEqual(
                    prepared.grade["criterion_scores"][0]["score"],
                    0,
                )
                self.assertTrue(
                    prepared.status_message.startswith("已转为手工评分")
                )

        with self.assertRaisesRegex(JobError, "已完成"):
            await self.service.begin_manual_review(completed_id, adapter)

        first_id = submission_ids["failed"]
        approved = await self.service.approve(
            first_id,
            HumanDecisionUpdate(
                grade=GradeDecision(
                    criterion_scores=[
                        GradeCriterion(
                            criterion_id="content",
                            score=Decimal("88"),
                        )
                    ],
                    raw_score=Decimal("88"),
                    final_score=Decimal("88"),
                    feedback="",
                    confidence=Decimal("1"),
                )
            ),
        )
        self.assertEqual(approved.status, "dry_run_complete")
        self.assertEqual(approved.grade["final_score"], "88.0")

    async def test_manual_review_can_approve_with_total_score_only(self) -> None:
        rubric = Rubric(
            total_score=Decimal("100"),
            score_bands=[
                RubricScoreBand(
                    id="passing",
                    name="完成",
                    min_score=Decimal("80"),
                    max_score=Decimal("100"),
                )
            ],
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容质量",
                    max_score=Decimal("60"),
                ),
                RubricCriterion(
                    id="format",
                    name="格式规范",
                    max_score=Decimal("40"),
                ),
            ],
        )
        job = self.service.create(
            JobCreate(
                course_id="demo-course",
                homework_id="demo-homework",
                rubric=rubric,
                write_enabled=False,
            )
        )
        self.created_job_ids.append(job.id)
        with session_scope() as db:
            submission = Submission(
                job_id=job.id,
                student_id="manual-total",
                status="failed",
                status_message="解析失败",
            )
            db.add(submission)
            db.flush()
            submission_id = submission.id

        prepared = await self.service.begin_manual_review(
            submission_id,
            MockAdapter(),
        )
        approved = await self.service.approve(
            submission_id,
            HumanDecisionUpdate(
                grade=GradeDecision.model_validate(prepared.grade),
                manual_total_score=Decimal("73"),
            ),
        )

        self.assertEqual(approved.status, "dry_run_complete")
        self.assertEqual(approved.status_message, "人工总分确认通过")
        self.assertEqual(approved.grade["final_score"], "73")
        self.assertEqual(approved.grade["criterion_scores"], [])

    async def test_manual_total_rejects_invalid_score(self) -> None:
        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容质量",
                    max_score=Decimal("100"),
                )
            ],
        )
        job = self.service.create(
            JobCreate(
                course_id="demo-course",
                homework_id="demo-homework",
                rubric=rubric,
                write_enabled=False,
            )
        )
        self.created_job_ids.append(job.id)
        with session_scope() as db:
            submission = Submission(
                job_id=job.id,
                student_id="manual-invalid-total",
                status="waiting_confirmation",
                status_message="已转为手工评分",
                grade_json=json.dumps(
                    {
                        "criterion_scores": [
                            {
                                "criterion_id": "content",
                                "score": 0,
                            }
                        ],
                        "raw_score": 0,
                        "final_score": 0,
                        "confidence": 0,
                    }
                ),
            )
            db.add(submission)
            db.flush()
            submission_id = submission.id

        current = self.service.get(job.id).submissions[0]
        with self.assertRaisesRegex(JobError, "不能超过"):
            await self.service.approve(
                submission_id,
                HumanDecisionUpdate(
                    grade=GradeDecision.model_validate(current.grade),
                    manual_total_score=Decimal("101"),
                ),
            )

    def test_deletes_inactive_job_and_related_records(self) -> None:
        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容质量",
                    max_score=Decimal("100"),
                )
            ],
        )
        job = self.service.create(
            JobCreate(
                course_id="demo-course",
                homework_id="demo-homework",
                rubric=rubric,
            )
        )
        self.created_job_ids.append(job.id)
        with session_scope() as db:
            submission = Submission(
                job_id=job.id,
                student_id="delete-me",
                status="failed",
            )
            db.add(submission)
            db.flush()
            submission_id = submission.id

        self.service.delete(job.id)

        with self.assertRaisesRegex(JobError, "任务不存在"):
            self.service.get(job.id)
        with session_scope() as db:
            self.assertIsNone(db.get(Submission, submission_id))
            self.assertEqual(
                db.query(AuditEvent).filter(AuditEvent.job_id == job.id).count(),
                0,
            )
        self.created_job_ids.remove(job.id)

    def test_rejects_deleting_active_job(self) -> None:
        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容质量",
                    max_score=Decimal("100"),
                )
            ],
        )
        job = self.service.create(
            JobCreate(
                course_id="demo-course",
                homework_id="demo-homework",
                rubric=rubric,
            )
        )
        self.created_job_ids.append(job.id)
        with session_scope() as db:
            db.get(GradingJob, job.id).status = "running"

        with self.assertRaisesRegex(JobError, "先暂停"):
            self.service.delete(job.id)

    async def test_manual_review_requires_inactive_job(self) -> None:
        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容质量",
                    max_score=Decimal("100"),
                )
            ],
        )
        job = self.service.create(
            JobCreate(
                course_id="demo-course",
                homework_id="demo-homework",
                rubric=rubric,
            )
        )
        self.created_job_ids.append(job.id)
        with session_scope() as db:
            record = db.get(GradingJob, job.id)
            record.status = "running"
            submission = Submission(
                job_id=job.id,
                student_id="manual-running",
                status="failed",
            )
            db.add(submission)
            db.flush()
            submission_id = submission.id

        with self.assertRaisesRegex(JobError, "请先暂停"):
            await self.service.begin_manual_review(
                submission_id,
                MockAdapter(),
            )

    def test_requeues_recoverable_submission_repeatedly(self) -> None:
        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容质量",
                    max_score=Decimal("100"),
                )
            ],
        )
        job = self.service.create(
            JobCreate(
                course_id="demo-course",
                homework_id="demo-homework",
                rubric=rubric,
            )
        )
        self.created_job_ids.append(job.id)
        with session_scope() as db:
            record = db.get(GradingJob, job.id)
            submission = Submission(
                job_id=job.id,
                student_id="docx-student",
                status="skipped",
                status_message="未找到 PDF 报告",
                snapshot_json=json.dumps(
                    {
                        "files": [
                            {
                                "name": "实验报告.docx",
                                "suffix": "docx",
                            }
                        ]
                    }
                ),
            )
            db.add(submission)
            db.flush()
            requeued = self.service._requeue_recoverable_submissions(
                db,
                record,
            )

        self.assertEqual(requeued, 1)
        current = self.service.get(job.id)
        self.assertEqual(current.submissions[0].status, "pending")
        self.assertEqual(
            current.submissions[0].status_message,
            "已加入重试队列，等待重新处理",
        )
        with session_scope() as db:
            record = db.get(GradingJob, job.id)
            submission = record.submissions[0]
            submission.status = "failed"
            submission.status_message = "大模型请求超时（120 秒）"
            requeued = self.service._requeue_recoverable_submissions(db, record)

        self.assertEqual(requeued, 1)
        current = self.service.get(job.id)
        self.assertEqual(current.submissions[0].status, "pending")

    async def test_loads_original_pdf_on_demand(self) -> None:
        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容质量",
                    max_score=Decimal("100"),
                )
            ],
        )
        job = self.service.create(
            JobCreate(
                course_id="demo-course",
                homework_id="demo-homework",
                rubric=rubric,
            )
        )
        self.created_job_ids.append(job.id)
        with session_scope() as db:
            submission = Submission(
                job_id=job.id,
                student_id="report-student",
                student_name="报告学生",
                status="waiting_confirmation",
                pdf_files_json=json.dumps(
                    [
                        {
                            "name": "阶段报告.pdf",
                            "document_type": "pdf",
                            "url": "mock://report.pdf",
                        }
                    ],
                    ensure_ascii=False,
                ),
            )
            db.add(submission)
            db.flush()
            submission_id = submission.id

        class PdfAdapter:
            async def download_file(self, url):
                self.url = url
                return b"%PDF-1.4\noriginal", "application/pdf"

        adapter = PdfAdapter()
        body, filename = await self.service.get_report_pdf(
            submission_id,
            adapter,
        )

        self.assertEqual(adapter.url, "mock://report.pdf")
        self.assertEqual(filename, "阶段报告.pdf")
        self.assertEqual(body, b"%PDF-1.4\noriginal")

    async def test_loads_original_pdf_from_zip_on_demand(self) -> None:
        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容质量",
                    max_score=Decimal("100"),
                )
            ],
        )
        job = self.service.create(
            JobCreate(
                course_id="demo-course",
                homework_id="demo-homework",
                rubric=rubric,
            )
        )
        self.created_job_ids.append(job.id)
        with session_scope() as db:
            submission = Submission(
                job_id=job.id,
                student_id="zip-report-student",
                student_name="压缩包学生",
                status="waiting_confirmation",
                pdf_files_json=json.dumps(
                    [
                        {
                            "name": "阶段报告.pdf",
                            "document_type": "pdf",
                            "archive_name": "handin.zip",
                            "archive_entry": "docs/report.pdf",
                        }
                    ],
                    ensure_ascii=False,
                ),
                snapshot_json=json.dumps(
                    {
                        "files": [
                            {
                                "name": "handin.zip",
                                "url": "mock://handin.zip",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
            )
            db.add(submission)
            db.flush()
            submission_id = submission.id

        archive_buffer = BytesIO()
        with ZipFile(archive_buffer, "w") as archive:
            archive.writestr("docs/report.pdf", b"%PDF-1.4\nfrom-zip")

        class ZipAdapter:
            async def download_file(self, url):
                self.url = url
                return archive_buffer.getvalue(), "application/zip"

        adapter = ZipAdapter()
        body, filename = await self.service.get_report_pdf(
            submission_id,
            adapter,
        )

        self.assertEqual(adapter.url, "mock://handin.zip")
        self.assertEqual(filename, "阶段报告.pdf")
        self.assertEqual(body, b"%PDF-1.4\nfrom-zip")

    async def test_rerun_overwrites_score_written_by_source_job(self) -> None:
        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容质量",
                    max_score=Decimal("100"),
                )
            ],
        )
        source = self.service.create(
            JobCreate(
                course_id="demo-course",
                homework_id="demo-homework",
                rubric=rubric,
            )
        )
        self.created_job_ids.append(source.id)
        source_grade = GradeDecision(
            criterion_scores=[
                GradeCriterion(
                    criterion_id="content",
                    score=Decimal("80"),
                )
            ],
            raw_score=Decimal("80"),
            final_score=Decimal("80"),
            feedback="原评分",
            confidence=0.9,
        )
        with session_scope() as db:
            source_record = db.get(GradingJob, source.id)
            source_record.status = "completed"
            db.add(
                Submission(
                    job_id=source.id,
                    student_id="demo-student-1",
                    status="written",
                    grade_json=json.dumps(
                        source_grade.model_dump(mode="json"),
                        ensure_ascii=False,
                    ),
                )
            )

        rerun = self.service.create(
            JobCreate(
                course_id="demo-course",
                homework_id="demo-homework",
                rubric=rubric,
                scope=JobScope(
                    status="all",
                    student_ids=["demo-student-1"],
                    rerun_from_job_id=source.id,
                    overwrite_existing_scores=True,
                ),
            )
        )
        self.created_job_ids.append(rerun.id)
        adapter = MockAdapter()
        adapter._scores["demo-student-1"] = Decimal("80")
        detail = await adapter.get_submission(
            "demo-homework",
            "demo-student-1",
        )
        rerun_grade = source_grade.model_copy(
            update={
                "raw_score": Decimal("92"),
                "final_score": Decimal("92"),
                "feedback": "重批评分",
                "criterion_scores": [
                    GradeCriterion(
                        criterion_id="content",
                        score=Decimal("92"),
                    )
                ],
            }
        )
        with session_scope() as db:
            submission = Submission(
                job_id=rerun.id,
                student_id="demo-student-1",
                status="writing",
                snapshot_json=json.dumps(detail),
                snapshot_hash=_submission_fingerprint(detail),
                initial_remote_score="80.0",
                grade_json=json.dumps(
                    rerun_grade.model_dump(mode="json"),
                    ensure_ascii=False,
                ),
            )
            db.add(submission)
            db.flush()
            submission_id = submission.id

        await self.service._write_one(rerun.id, submission_id, adapter)

        current = self.service.get(rerun.id).submissions[0]
        self.assertEqual(current.status, "written")
        self.assertEqual(adapter._scores["demo-student-1"], Decimal("92"))
        write_event = next(
            event for event in current.events if event.event_type == "grade_written"
        )
        self.assertEqual(write_event.detail["previous_score"], "80.0")
        self.assertTrue(write_event.detail["overwrote_existing_score"])
        self.assertEqual(write_event.detail["rerun_from_job_id"], source.id)
        with self.assertRaisesRegex(
            RemoteSafetyError,
            "可能已被人工修改",
        ):
            self.service._validate_existing_remote_score(
                rerun.id,
                "demo-student-1",
                "92.0",
            )

    async def test_conflict_overwrite_requeues_and_writes_changed_score(
        self,
    ) -> None:
        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容质量",
                    max_score=Decimal("100"),
                )
            ],
        )
        source = self.service.create(
            JobCreate(
                course_id="demo-course",
                homework_id="demo-homework",
                rubric=rubric,
            )
        )
        self.created_job_ids.append(source.id)
        source_grade = GradeDecision(
            criterion_scores=[
                GradeCriterion(criterion_id="content", score=Decimal("80"))
            ],
            raw_score=Decimal("80"),
            final_score=Decimal("80"),
            feedback="原评分",
            confidence=0.9,
        )
        with session_scope() as db:
            source_record = db.get(GradingJob, source.id)
            source_record.status = "completed"
            db.add(
                Submission(
                    job_id=source.id,
                    student_id="demo-student-1",
                    status="written",
                    grade_json=json.dumps(
                        source_grade.model_dump(mode="json"),
                        ensure_ascii=False,
                    ),
                )
            )

        rerun = self.service.create(
            JobCreate(
                course_id="demo-course",
                homework_id="demo-homework",
                rubric=rubric,
                scope=JobScope(
                    status="all",
                    student_ids=["demo-student-1"],
                    rerun_from_job_id=source.id,
                    overwrite_existing_scores=True,
                ),
            )
        )
        self.created_job_ids.append(rerun.id)
        adapter = MockAdapter()
        adapter._scores["demo-student-1"] = Decimal("92")
        detail = await adapter.get_submission(
            "demo-homework",
            "demo-student-1",
        )
        rerun_grade = source_grade.model_copy(
            update={
                "raw_score": Decimal("94"),
                "final_score": Decimal("94"),
                "feedback": "冲突覆盖评分",
                "criterion_scores": [
                    GradeCriterion(
                        criterion_id="content",
                        score=Decimal("94"),
                    )
                ],
            }
        )
        with session_scope() as db:
            record = db.get(GradingJob, rerun.id)
            record.status = "completed"
            submission = Submission(
                job_id=rerun.id,
                student_id="demo-student-1",
                status="conflict",
                status_message=(
                    "远端成绩与原任务记录不一致，可能已被人工修改，已阻止覆盖"
                ),
                snapshot_json=json.dumps(detail),
                snapshot_hash=_submission_fingerprint(detail),
                initial_remote_score="80.0",
                grade_json=json.dumps(
                    rerun_grade.model_dump(mode="json"),
                    ensure_ascii=False,
                ),
            )
            db.add(submission)
            db.flush()
            submission_id = submission.id

        updated = self.service.set_conflict_overwrite(rerun.id, True)

        self.assertTrue(updated.scope["allow_conflict_overwrite"])
        self.assertEqual(updated.status, "paused")
        self.assertEqual(updated.skipped_count, 0)
        self.assertEqual(updated.submissions[0].status, "pending")
        protected = self.service.set_conflict_overwrite(rerun.id, False)
        self.assertFalse(protected.scope["allow_conflict_overwrite"])
        self.assertEqual(protected.status, "completed")
        self.assertEqual(protected.submissions[0].status, "conflict")
        updated = self.service.set_conflict_overwrite(rerun.id, True)
        self.assertEqual(updated.submissions[0].status, "pending")
        await self.service._write_one(rerun.id, submission_id, adapter)
        self.assertEqual(adapter._scores["demo-student-1"], Decimal("94"))
        self.assertEqual(
            self.service.get(rerun.id).submissions[0].status,
            "written",
        )

    async def test_regular_job_cannot_overwrite_existing_score(self) -> None:
        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容质量",
                    max_score=Decimal("100"),
                )
            ],
        )
        job = self.service.create(
            JobCreate(
                course_id="demo-course",
                homework_id="demo-homework",
                rubric=rubric,
            )
        )
        self.created_job_ids.append(job.id)
        with self.assertRaisesRegex(
            JobError,
            "仅重新批阅任务",
        ):
            self.service.set_conflict_overwrite(job.id, True)
        adapter = MockAdapter()
        adapter._scores["demo-student-1"] = Decimal("80")
        detail = await adapter.get_submission(
            "demo-homework",
            "demo-student-1",
        )
        grade = GradeDecision(
            criterion_scores=[
                GradeCriterion(
                    criterion_id="content",
                    score=Decimal("90"),
                )
            ],
            raw_score=Decimal("90"),
            final_score=Decimal("90"),
            feedback="新评分",
            confidence=0.9,
        )
        with session_scope() as db:
            submission = Submission(
                job_id=job.id,
                student_id="demo-student-1",
                status="writing",
                snapshot_json=json.dumps(detail),
                snapshot_hash=_submission_fingerprint(detail),
                initial_remote_score="80.0",
                grade_json=json.dumps(
                    grade.model_dump(mode="json"),
                    ensure_ascii=False,
                ),
            )
            db.add(submission)
            db.flush()
            submission_id = submission.id

        with self.assertRaisesRegex(
            RemoteSafetyError,
            "当前任务未授权覆盖",
        ):
            await self.service._write_one(job.id, submission_id, adapter)
        self.assertEqual(adapter._scores["demo-student-1"], Decimal("80"))

    def test_rerun_rejects_unrelated_or_unbounded_scope(self) -> None:
        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容质量",
                    max_score=Decimal("100"),
                )
            ],
        )
        source = self.service.create(
            JobCreate(
                course_id="demo-course",
                homework_id="demo-homework",
                rubric=rubric,
            )
        )
        self.created_job_ids.append(source.id)
        with session_scope() as db:
            db.add(
                Submission(
                    job_id=source.id,
                    student_id="demo-student-1",
                    status="written",
                )
            )

        with self.assertRaisesRegex(JobError, "必须限定为原任务中的学生"):
            self.service.create(
                JobCreate(
                    course_id="demo-course",
                    homework_id="demo-homework",
                    rubric=rubric,
                    scope=JobScope(
                        status="all",
                        rerun_from_job_id=source.id,
                        overwrite_existing_scores=True,
                    ),
                )
            )
        with self.assertRaisesRegex(JobError, "原任务之外的学生"):
            self.service.create(
                JobCreate(
                    course_id="demo-course",
                    homework_id="demo-homework",
                    rubric=rubric,
                    scope=JobScope(
                        status="all",
                        student_ids=["another-student"],
                        rerun_from_job_id=source.id,
                        overwrite_existing_scores=True,
                    ),
                )
            )

    def test_does_not_requeue_genuine_review_or_missing_attachment(self) -> None:
        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容质量",
                    max_score=Decimal("100"),
                )
            ],
        )
        job = self.service.create(
            JobCreate(
                course_id="demo-course",
                homework_id="demo-homework",
                rubric=rubric,
            )
        )
        self.created_job_ids.append(job.id)
        with session_scope() as db:
            record = db.get(GradingJob, job.id)
            db.add_all(
                [
                    Submission(
                        job_id=job.id,
                        student_id="incomplete",
                        status="skipped",
                        status_message="模型要求复核：报告内容明显残缺",
                    ),
                    Submission(
                        job_id=job.id,
                        student_id="no-file",
                        status="skipped",
                        status_message="未找到 PDF 报告",
                        snapshot_json=json.dumps({"files": []}),
                    ),
                ]
            )
            db.flush()
            requeued = self.service._requeue_recoverable_submissions(db, record)

        self.assertEqual(requeued, 0)
        current = self.service.get(job.id)
        self.assertEqual(current.recoverable_count, 0)
        self.assertEqual(
            {submission.status for submission in current.submissions},
            {"skipped"},
        )

    def test_recovers_interrupted_job_as_paused(self) -> None:
        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容质量",
                    max_score=Decimal("100"),
                )
            ],
        )
        job = self.service.create(
            JobCreate(
                course_id="demo-course",
                homework_id="demo-homework",
                rubric=rubric,
            )
        )
        self.created_job_ids.append(job.id)
        with session_scope() as db:
            record = db.get(GradingJob, job.id)
            record.status = "running"
            db.add_all(
                [
                    Submission(
                        job_id=job.id,
                        student_id="grading",
                        status="grading",
                    ),
                    Submission(
                        job_id=job.id,
                        student_id="writing",
                        status="writing",
                    ),
                ]
            )

        self.service.recover_interrupted_jobs()

        current = self.service.get(job.id)
        by_student = {
            submission.student_id: submission
            for submission in current.submissions
        }
        self.assertEqual(current.status, "paused")
        self.assertEqual(by_student["grading"].status, "pending")
        self.assertEqual(by_student["writing"].status, "conflict")

    def test_migrates_legacy_model_review(self) -> None:
        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容质量",
                    max_score=Decimal("100"),
                )
            ],
        )
        job = self.service.create(
            JobCreate(
                course_id="demo-course",
                homework_id="demo-homework",
                rubric=rubric,
            )
        )
        self.created_job_ids.append(job.id)
        grade = GradeDecision(
            criterion_scores=[
                GradeCriterion(
                    criterion_id="content",
                    score=Decimal("40"),
                )
            ],
            raw_score=Decimal("40"),
            final_score=Decimal("40"),
            feedback="内容残缺。",
            confidence=0.4,
            needs_review=True,
            review_reasons=["关键章节缺失"],
        )
        with session_scope() as db:
            record = db.get(GradingJob, job.id)
            record.status = "completed"
            record.skipped_count = 1
            db.add(
                Submission(
                    job_id=job.id,
                    student_id="legacy-review",
                    status="skipped",
                    status_message="模型要求复核：关键章节缺失",
                    grade_json=json.dumps(
                        grade.model_dump(mode="json"),
                        ensure_ascii=False,
                    ),
                )
            )

        migrated = self.service.migrate_legacy_model_reviews(job.id)

        self.assertEqual(migrated, 1)
        current = self.service.get(job.id)
        self.assertEqual(current.status, "waiting_confirmation")
        self.assertEqual(current.review_count, 1)
        self.assertEqual(current.skipped_count, 0)
        self.assertEqual(
            current.submissions[0].status_message,
            "模型建议人工复核：关键章节缺失",
        )
