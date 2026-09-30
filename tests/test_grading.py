import asyncio
from decimal import Decimal
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

from pydantic import ValidationError

from backend.app.schemas import (
    GradeCriterion,
    GradeDecision,
    Rubric,
    RubricCriterion,
    RubricNormalizeRequest,
    RubricScoreBand,
    RubricStage,
)
from backend.app.services.llm import (
    GradeValidationError,
    GradeValidator,
    LlmClient,
    LlmError,
    _parse_json_object,
)


class RubricTests(TestCase):
    def test_rejects_total_mismatch(self) -> None:
        with self.assertRaises(ValidationError):
            Rubric(
                total_score=Decimal("100"),
                criteria=[
                    RubricCriterion(
                        id="quality",
                        name="质量",
                        max_score=Decimal("90"),
                    )
                ],
            )

    def test_stage_completion_requires_stage_definitions(self) -> None:
        with self.assertRaises(ValidationError):
            Rubric(
                total_score=Decimal("100"),
                grading_mode="stage_completion",
                criteria=[
                    RubricCriterion(
                        id="completion",
                        name="完成度",
                        max_score=Decimal("100"),
                    )
                ],
            )

    def test_rejects_overlapping_score_bands(self) -> None:
        with self.assertRaises(ValidationError):
            Rubric(
                total_score=Decimal("100"),
                criteria=[
                    RubricCriterion(
                        id="completion",
                        name="完成度",
                        max_score=Decimal("100"),
                    )
                ],
                score_bands=[
                    RubricScoreBand(
                        id="basic",
                        name="基本完成",
                        min_score=Decimal("60"),
                        max_score=Decimal("80"),
                    ),
                    RubricScoreBand(
                        id="good",
                        name="完成良好",
                        min_score=Decimal("70"),
                        max_score=Decimal("90"),
                    ),
                ],
            )

    def test_applies_deterministic_penalties(self) -> None:
        rubric = Rubric(
            total_score=Decimal("100"),
            late_penalty_points=Decimal("5"),
            resubmission_penalty_points=Decimal("2"),
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容",
                    max_score=Decimal("70"),
                ),
                RubricCriterion(
                    id="analysis",
                    name="分析",
                    max_score=Decimal("30"),
                ),
            ],
        )
        decision = GradeDecision(
            criterion_scores=[
                GradeCriterion(criterion_id="content", score=Decimal("62.04")),
                GradeCriterion(criterion_id="analysis", score=Decimal("27.96")),
            ],
            raw_score=Decimal("0"),
            final_score=Decimal("0"),
            feedback="报告完整，分析仍可加强。",
            confidence=0.9,
        )

        result = GradeValidator().validate_and_adjust(
            decision,
            rubric,
            is_delay=True,
            is_resubmission=True,
        )

        self.assertEqual(result.raw_score, Decimal("90.0"))
        self.assertEqual(result.final_score, Decimal("83.0"))
        self.assertEqual(len(result.adjustments), 2)

    def test_rejects_unknown_criterion(self) -> None:
        rubric = Rubric(
            total_score=Decimal("10"),
            criteria=[
                RubricCriterion(id="known", name="已知", max_score=Decimal("10"))
            ],
        )
        decision = GradeDecision(
            criterion_scores=[
                GradeCriterion(criterion_id="invented", score=Decimal("10"))
            ],
            raw_score=Decimal("10"),
            final_score=Decimal("10"),
            feedback="评语",
            confidence=0.8,
        )

        with self.assertRaises(GradeValidationError):
            GradeValidator().validate_and_adjust(
                decision,
                rubric,
                is_delay=False,
                is_resubmission=False,
            )

    def test_maps_unique_criterion_name_to_id(self) -> None:
        rubric = Rubric(
            total_score=Decimal("10"),
            criteria=[
                RubricCriterion(
                    id="completion",
                    name="阶段任务完成情况梳理",
                    max_score=Decimal("10"),
                )
            ],
        )
        decision = GradeDecision(
            criterion_scores=[
                GradeCriterion(
                    criterion_id="阶段任务完成情况梳理",
                    score=Decimal("9"),
                )
            ],
            raw_score=Decimal("9"),
            final_score=Decimal("9"),
            feedback="完成情况清晰。",
            confidence=0.8,
        )

        result = GradeValidator().validate_and_adjust(
            decision,
            rubric,
            is_delay=False,
            is_resubmission=False,
        )

        self.assertEqual(result.criterion_scores[0].criterion_id, "completion")


