from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Iterable, Optional
from urllib.parse import urljoin

from ..runtime_config import runtime_config_store
from ..schemas import Course, Homework, RemoteStudent, RubricCriterion, SessionStatus
from .browser_session import TEACHER_HOME_URL, BrowserSession, browser_session


HIEXAM_BASE = "https://hiexam-server.zhihuishu.com"


class AdapterError(RuntimeError):
    pass


class AuthenticationRequired(AdapterError):
    pass


class RemoteSafetyError(AdapterError):
    pass


class PostWriteVerificationError(RemoteSafetyError):
    pass


class PlatformAdapter(ABC):
    @abstractmethod
    async def session_status(self) -> SessionStatus:
        raise NotImplementedError

    @abstractmethod
    async def open_login(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_courses(self) -> list[Course]:
        raise NotImplementedError

    @abstractmethod
    async def list_homeworks(self, course_id: str) -> list[Homework]:
        raise NotImplementedError

    @abstractmethod
    async def get_homework(self, course_id: str, homework_id: str) -> Homework:
        raise NotImplementedError

    @abstractmethod
    async def list_students(
        self,
        homework_id: str,
        *,
        class_id: str = "",
        status: str = "unreviewed",
    ) -> list[RemoteStudent]:
        raise NotImplementedError

    @abstractmethod
    async def get_submission(
        self, homework_id: str, student_id: str
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def download_file(self, url: str) -> tuple[bytes, str]:
        raise NotImplementedError

    @abstractmethod
    async def write_grade(
        self,
        homework_id: str,
        student_id: str,
        score: Decimal,
        remark: str,
        score_attributes: dict[str, Decimal],
    ) -> dict[str, Any]:
        raise NotImplementedError


class ZhihuishuAdapter(PlatformAdapter):
    def __init__(self, session: BrowserSession = browser_session) -> None:
        self.session = session

    async def session_status(self) -> SessionStatus:
        if not self.session.started:
            return SessionStatus(status="not_started", message="浏览器尚未启动")
        try:
            payload = await self._api_json(
                "GET", "/zhsathome/atUser/getLoginUserInfo"
            )
        except AuthenticationRequired:
            return SessionStatus(status="login_required", message="请在浏览器中登录")
        except AdapterError as exc:
            return SessionStatus(status="expired", message=str(exc))
        name = str(
            _first_value(payload, ("realName", "name", "username", "userName"))
            or ""
        )
        await self.session.persist_state()
        return SessionStatus(status="ready", display_name=name, message="登录有效")

    async def open_login(self) -> None:
        await self.session.open_login()

    async def list_courses(self) -> list[Course]:
        page = await self.session.page()
        try:
            async with page.expect_response(
                lambda response: "queryTeacherCourse" in response.url,
                timeout=20_000,
            ) as response_info:
                await page.goto(TEACHER_HOME_URL, wait_until="domcontentloaded")
            response = await response_info.value
            payload = await response.json()
        except Exception as exc:
            status = await self.session_status()
            if status.status != "ready":
                raise AuthenticationRequired(status.message) from exc
            raise AdapterError(
                "未捕获到课程列表接口，请刷新智慧树教师首页后重试"
            ) from exc

        records = _best_record_list(
            payload,
            id_keys=("courseId", "courseID", "id"),
            name_keys=("courseName", "name"),
        )
        courses: list[Course] = []
        seen: set[str] = set()
        for record in records:
            course_id = _string_value(record, ("courseId", "courseID", "id"))
            name = _string_value(record, ("courseName", "name"))
            if not course_id or not name or course_id in seen:
                continue
            seen.add(course_id)
            courses.append(
                Course(
                    id=course_id,
                    name=name,
                    term=_string_value(
                        record, ("termName", "semesterName", "term", "semester")
                    ),
                    course_number=_string_value(
                        record, ("courseNumber", "courseNo", "courseCode")
                    ),
                    student_count=_int_value(
                        record, ("studentCount", "studentNum", "stuCount")
                    ),
                    raw=record,
                )
            )
        return courses

    async def list_homeworks(self, course_id: str) -> list[Homework]:
        page_num = 1
        page_size = 20
        homeworks: list[Homework] = []
        seen: set[str] = set()
        while True:
            payload = await self._api_json(
                "GET",
                "/zhsathome/homework/homeworkListV2",
                params={
                    "courseId": course_id,
                    "key": "",
                    "status": -1,
                    "pageNum": page_num,
                    "pageSize": page_size,
                    "classId": 0,
                    "source": 0,
                },
            )
            records = _best_record_list(
                payload,
                id_keys=("homeworkId", "id"),
                name_keys=("homeworkName", "title", "name"),
            )
            for record in records:
                homework_id = _string_value(record, ("homeworkId", "id"))
                if not homework_id or homework_id in seen:
                    continue
                seen.add(homework_id)
                homeworks.append(self._homework_from_record(course_id, record))
            row_count = _int_value(payload, ("rowCount", "total", "totalCount"))
            if (
                not records
                or len(records) < page_size
                or (row_count is not None and len(homeworks) >= row_count)
            ):
                break
            page_num += 1
        return homeworks

    async def get_homework(self, course_id: str, homework_id: str) -> Homework:
        payloads = await asyncio.gather(
            self._api_json(
                "GET",
                "/zhsathome/homework/getPart3",
                params={"homeworkId": homework_id, "courseId": course_id},
            ),
            self._api_json(
                "GET",
                "/zhsathome/homeworkDir/homeworkDirGet2",
                params={"homeworkId": homework_id},
            ),
            self._api_json(
                "GET",
                "/zhsathome/homeworkDir/homeworkDirGet3",
                params={"homeworkId": homework_id},
            ),
            return_exceptions=True,
        )
        merged: dict[str, Any] = {}
        errors: list[Exception] = []
        for payload in payloads:
            if isinstance(payload, dict):
                merged.update(_unwrap_dict(payload))
            elif isinstance(payload, AuthenticationRequired):
                raise payload
            elif isinstance(payload, Exception):
                errors.append(payload)
        if not merged:
            for error in errors:
                if isinstance(error, AdapterError):
                    raise error
            raise AdapterError("无法读取作业详情")
        homework = self._homework_from_record(course_id, merged)
        if not homework.id:
            homework.id = homework_id
        homework.auto_publish = _find_bool(
            merged,
            (
                "autoPublish",
                "isAutoPublish",
                "autoPublishScore",
                "isAutoRelease",
            ),
        )
        homework.score_attributes = _extract_score_attributes(merged)
        return homework

    async def list_students(
        self,
        homework_id: str,
        *,
        class_id: str = "",
        status: str = "unreviewed",
    ) -> list[RemoteStudent]:
        page_num = 1
        students: list[RemoteStudent] = []
        seen: set[str] = set()
        while True:
            page_size = 50
            params: dict[str, Any] = {
                "homeworkId": homework_id,
                "classId": class_id or -1,
                "key": "",
                "status": 2 if status == "unreviewed" else -1,
                "orde": 1,
                "pageNum": page_num,
                "pageSize": page_size,
            }
            payload = await self._api_json(
                "GET",
                "/zhsathome/homeworkReview/reviewUserList",
                params=params,
            )
            records = _best_record_list(
                payload,
                id_keys=("userId", "studentId", "uuid", "id"),
                name_keys=("studentName", "realName", "userName", "name"),
            )
            if not records:
                break
            for record in records:
                student_id = _record_string_value(
                    record, ("userId", "studentId", "uuid", "id")
                )
                if not student_id or student_id in seen:
                    continue
                seen.add(student_id)
                students.append(
                    RemoteStudent(
                        id=student_id,
                        name=_string_value(
                            record,
                            ("studentName", "realName", "userName", "name"),
                        ),
                        student_number=_string_value(
                            record,
                            (
                                "studentNumber",
                                "studentNo",
                                "userNo",
                                "schoolNumber",
                            ),
                        ),
                        class_name=_string_value(
                            record, ("className", "clazzName")
                        ),
                        status=_string_value(
                            record, ("reviewStatus", "status", "submitStatus")
                        ),
                        score=_decimal_value(record, ("score", "answerScore")),
                        publish_state=_string_value(
                            record,
                            ("publishStatus", "scorePublishStatus", "isPublish"),
                        ),
                        raw=record,
                    )
                )
            row_count = _int_value(payload, ("rowCount", "total", "totalCount"))
            if len(records) < page_size or (
                row_count is not None and len(students) >= row_count
            ):
                break
            page_num += 1
        return students

    async def get_submission(
        self, homework_id: str, student_id: str
    ) -> dict[str, Any]:
        detail_payload = await self._api_json(
            "GET",
            "/zhsathome/homeworkDir/homeworkReviewUserGet",
            params={"homeworkId": homework_id, "studentId": student_id},
        )
        try:
            files_payload = await self._api_json(
                "POST",
                "/zhsathome/homeworkFile/listUserAnswerFileInfo",
                form={
                    "homeworkId": homework_id,
                    "studentIds": student_id,
                    "isGetAll": False,
                    "isAnnotate": 0,
                },
            )
        except AuthenticationRequired:
            raise
        except AdapterError:
            files_payload = {}
        detail = _unwrap_dict(detail_payload)
        files = _merge_files(
            _extract_files(detail),
            _extract_files(files_payload),
        )
        score = detail.get("answerScore")
        if score is None:
            score = detail.get("homeworkUserScore")
        return {
            "homework_id": homework_id,
            "student_id": student_id,
            "answer_content": _string_value(
                detail, ("answerContent", "content", "answer")
            ),
            "files": files,
            "score": "" if score is None else str(score),
            "publish_state": _string_value(
                detail, ("publishStatus", "scorePublishStatus", "isPublish")
            ),
            "status": _string_value(
                detail, ("reviewStatus", "status", "submitStatus")
            ),
            "redo": _first_value(detail, ("redo", "isRedo", "redoStatus")),
            "is_delay": _first_value(detail, ("isDelay", "delay")),
            "submit_time": _string_value(
                detail, ("submitTime", "submissionTime", "updateTime")
            ),
            "score_attributes": _extract_score_attributes(detail),
            "raw": detail,
        }

    async def download_file(self, url: str) -> tuple[bytes, str]:
        if not url:
            raise AdapterError("附件缺少下载地址")
        status, headers, body = await self.session.request(
            "GET", urljoin(HIEXAM_BASE, url)
        )
        if status in (401, 403):
            raise AuthenticationRequired("登录已失效，请重新登录")
        if status < 200 or status >= 300:
            raise AdapterError(f"附件下载失败，HTTP {status}")
        return body, headers.get("content-type", "")

    async def write_grade(
        self,
        homework_id: str,
        student_id: str,
        score: Decimal,
        remark: str,
        score_attributes: dict[str, Decimal],
    ) -> dict[str, Any]:
        payload = await self._api_json(
            "POST",
            "/zhsathome/homeworkDir/reviewHomeworkDirUser",
            form={
                "homeworkId": homework_id,
                "studentId": student_id,
                "score": _decimal_text(score),
                "remark": remark,
                "scoreAttr": json.dumps(
                    {
                        key: _decimal_text(value)
                        for key, value in score_attributes.items()
                    },
                    ensure_ascii=False,
                ),
                "fileJson": "[]",
                "remarkAudioJson": "[]",
                "fileId": "0",
                "fileUrl": "",
                "duration": "",
            },
        )
        return payload

    async def _api_json(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        form: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        config = runtime_config_store.load()
        status, _headers, body = await self.session.request(
            method,
            urljoin(HIEXAM_BASE, path),
            params=params,
            form=form,
            timeout_ms=config.request_timeout_seconds * 1000,
        )
        text = body.decode("utf-8", errors="replace")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            normalized = text.lower()
            if (
                "passport.zhihuishu.com/login" in normalized
                or ("window.top.location" in normalized and "login" in normalized)
            ):
                raise AuthenticationRequired(
                    "智慧树登录已失效，请重新登录后继续任务"
                ) from exc
            raise AdapterError(f"平台接口返回了非 JSON 内容，HTTP {status}") from exc
        if status in (401, 403) or _is_login_timeout(payload):
            raise AuthenticationRequired("登录已失效，请在浏览器中重新登录")
        if status < 200 or status >= 300:
            raise AdapterError(f"平台接口请求失败，HTTP {status}")
        code = _first_value(payload, ("code", "statusCode"))
        if code not in (None, 0, "0", 200, "200"):
            message = _string_value(payload, ("message", "msg", "errorMsg"))
            raise AdapterError(message or f"平台业务接口返回错误码 {code}")
        return payload

    @staticmethod
    def _homework_from_record(course_id: str, record: dict[str, Any]) -> Homework:
        return Homework(
            id=_string_value(record, ("homeworkId", "id")),
            course_id=course_id,
            title=_string_value(record, ("homeworkName", "title", "name")),
            description=_string_value(
                record, ("description", "homeworkExplain", "content")
            ),
            total_score=_decimal_value(
                record, ("totalScore", "homeworkScore", "score")
            ),
            status=_string_value(record, ("status", "homeworkStatus")),
            deadline=_string_value(
                record, ("endTime", "deadline", "homeworkEndTime")
            ),
            reviewed_count=_int_value(
                record,
                ("reviewedCount", "reviewNum", "reviewedNum", "approvedNum"),
            ),
            unreviewed_count=_int_value(
                record,
                (
                    "unreviewedCount",
                    "unReviewNum",
                    "notReviewNum",
                    "unApprovedNum",
                ),
            ),
            auto_publish=_find_bool(
                record, ("autoPublish", "isAutoPublish", "autoPublishScore")
            ),
            score_attributes=_extract_score_attributes(record),
            raw=record,
        )


class MockAdapter(PlatformAdapter):
    def __init__(self) -> None:
        self._scores: dict[str, Decimal] = {}

    async def session_status(self) -> SessionStatus:
        return SessionStatus(status="ready", display_name="本地演示教师")

    async def open_login(self) -> None:
        return None

    async def list_courses(self) -> list[Course]:
        return [
            Course(
                id="demo-course",
                name="边缘智能系统（演示）",
                term="2026 秋",
                course_number="DEMO-001",
                student_count=2,
            )
        ]

    async def list_homeworks(self, course_id: str) -> list[Homework]:
        return [
            Homework(
                id="demo-homework",
                course_id=course_id,
                title="实验报告：端侧模型推理",
                total_score=Decimal("100"),
                unreviewed_count=2,
                auto_publish=False,
            )
        ]

    async def get_homework(self, course_id: str, homework_id: str) -> Homework:
        return (await self.list_homeworks(course_id))[0]

    async def list_students(
        self,
        homework_id: str,
        *,
        class_id: str = "",
        status: str = "unreviewed",
    ) -> list[RemoteStudent]:
        return [
            RemoteStudent(
                id="demo-student-1",
                name="学生甲",
                student_number="20260001",
                class_name="演示班",
                status="unreviewed",
            ),
            RemoteStudent(
                id="demo-student-2",
                name="学生乙",
                student_number="20260002",
                class_name="演示班",
                status="unreviewed",
            ),
        ]

    async def get_submission(
        self, homework_id: str, student_id: str
    ) -> dict[str, Any]:
        current_score = self._scores.get(student_id)
        return {
            "homework_id": homework_id,
            "student_id": student_id,
            "answer_content": "",
            "files": [
                {
                    "id": f"{student_id}-pdf",
                    "name": f"{student_id}-report.pdf",
                    "url": f"mock://{student_id}/report.pdf",
                    "suffix": "pdf",
                    "content_type": "application/pdf",
                },
                {
                    "id": f"{student_id}-zip",
                    "name": "source.zip",
                    "url": f"mock://{student_id}/source.zip",
                    "suffix": "zip",
                    "content_type": "application/zip",
                },
            ],
            "score": "" if current_score is None else _decimal_text(current_score),
            "publish_state": "unpublished",
            "status": "unreviewed",
            "redo": False,
            "is_delay": False,
            "submit_time": "2026-09-28 12:00:00",
            "score_attributes": [],
            "raw": {},
        }

    async def download_file(self, url: str) -> tuple[bytes, str]:
        try:
            import fitz
        except ImportError as exc:
            raise AdapterError("演示 PDF 生成依赖 PyMuPDF") from exc
        document = fitz.open()
        page = document.new_page()
        page.insert_text(
            (72, 72),
            (
                "Edge model inference report\n"
                "The experiment compares FP16 and INT8 latency and memory.\n"
                "Results include methodology, measurements, analysis, and conclusion."
            ),
        )
        data = document.tobytes()
        document.close()
        return data, "application/pdf"

    async def write_grade(
        self,
        homework_id: str,
        student_id: str,
        score: Decimal,
        remark: str,
        score_attributes: dict[str, Decimal],
    ) -> dict[str, Any]:
        self._scores[student_id] = score
        return {
            "code": 0,
            "data": {
                "homeworkId": homework_id,
                "studentId": student_id,
                "score": _decimal_text(score),
                "published": False,
            },
        }


_mock_adapter = MockAdapter()


def get_adapter() -> PlatformAdapter:
    if runtime_config_store.load().adapter_mode == "mock":
        return _mock_adapter
    return ZhihuishuAdapter()


def _walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for nested in value.values():
            yield from _walk(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk(nested)


def _best_record_list(
    payload: Any,
    *,
    id_keys: tuple[str, ...],
    name_keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    best: list[dict[str, Any]] = []
    for value in _walk(payload):
        if not isinstance(value, list):
            continue
        records = [item for item in value if isinstance(item, dict)]
        if not records:
            continue
        matches = [
            item
            for item in records
            if any(key in item for key in id_keys)
            and any(key in item for key in name_keys)
        ]
        if len(matches) > len(best):
            best = matches
    return best


def _unwrap_dict(payload: dict[str, Any]) -> dict[str, Any]:
    value: Any = payload
    while isinstance(value, dict):
        nested = None
        for key in ("data", "result", "rt"):
            candidate = value.get(key)
            if isinstance(candidate, dict):
                nested = candidate
                break
        if nested is None:
            break
        value = nested
    return value if isinstance(value, dict) else payload


def _first_value(value: Any, keys: tuple[str, ...]) -> Any:
    lowered = {key.lower() for key in keys}
    for item in _walk(value):
        if isinstance(item, dict):
            for key, candidate in item.items():
                if key.lower() in lowered and candidate is not None:
                    return candidate
    return None


def _string_value(value: Any, keys: tuple[str, ...]) -> str:
    candidate = _first_value(value, keys)
    if candidate is None:
        return ""
    return str(candidate)


def _record_string_value(
    record: dict[str, Any],
    keys: tuple[str, ...],
) -> str:
    for key in keys:
        candidate = record.get(key)
        if candidate is not None:
            return str(candidate)
    return ""


def _int_value(value: Any, keys: tuple[str, ...]) -> Optional[int]:
    candidate = _first_value(value, keys)
    if candidate in (None, ""):
        return None
    try:
        return int(candidate)
    except (TypeError, ValueError):
        return None


def _decimal_value(value: Any, keys: tuple[str, ...]) -> Optional[Decimal]:
    candidate = _first_value(value, keys)
    if candidate in (None, ""):
        return None
    try:
        return Decimal(str(candidate))
    except Exception:
        return None


def _find_bool(value: Any, keys: tuple[str, ...]) -> Optional[bool]:
    candidate = _first_value(value, keys)
    if candidate is None:
        return None
    if isinstance(candidate, bool):
        return candidate
    normalized = str(candidate).strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return None


def _extract_files(payload: Any) -> list[dict[str, Any]]:
    records = _best_record_list(
        payload,
        id_keys=("fileId", "id", "sourceFileId"),
        name_keys=("fileName", "fileTitle", "name", "sourceFileName"),
    )
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        file_id = _string_value(record, ("fileId", "sourceFileId", "id"))
        name = _string_value(
            record,
            (
                "fileName",
                "fileTitle",
                "sourceFileName",
                "name",
                "originalName",
            ),
        )
        url = _string_value(
            record,
            ("fileUrl", "sourcefileUrl", "sourceFileUrl", "url", "downloadUrl"),
        )
        key = file_id or url or name
        if not key or key in seen:
            continue
        seen.add(key)
        suffix = _string_value(
            record,
            ("suffix", "suffixTypeName", "fileSuffix", "ext"),
        )
        if not suffix and "." in name:
            suffix = name.rsplit(".", 1)[-1]
        files.append(
            {
                "id": file_id,
                "name": name,
                "url": url,
                "suffix": suffix.lower().lstrip("."),
                "content_type": _string_value(
                    record, ("contentType", "mimeType", "fileType")
                ),
                "size": _int_value(record, ("fileSize", "size")),
            }
        )
    return files


def _merge_files(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for file in group:
            key = str(file.get("id") or file.get("url") or file.get("name") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(file)
    return merged


def _extract_score_attributes(payload: Any) -> list[RubricCriterion]:
    candidates: list[dict[str, Any]] = []
    for value in _walk(payload):
        if isinstance(value, list):
            records = [item for item in value if isinstance(item, dict)]
            matches = [
                item
                for item in records
                if any(key in item for key in ("scoreAttrId", "attrId"))
                and any(key in item for key in ("score", "maxScore", "scoreValue"))
            ]
            if len(matches) > len(candidates):
                candidates = matches
    criteria: list[RubricCriterion] = []
    for index, item in enumerate(candidates):
        platform_id = _string_value(item, ("scoreAttrId", "attrId", "id"))
        max_score = _decimal_value(item, ("maxScore", "scoreValue", "score"))
        if not platform_id or max_score is None or max_score <= 0:
            continue
        criteria.append(
            RubricCriterion(
                id=f"criterion-{index + 1}",
                name=_string_value(
                    item, ("scoreAttrName", "attrName", "name", "title")
                )
                or f"评分项 {index + 1}",
                description=_string_value(item, ("description", "desc", "content")),
                max_score=max_score,
                platform_score_attr_id=platform_id,
            )
        )
    return criteria


def _is_login_timeout(payload: Any) -> bool:
    value = _first_value(payload, ("loginstatus", "loginStatus"))
    return str(value).lower() in {"timeout", "expired", "false"}


def _decimal_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.1")), "f")
