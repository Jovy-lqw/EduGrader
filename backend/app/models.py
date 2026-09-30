from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class GradingJob(Base):
    __tablename__ = "grading_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(String(128), index=True)
    course_name: Mapped[str] = mapped_column(String(512), default="")
    homework_id: Mapped[str] = mapped_column(String(128), index=True)
    homework_title: Mapped[str] = mapped_column(String(512), default="")
    rubric_json: Mapped[str] = mapped_column(Text)
    scope_json: Mapped[str] = mapped_column(Text, default="{}")
    require_human_confirmation: Mapped[bool] = mapped_column(
        Boolean, default=False
    )
    write_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    publish_after_write: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(64), default="created", index=True)
    stop_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str] = mapped_column(Text, default="")
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    submissions: Mapped[list["Submission"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="Submission.created_at",
    )


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("grading_jobs.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[str] = mapped_column(String(128), index=True)
    student_name: Mapped[str] = mapped_column(String(256), default="")
    student_number_masked: Mapped[str] = mapped_column(String(128), default="")
    class_name: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(64), default="pending", index=True)
    status_message: Mapped[str] = mapped_column(Text, default="")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    snapshot_hash: Mapped[str] = mapped_column(String(64), default="")
    pdf_files_json: Mapped[str] = mapped_column(Text, default="[]")
    ignored_files_json: Mapped[str] = mapped_column(Text, default="[]")
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    grade_json: Mapped[str] = mapped_column(Text, default="{}")
    remote_receipt_json: Mapped[str] = mapped_column(Text, default="{}")
    initial_remote_score: Mapped[str] = mapped_column(String(64), default="")
    initial_publish_state: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    job: Mapped[GradingJob] = relationship(back_populates="submissions")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("grading_jobs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    submission_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