class LlmClientTests(IsolatedAsyncioTestCase):
    async def test_spaces_concurrent_request_starts(self) -> None:
        client = LlmClient()
        starts: list[float] = []

        async def reserve_slot() -> None:
            await client._wait_for_request_slot(0.03)
            starts.append(asyncio.get_running_loop().time())

        await asyncio.gather(*(reserve_slot() for _ in range(3)))

        self.assertEqual(len(starts), 3)
        self.assertGreaterEqual(starts[1] - starts[0], 0.02)
        self.assertGreaterEqual(starts[2] - starts[1], 0.02)

    async def test_explicit_six_section_rubric_is_parsed_locally(self) -> None:
        client = LlmClient()
        client._chat_json = AsyncMock()
        source = """
第二阶段进度报告评分细则（总分 100 分）

一、评分原则
1. 先判断完成阶段，再在对应阶段内评分。
2. 有真实成果原则上不低于 60 分。

二、完成阶段与建议分数区间
（一）优秀完成阶段：90～100 分
1. 三个模块均已基本完成。
- 95～97：实现完整，异常测试充分。
（二）良好完成阶段：80～89 分
1. 主体功能基本完成。
（三）基本完成阶段：70～79 分
1. 至少两个核心模块完成。
（四）最低完成阶段：60～69 分
1. 有真实工作但完成度较低。
（五）严重不足阶段：60 分以下
1. 基本没有新增内容。

三、评分维度
1. 阶段任务完成情况梳理：60 分
- 提供实现状态和运行结果。
2. 测试环境、方法与结果：40 分
- 提供日志、抓包或测试输出。

四、强制章节
1. 第二阶段任务及完成情况。
2. 测试环境、方法与结果。

五、扣分及限制规则
1. 没有测试证据时总分不超过 79 分。

六、分数校准要求
1. 90 分以上必须有充分测试证据。
""".strip()

        rubric = await client.normalize_rubric(
            RubricNormalizeRequest(
                source_text=source,
                total_score=Decimal("100"),
            )
        )

        client._chat_json.assert_not_awaited()
        self.assertEqual(len(rubric.criteria), 2)
        self.assertEqual(len(rubric.score_bands), 5)
        self.assertEqual(rubric.score_bands[0].min_score, Decimal("90"))
        self.assertEqual(rubric.score_bands[1].max_score, Decimal("90"))
        self.assertEqual(rubric.score_bands[-1].max_score, Decimal("60"))
        self.assertEqual(len(rubric.required_sections), 2)
        self.assertEqual(len(rubric.global_deduction_rules), 1)
        self.assertEqual(len(rubric.calibration_rules), 1)

    async def test_normalize_prompt_extracts_global_rules(self) -> None:
        client = LlmClient()
        client._chat_json = AsyncMock(
            return_value={
                "title": "阶段报告评分细则",
                "total_score": 100,
                "criteria": [
                    {
                        "id": "completion",
                        "name": "完成度",
                        "max_score": 100,
                    }
                ],
                "overall_requirements": ["以完成度为主"],
                "score_bands": [
                    {
                        "id": "good",
                        "name": "完成良好",
                        "min_score": 80,
                        "max_score": 100,
                        "requirements": ["主要任务完成"],
                    }
                ],
                "required_sections": ["测试结果"],
                "global_deduction_rules": ["无证据不得进入高分档"],
                "calibration_rules": ["不设置固定人数配额"],
            }
        )

        rubric = await client.normalize_rubric(
            RubricNormalizeRequest(
                source_text="按完成度分档，并检查强制章节和全局扣分项。",
                total_score=Decimal("100"),
            )
        )

        prompt = client._chat_json.await_args.args[1]
        self.assertIn("overall_requirements", prompt)
        self.assertIn("score_bands", prompt)
        self.assertIn("required_sections", prompt)
        self.assertIn("global_deduction_rules", prompt)
        self.assertIn("calibration_rules", prompt)
        self.assertEqual(rubric.score_bands[0].id, "good")

    async def test_normalize_retries_when_model_returns_schema(self) -> None:
        client = LlmClient()
        client._chat_json = AsyncMock(
            side_effect=[
                Rubric.model_json_schema(),
                {
                    "title": "评分细则",
                    "total_score": 100,
                    "criteria": [
                        {
                            "id": "completion",
                            "name": "完成度",
                            "max_score": 100,
                        }
                    ],
                },
            ]
        )

        rubric = await client.normalize_rubric(
            RubricNormalizeRequest(
                source_text="按完成度评分。",
                total_score=Decimal("100"),
            )
        )

        self.assertEqual(rubric.criteria[0].id, "completion")
        self.assertEqual(client._chat_json.await_count, 2)
        retry_prompt = client._chat_json.await_args_list[1].args[1]
        self.assertIn("不要返回 JSON Schema 定义", retry_prompt)

    async def test_normalize_restores_platform_criteria_when_model_omits_them(
        self,
    ) -> None:
        client = LlmClient()
        client._chat_json = AsyncMock(
            return_value={
                "title": "阶段报告评分细则",
                "total_score": 100,
                "criteria": [],
            }
        )
        platform_criterion = RubricCriterion(
            id="platform-total",
            name="总评",
            max_score=Decimal("100"),
            platform_score_attr_id="score-attribute-1",
        )

        rubric = await client.normalize_rubric(
            RubricNormalizeRequest(
                source_text="按照报告完成情况评分。",
                total_score=Decimal("100"),
                platform_criteria=[platform_criterion],
            )
        )

        self.assertEqual(rubric.criteria, [platform_criterion])
        self.assertEqual(client._chat_json.await_count, 1)

    async def test_normalize_reports_friendly_error_for_empty_criteria(
        self,
    ) -> None:
        client = LlmClient()
        client._chat_json = AsyncMock(
            return_value={
                "title": "评分细则",
                "total_score": 100,
                "criteria": [],
            }
        )

        with self.assertRaisesRegex(
            LlmError,
            "模型未返回有效评分项",
        ) as context:
            await client.normalize_rubric(
                RubricNormalizeRequest(
                    source_text="按照完成情况评分。",
                    total_score=Decimal("100"),
                )
            )

        self.assertNotIn("pydantic.dev", str(context.exception))

    async def test_missing_confidence_uses_neutral_default(
        self,
    ) -> None:
        client = LlmClient()
        client._chat_json = AsyncMock(
            return_value={
                "criterion_scores": [
                    {
                        "criterion_id": "content",
                        "score": 80,
                        "evidence": ["完成了主要实验"],
                        "deductions": ["缺少误差分析"],
                        "explanation": "主体完整，但分析不足。",
                    }
                ],
                "raw_score": 80,
                "final_score": 80,
                "feedback": "建议补充误差分析。",
            }
        )
        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容",
                    max_score=Decimal("100"),
                )
            ],
        )

        decision = await client.grade(rubric, "报告内容")

        self.assertEqual(decision.confidence, 0.5)
        self.assertFalse(decision.needs_review)
        self.assertEqual(decision.review_reasons, [])

    async def test_needs_review_without_reason_is_retried(self) -> None:
        client = LlmClient()
        response = {
            "criterion_scores": [
                {
                    "criterion_id": "content",
                    "score": 80,
                    "evidence": [],
                    "deductions": [],
                    "explanation": "",
                }
            ],
            "raw_score": 80,
            "final_score": 80,
            "feedback": "建议补充实验依据。",
            "confidence": 0.6,
            "needs_review": True,
            "review_reasons": [],
        }
        client._chat_json = AsyncMock(
            side_effect=[
                response,
                {
                    **response,
                    "review_reasons": ["缺少可核验的实验日志"],
                },
            ]
        )
        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="content",
                    name="内容",
                    max_score=Decimal("100"),
                )
            ],
        )

        decision = await client.grade(rubric, "报告内容")

        self.assertEqual(decision.review_reasons, ["缺少可核验的实验日志"])
        self.assertEqual(client._chat_json.await_count, 2)

    async def test_stage_completion_identifies_stage_before_scoring(self) -> None:
        client = LlmClient()
        client._chat_json = AsyncMock(
            return_value={
                "criterion_scores": [
                    {
                        "criterion_id": "completion",
                        "score": 85,
                        "evidence": ["核心模块已有可运行结果"],
                        "deductions": ["当前阶段仍缺少一个边界用例"],
                        "explanation": "核心实施阶段大部分任务已完成。",
                    }
                ],
                "raw_score": 85,
                "final_score": 85,
                "detected_stage_id": "core",
                "detected_stage_name": "核心实施阶段",
                "stage_evidence": ["报告给出了核心模块实现和初步测试结果"],
                "feedback": "当前阶段完成度较高，建议补充边界测试。",
                "confidence": 0.9,
            }
        )
        rubric = Rubric(
            total_score=Decimal("100"),
            grading_mode="stage_completion",
            stages=[
                RubricStage(
                    id="foundation",
                    name="基础准备阶段",
                ),
                RubricStage(
                    id="core",
                    name="核心实施阶段",
                ),
            ],
            criteria=[
                RubricCriterion(
                    id="completion",
                    name="当前阶段任务完成度",
                    max_score=Decimal("100"),
                )
            ],
        )

        decision = await client.grade(rubric, "核心模块已实现，并完成初步测试。")

        self.assertEqual(decision.detected_stage_id, "core")
        prompt = client._chat_json.await_args.args[1]
        self.assertIn("先根据报告中已经完成且可核验的成果", prompt)
        self.assertIn("不因后续阶段尚未开始或尚未完成而扣分", prompt)

    async def test_stage_name_is_mapped_to_stage_id(self) -> None:
        client = LlmClient()
        client._chat_json = AsyncMock(
            return_value={
                "criterion_scores": [
                    {
                        "criterion_id": "completion",
                        "score": 70,
                    }
                ],
                "raw_score": 70,
                "final_score": 70,
                "detected_stage_name": "基础准备阶段",
                "stage_evidence": ["已完成需求梳理"],
                "feedback": "基础准备已完成。",
                "confidence": 0.8,
            }
        )
        rubric = Rubric(
            total_score=Decimal("100"),
            grading_mode="stage_completion",
            stages=[
                RubricStage(
                    id="foundation",
                    name="基础准备阶段",
                )
            ],
            criteria=[
                RubricCriterion(
                    id="completion",
                    name="当前阶段任务完成度",
                    max_score=Decimal("100"),
                )
            ],
        )

        decision = await client.grade(rubric, "已完成需求梳理。")

        self.assertEqual(decision.detected_stage_id, "foundation")

    async def test_score_band_is_inferred_from_criterion_total(self) -> None:
        client = LlmClient()
        client._chat_json = AsyncMock(
            return_value={
                "criterion_scores": [
                    {
                        "criterion_id": "completion",
                        "score": 86,
                        "evidence": ["核心任务已经完成并提供测试日志"],
                    }
                ],
                "raw_score": 86,
                "final_score": 86,
                "feedback": "完成良好，仍可补充边界测试。",
                "confidence": 0.9,
            }
        )
        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="completion",
                    name="完成度",
                    max_score=Decimal("100"),
                )
            ],
            score_bands=[
                RubricScoreBand(
                    id="good",
                    name="完成良好",
                    min_score=Decimal("80"),
                    max_score=Decimal("90"),
                ),
                RubricScoreBand(
                    id="excellent",
                    name="高质量完成",
                    min_score=Decimal("90"),
                    max_score=Decimal("100"),
                ),
            ],
        )

        decision = await client.grade(rubric, "核心任务已经完成。")

        self.assertEqual(decision.detected_score_band_id, "good")
        self.assertEqual(decision.detected_score_band_name, "完成良好")
        self.assertEqual(
            decision.score_band_evidence,
            ["核心任务已经完成并提供测试日志"],
        )
        prompt = client._chat_json.await_args.args[1]
        self.assertIn("先依据总体要求、强制章节、全局扣分规则", prompt)
        self.assertIn("不是人数配额", prompt)

    async def test_score_outside_selected_band_is_corrected_locally(self) -> None:
        client = LlmClient()
        base_response = {
            "criterion_scores": [
                {
                    "criterion_id": "completion",
                    "score": 85,
                    "evidence": ["主要任务完成"],
                }
            ],
            "raw_score": 85,
            "final_score": 85,
            "detected_score_band_id": "excellent",
            "score_band_evidence": ["主要任务完成"],
            "feedback": "完成良好。",
            "confidence": 0.8,
        }
        client._chat_json = AsyncMock(return_value=base_response)
        rubric = Rubric(
            total_score=Decimal("100"),
            criteria=[
                RubricCriterion(
                    id="completion",
                    name="完成度",
                    max_score=Decimal("100"),
                )
            ],
            score_bands=[
                RubricScoreBand(
                    id="good",
                    name="完成良好",
                    min_score=Decimal("80"),
                    max_score=Decimal("90"),
                ),
                RubricScoreBand(
                    id="excellent",
                    name="高质量完成",
                    min_score=Decimal("90"),
                    max_score=Decimal("100"),
                ),
            ],
        )

        decision = await client.grade(rubric, "主要任务完成。")

        self.assertEqual(decision.detected_score_band_id, "good")
        self.assertEqual(decision.detected_score_band_name, "完成良好")
        self.assertEqual(client._chat_json.await_count, 1)

    def test_parses_json_surrounded_by_explanation(self) -> None:
        parsed = _parse_json_object(
            '以下是结果：\n{"score": 90, "feedback": "完成良好"}\n请查收。'
        )

        self.assertEqual(parsed["score"], 90)
