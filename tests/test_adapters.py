from decimal import Decimal
from unittest import IsolatedAsyncioTestCase

from backend.app.services.adapters import AuthenticationRequired, ZhihuishuAdapter


class HomeworkListTests(IsolatedAsyncioTestCase):
    async def test_login_redirect_is_reported_as_expired_session(self) -> None:
        class RedirectSession:
            async def request(self, *args, **kwargs):
                return (
                    200,
                    {},
                    (
                        b"<script>window.top.location.href="
                        b"'http://passport.zhihuishu.com/login?service=x';</script>"
                    ),
                )

        adapter = ZhihuishuAdapter(RedirectSession())

        with self.assertRaisesRegex(AuthenticationRequired, "登录已失效"):
            await adapter._api_json("GET", "/example")

    async def test_homework_detail_preserves_authentication_error(self) -> None:
        class ExpiredAdapter(ZhihuishuAdapter):
            def __init__(self) -> None:
                pass

            async def _api_json(self, method, path, *, params=None, form=None):
                raise AuthenticationRequired("智慧树登录已失效")

        adapter = ExpiredAdapter()

        with self.assertRaisesRegex(AuthenticationRequired, "登录已失效"):
            await adapter.get_homework("course", "homework")

    async def test_uses_platform_filters_and_reads_all_pages(self) -> None:
        class RecordingAdapter(ZhihuishuAdapter):
            def __init__(self) -> None:
                self.calls: list[dict] = []

            async def _api_json(self, method, path, *, params=None, form=None):
                self.calls.append(
                    {
                        "method": method,
                        "path": path,
                        "params": params,
                        "form": form,
                    }
                )
                page_num = params["pageNum"]
                start = 1 if page_num == 1 else 21
                count = 20 if page_num == 1 else 1
                return {
                    "status": "200",
                    "rt": {
                        "rowCount": 21,
                        "list": [
                            {
                                "homeworkId": start + offset,
                                "homeworkName": f"作业 {start + offset}",
                                "approvedNum": 7,
                                "unApprovedNum": 3,
                            }
                            for offset in range(count)
                        ],
                    },
                }

        adapter = RecordingAdapter()
        homeworks = await adapter.list_homeworks("11539443")

        self.assertEqual(len(homeworks), 21)
        self.assertEqual(homeworks[0].id, "1")
        self.assertEqual(homeworks[-1].id, "21")
        self.assertEqual(homeworks[0].reviewed_count, 7)
        self.assertEqual(homeworks[0].unreviewed_count, 3)
        self.assertEqual([call["params"]["pageNum"] for call in adapter.calls], [1, 2])
        for call in adapter.calls:
            self.assertEqual(call["method"], "GET")
            self.assertEqual(
                call["path"],
                "/zhsathome/homework/homeworkListV2",
            )
            self.assertEqual(call["params"]["status"], -1)
            self.assertEqual(call["params"]["classId"], 0)
            self.assertEqual(call["params"]["source"], 0)

    async def test_unreviewed_students_use_platform_filter_and_fields(self) -> None:
        class RecordingAdapter(ZhihuishuAdapter):
            def __init__(self) -> None:
                self.calls: list[dict] = []

            async def _api_json(self, method, path, *, params=None, form=None):
                self.calls.append(params)
                return {
                    "status": "200",
                    "rt": {
                        "rowCount": 1,
                        "list": [
                            {
                                "id": 99,
                                "userId": 42,
                                "userName": "测试学生",
                                "userNo": "20260001",
                                "status": 2,
                            }
                        ],
                    },
                }

        adapter = RecordingAdapter()
        students = await adapter.list_students("3985439")

        self.assertEqual(len(students), 1)
        self.assertEqual(students[0].id, "42")
        self.assertEqual(students[0].name, "测试学生")
        self.assertEqual(students[0].student_number, "20260001")
        self.assertEqual(adapter.calls[0]["status"], 2)
        self.assertEqual(adapter.calls[0]["classId"], -1)
        self.assertEqual(adapter.calls[0]["orde"], 1)

    async def test_submission_uses_answer_score_and_platform_file_fields(
        self,
    ) -> None:
        class SubmissionAdapter(ZhihuishuAdapter):
            def __init__(self) -> None:
                self.file_form = None

            async def _api_json(self, method, path, *, params=None, form=None):
                if path.endswith("homeworkReviewUserGet"):
                    return {
                        "rt": {
                            "score": 100,
                            "answerScore": None,
                            "fileList": [
                                {
                                    "fileId": 7,
                                    "fileTitle": "阶段二报告.pdf",
                                    "fileUrl": "https://example.com/report.pdf",
                                    "suffixTypeName": "pdf",
                                }
                            ],
                        }
                    }
                self.file_form = form
                return {"rt": {"userFileInfos": {}}}

        adapter = SubmissionAdapter()
        detail = await adapter.get_submission("3985439", "42")

        self.assertEqual(detail["score"], "")
        self.assertEqual(len(detail["files"]), 1)
        self.assertEqual(detail["files"][0]["name"], "阶段二报告.pdf")
        self.assertEqual(detail["files"][0]["suffix"], "pdf")
        self.assertFalse(adapter.file_form["isGetAll"])

    async def test_write_grade_matches_platform_form(self) -> None:
        class WriteAdapter(ZhihuishuAdapter):
            def __init__(self) -> None:
                self.form = None

            async def _api_json(self, method, path, *, params=None, form=None):
                self.form = form
                return {"status": "200"}

        adapter = WriteAdapter()
        await adapter.write_grade(
            "3985439",
            "863298553",
            Decimal("94"),
            "测试评语",
            {},
        )

        self.assertEqual(adapter.form["score"], "94.0")
        self.assertEqual(adapter.form["fileId"], "0")
        self.assertEqual(adapter.form["scoreAttr"], "{}")
