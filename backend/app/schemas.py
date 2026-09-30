from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class RubricCriterion(BaseModel):
    id: str
    name: str
    description: str = ""
    max_score: Decimal = Field(gt=0)
    required_evidence: list[str] = Field(default_factory=list)
    deduction_rules: list[str] = Field(default_factory=list)
    platform_score_attr_id: Optional[str] = None


class RubricStage(BaseModel):
    id: str
    name: str
    description: str = ""
    completion_signals: list[str] = Field(default_factory=list)
    expected_deliverables: list[str] = Field(default_factory=list)


class RubricScoreBand(BaseModel):
    id: str
    name: str
    min_score: Decimal = Field(ge=0)
    max_score: Decimal = Field(gt=0)
    description: str = ""
    requirements: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_range(self) -> "RubricScoreBand":
        if self.min_score >= self.max_score:
            raise ValueError("评分档位下限必须小于上限")
        return self


class Rubric(BaseModel):
    title: str = "本次作业评分细则"
    source_text: str = ""
    total_score: Decimal = Field(gt=0)
    criteria: list[RubricCriterion] = Field(min_length=1)
    grading_mode: Literal["holistic", "stage_completion"] = "holistic"
    stages: list[RubricStage] = Field(default_factory=list)
    stage_scoring_instruction: str = ""
    overall_requirements: list[str] = Field(default_factory=list)
    score_bands: list[RubricScoreBand] = Field(default_factory=list)
    required_sections: list[str] = Field(default_factory=list)
    global_deduction_rules: list[str] = Field(default_factory=list)
    calibration_rules: list[str] = Field(default_factory=list)
    late_rule: str = ""
    late_penalty_points: Decimal = Field(default=Decimal("0"), ge=0)
    resubmission_rule: str = ""
    resubmission_penalty_points: Decimal = Field(default=Decimal("0"), ge=0)
    feedback_style: str = "准确、具体、简洁，指出主要优点与最需要改进之处。"

    @model_validator(mode="after")
    def validate_total(self) -> "Rubric":
        criteria_total = sum(
            (criterion.max_score for criterion in self.criteria), Decimal("0")
        )
        if criteria_total != self.total_score:
            raise ValueError(
                f"评分项总分 {criteria_total} 与作业总分 {self.total_score} 不一致"
            )
        if self.grading_mode == "stage_completion":
            if not self.stages:
                raise ValueError("阶段完成度评分至少需要一个阶段定义")
            stage_ids = [stage.id for stage in self.stages]
            if len(stage_ids) != len(set(stage_ids)):
                raise ValueError("阶段标识不能重复")
        band_ids = [band.id for band in self.score_bands]
        if len(band_ids) != len(set(band_ids)):
            raise ValueError("评分档位标识不能重复")
        ordered_bands = sorted(
            self.score_bands,
            key=lambda band: (band.min_score, band.max_score),
        )
        for index, band in enumerate(ordered_bands):
            if band.max_score > self.total_score:
                raise ValueError("评分档位上限不能超过作业总分")
            if index and band.min_score < ordered_bands[index - 1].max_score:
                raise ValueError("评分档位不能重叠")
        return self


class RubricNormalizeRequest(BaseModel):
    source_text: str = Field(min_length=1)
    total_score: Decimal = Field(gt=0)
    platform_criteria: list[RubricCriterion] = Field(default_factory=list)


class RubricFileParseResponse(BaseModel):
    filename: str
    file_type: Literal["pdf", "docx", "txt", "md"]
    text: str
    characters: int


class GradeCriterion(BaseModel):
    criterion_id: str
    score: Decimal = Field(ge=0)
    evidence: list[str] = Field(default_factory=list)
    deductions: list[str] = Field(default_factory=list)
    explanation: str = ""


class GradeDecision(BaseModel):
    criterion_scores: list[GradeCriterion]
    raw_score: Decimal = Field(ge=0)
    final_score: Decimal = Field(ge=0)
    detected_stage_id: str = ""
    detected_stage_name: str = ""
    stage_evidence: list[str] = Field(default_factory=list)
    detected_score_band_id: str = ""
    detected_score_band_name: str = ""
    score_band_evidence: list[str] = Field(default_factory=list)
    feedback: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    needs_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    adjustments: list[str] = Field(default_factory=list)


class Course(BaseModel):
    id: str
    name: str
    term: str = ""
    course_number: str = ""
    student_count: Optional[int] = None
    raw: dict[str, Any] = Field(default_factory=dict)


class Homework(BaseModel):
    id: str
    course_id: str
    title: str
    description: str = ""
    total_score: Optional[Decimal] = None
    status: str = ""
    deadline: str = ""
    reviewed_count: Optional[int] = None
    unreviewed_count: Optional[int] = None
    auto_publish: Optional[bool] = None
    score_attributes: list[RubricCriterion] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class RemoteStudent(BaseModel):
    id: str
    name: str
    student_number: str = ""
    class_name: str = ""
    status: str = ""
    score: Optional[Decimal] = None
    publish_state: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class JobScope(BaseModel):
    status: Literal["unreviewed", "all"] = "unreviewed"
    class_id: str = ""
    student_ids: list[str] = Field(default_factory=list)
    rerun_from_job_id: str = ""
    overwrite_existing_scores: bool = False
    allow_conflict_overwrite: bool = False


class ConflictOverwriteUpdate(BaseModel):
    enabled: bool


class JobCreate(BaseModel):
    course_id: str
    course_name: str = ""
    homework_id: str
    homework_title: str = ""
    rubric: Rubric
    scope: JobScope = Field(default_factory=JobScope)
    require_human_confirmation: bool = False
    write_enabled: bool = True


class SubmissionEventView(BaseModel):
    event_type: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class SubmissionView(BaseModel):
    id: str
    student_id: str
    student_name: str
    student_number_masked: str
    class_name: str
    status: str
    status_message: str
    attempt_count: int
    pdf_files: list[dict[str, Any]]
    ignored_files: list[dict[str, Any]]
    grade: dict[str, Any]
    remote_receipt: dict[str, Any]
    events: list[SubmissionEventView] = Field(default_factory=list)
    updated_at: datetime


class JobView(BaseModel):
    id: str
    course_id: str
    course_name: str
    homework_id: str
    homework_title: str
    rubric: dict[str, Any]
    scope: dict[str, Any]
    require_human_confirmation: bool
    write_enabled: bool
    publish_after_write: bool
    status: str
    error_message: str
    total_count: int
    completed_count: int
    skipped_count: int
    failed_count: int
    review_count: int
    recoverable_count: int
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    submissions: list[SubmissionView] = Field(default_factory=list)


class HumanDecisionUpdate(BaseModel):
    grade: GradeDecision


class SessionStatus(BaseModel):
    status: Literal["not_started", "login_required", "ready", "expired"]
    display_name: str = ""
    message: str = ""


class ApiMessage(BaseModel):
    message: str
