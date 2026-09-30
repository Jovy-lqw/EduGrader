import type { Rubric } from "./types";

export type RubricTemplate = {
  id: string;
  label: string;
  summary: string;
  rubric: Rubric;
  builtIn: boolean;
  updatedAt?: string;
};

const CUSTOM_TEMPLATE_STORAGE_KEY = "edugrader.custom-rubric-templates.v1";

const stageTwoProgressRubric: Rubric = {
  title: "第二阶段进度报告评分细则（80～100 分制）",
  source_text: "",
  total_score: 100,
  grading_mode: "holistic",
  stages: [],
  stage_scoring_instruction: "",
  overall_requirements: [
    "先判断第二阶段任务完成档位，再在对应档位内进行分项评分。",
    "重点评价第二阶段实际完成度、可验证成果和报告与代码的一致性。",
    "不因第三阶段任务尚未开展而扣分。",
    "所有完成评分的报告最终成绩限定在 80～100 分，任何扣分、封顶或校准均不得使总分低于 80 分。",
    "同一完成档位内，学生分差原则上控制在 1～3 分；只有完成度或证据存在明显差异时才扩大分差。",
    "不机械规定各档人数。90 分以上必须有完整实现和充分证据，95 分以上必须有明显突出的成果。",
    "内容无法识别、身份冲突、明显弄虚作假或报告与代码严重矛盾时进入人工复核；人工确认评分后仍按 80～100 分区间执行。",
  ],
  score_bands: [
    {
      id: "excellent",
      name: "突出完成",
      min_score: 95,
      max_score: 100,
      description: "三个模块完整联调，设计、实现、测试和分析均有高质量证据。",
      requirements: [
        "连接管理、可靠数据传输、流量控制三个模块完整实现并形成稳定链路",
        "核心机制说明准确，正常场景、主要异常场景和边界场景测试充分",
        "提供抓包、日志、trace、测试输出及 ≥100MB 大文件传输测试",
        "报告、代码、测试结果和需求追踪表基本一致",
        "95～97：实现和证据完整，分析深入，仅有轻微不足",
        "98～100：还有高质量性能分析、系统性验证或额外改进成果",
      ],
    },
    {
      id: "good",
      name: "良好完成",
      min_score: 90,
      max_score: 95,
      description: "三个模块主体功能完整，主要流程稳定，测试证据较充分。",
      requirements: [
        "三个核心模块均已实现，允许存在少量边界场景或稳定性问题",
        "有正常场景和主要异常场景测试，并提供可核验依据",
        "如实说明已实现、存在 bug 和尚未开发的内容",
        "报告结构完整，设计与代码基本一致",
      ],
    },
    {
      id: "basic",
      name: "基本完成",
      min_score: 85,
      max_score: 90,
      description: "主要功能已经实现，但完整性、联调质量或测试证据仍有明显不足。",
      requirements: [
        "至少两个核心模块完成主要功能，另一模块已有真实实现或联调进展",
        "或三个模块均有实现，但完整性、稳定性或联调程度不足",
        "可以展示真实运行结果，但测试范围有限",
        "能够说明当前进展和问题，但证据、分析或设计深度不足",
      ],
    },
    {
      id: "minimum",
      name: "需要改进",
      min_score: 80,
      max_score: 85,
      description: "存在真实第二阶段工作，但核心功能、证据或报告完整性不足。",
      requirements: [
        "仅完成一个主要模块，多个模块只有基础框架，或联调尚未形成有效链路",
        "测试证据较少，报告结构或必需章节存在较多缺失",
        "缺少有效第二阶段新增内容、报告与代码明显不一致等严重问题经复核后也归入本档",
        "本档最低为 80 分，不因文字表达一般、任务缺项或证据不足给出 80 分以下成绩",
      ],
    },
  ],
  required_sections: [
    "第一阶段内容",
    "第二阶段任务及完成情况",
    "连接管理设计",
    "可靠数据传输设计",
    "流量控制设计",
    "测试环境、方法与结果",
    "问题分析和解决过程",
    "AI 协作及人工验证记录",
    "Git 提交标识",
    "尚未解决的问题",
    "第三阶段工作计划",
  ],
  criteria: [
    {
      id: "stage_progress",
      name: "阶段任务完成情况梳理",
      description: "本项 24～30 分。连接管理、可靠数据传输、流量控制及需求追踪构成 24 分基础分；根据三个模块的实际完成度、联调程度和完成状态说明质量，增加 0～6 分。",
      max_score: 30,
      required_evidence: ["三个模块的实际完成状态", "需求追踪表", "已实现、存在 bug 和未开发内容说明"],
      deduction_rules: ["完成状态与证据不一致", "只写计划而无实际成果", "本项扣分后不得低于 24 分"],
      platform_score_attr_id: null,
    },
    {
      id: "module_design",
      name: "模块设计说明",
      description: "本项 20～25 分。关键模块有真实设计说明可得 20 分基础分；根据连接管理、可靠传输、流量控制的机制准确性，以及流程图、状态机图或伪代码质量，增加 0～5 分。连接管理关注状态机、三次握手、关闭流程、ISN、TIME-WAIT及功能裁剪；可靠传输关注序号确认、缓冲区、校验和、RFC6298、RTT/RTO、Karn算法、超时重传及基础快速重传；流量控制关注 rwnd、缓冲区大小、零窗口探测和糊涂窗口避免。",
      max_score: 25,
      required_evidence: ["关键机制设计说明", "流程图、状态机图或伪代码", "设计与提交代码的对应关系"],
      deduction_rules: ["设计与代码不一致", "关键概念错误", "大段粘贴源码代替说明", "本项扣分后不得低于 20 分"],
      platform_score_attr_id: null,
    },
    {
      id: "testing",
      name: "测试环境、方法与结果",
      description: "本项 20～25 分。提供真实测试过程可得 20 分基础分；根据环境和网络参数、正常场景、握手丢包/FIN丢包/失序报文/零窗口等异常测试、抓包日志及 ≥100MB 大文件传输测试的完整程度，增加 0～5 分。",
      max_score: 25,
      required_evidence: ["测试环境和网络模拟参数", "正常与异常场景测试结果", "抓包、日志、trace 或测试输出", "≥100MB 大文件传输测试"],
      deduction_rules: ["仅声称全部通过而无证据", "缺少关键异常场景", "结果与结论不一致", "本项扣分后不得低于 20 分"],
      platform_score_attr_id: null,
    },
    {
      id: "problem_solving",
      name: "问题分析与解决过程",
      description: "本项 8～10 分。记录真实问题或未解决事项可得 8 分基础分；能够完整说明典型 bug 的现象、定位、根因、修复和验证过程，增加 0～2 分。",
      max_score: 10,
      required_evidence: ["典型 bug 定位与根因", "修复及验证结果", "尚未解决的问题"],
      deduction_rules: ["隐瞒问题", "只有结果没有定位过程", "修复后未验证", "本项扣分后不得低于 8 分"],
      platform_score_attr_id: null,
    },
    {
      id: "ai_version_plan",
      name: "AI 使用记录、版本与下一阶段计划",
      description: "本项 8～10 分。基本说明 AI 使用、版本信息和后续计划可得 8 分基础分；完整记录 AI 建议、人工修改或拒绝、验证方法、Git 提交标识及第三阶段计划，增加 0～2 分。",
      max_score: 10,
      required_evidence: ["AI 协作与人工判断记录", "人工验证结果", "Git 提交标识", "第三阶段计划"],
      deduction_rules: ["缺少 AI 使用记录", "缺少 Git 提交标识", "缺少下一阶段计划", "本项扣分后不得低于 8 分"],
      platform_score_attr_id: null,
    },
  ],
  global_deduction_rules: [
    "全部分项扣分后，最终总分必须限制在 80～100 分；若计算结果低于 80 分，按 80 分计。",
    "没有测试证据，仅声称“全部通过”：测试维度按 20 分计，总分最高不超过 89 分。",
    "设计描述与提交代码明显不一致：模块设计维度按 20 分计，总分最高不超过 84 分，并进入人工复核。",
    "缺少 AI 使用记录、Git 提交标识或下一阶段计划：在该维度的 8～10 分区间内扣分，最低按 8 分计。",
    "大段粘贴源码代替设计说明：模块设计维度最高不超过 21 分，但最低按 20 分计。",
    "混淆字节序号与报文序号、RTO 重传与快速重传等关键概念：每处扣 1～2 分，模块设计维度最低按 20 分计。",
    "对同一个问题原则上不重复扣分。",
    "虚构测试、隐瞒问题、直接复制旧报告或提交内容无法识别：进入人工复核；确认需要评分时原则上归入 80～84 分档，不得低于 80 分。",
  ],
  calibration_rules: [
    "以 82 分、87 分、92 分、97 分分别作为需要改进、基本完成、良好完成、突出完成档位的参考锚点。",
    "先确定完成档位，再根据报告质量、测试证据和问题分析在档位内上下调整。",
    "80～84 分用于核心功能、报告结构或证据存在明显缺失的情况。",
    "85～89 分用于主要功能基本完成，但联调、设计说明或测试证据不够完整的情况。",
    "90～94 分必须具备较完整实现、较充分测试证据及基本一致的报告与代码。",
    "95～100 分仅用于完成度、证据质量和分析深度均明显突出的报告，100 分要求所有评分维度均无实质缺项。",
    "同一档位内分差原则上控制在 1～3 分，最终成绩不得低于 80 分。",
    "不按照固定比例强制制造高分或低分，批量评分后如分布异常，应重新检查评分尺度是否一致。",
  ],
  late_rule: "",
  late_penalty_points: 0,
  resubmission_rule: "",
  resubmission_penalty_points: 0,
  feedback_style: "先说明完成档位和关键证据，再说明提升分依据、主要不足及下一阶段建议；最终成绩限定在 80～100 分。",
};

stageTwoProgressRubric.source_text = describeRubric(stageTwoProgressRubric);

const stageThreeProgressRubric: Rubric = {
  title: "第三阶段进度报告评分细则（80～100 分制）",
  source_text: "",
  total_score: 100,
  grading_mode: "holistic",
  stages: [],
  stage_scoring_instruction: "",
  overall_requirements: [
    "先判断第三阶段任务完成档位，再在对应档位内进行分项评分。",
    "重点评价基础 Reno 拥塞控制、全协议联调、功能复测、性能实验及最终成果的可复现性。",
    "第三阶段报告采用累积方式，应保留第一、第二阶段成果，并清楚标识第三阶段新增和修正内容。",
    "基础 Reno 是第三阶段必做内容；完整 Reno 快速恢复、NewReno、SACK/RACK、CUBIC 等挑战任务属于选做，不因未完成而扣除基础分。",
    "所有完成评分的报告最终成绩限定在 80～100 分，任何扣分、封顶或校准均不得使总分低于 80 分。",
    "同一完成档位内，学生分差原则上控制在 1～3 分；95 分以上必须有准确的窗口演化证据、可复现实验和深入分析。",
    "内容无法识别、关键结果无法复现、明显弄虚作假或报告与代码严重矛盾时进入人工复核；人工确认评分后仍按 80～100 分区间执行。",
  ],
  score_bands: [
    {
      id: "excellent",
      name: "突出完成",
      min_score: 95,
      max_score: 100,
      description: "基础 Reno、全协议联调和性能实验均完整，原始证据可复现且分析深入。",
      requirements: [
        "慢启动、拥塞避免、RTO 丢包响应和三次重复 ACK 响应实现正确",
        "能够用代码和原始 trace 逐次解释 cwnd、ssthresh、rwnd 与 FlightSize 的变化",
        "连接管理、可靠传输、流量控制和基础 Reno 完整联调并通过充分复测",
        "至少选择两类变量开展控制实验，保存原始数据、日志、trace 和绘图脚本",
        "最终代码、Git 版本、构建运行说明、报告和展示材料完整且可复现",
        "95～97：必做内容与证据完整，分析准确，仅有轻微不足",
        "98～100：还有高质量重复实验、异常分析、工程改进或经独立验证的挑战成果",
      ],
    },
    {
      id: "good",
      name: "良好完成",
      min_score: 90,
      max_score: 95,
      description: "基础 Reno 主体功能和最终联调完成，测试及性能证据较充分。",
      requirements: [
        "基础 Reno 核心机制均有真实实现，允许存在少量边界场景或稳定性问题",
        "主要功能完成复测，rwnd 与 cwnd 的联合约束基本正确",
        "已开展至少两类变量的性能对照实验，并提供主要原始证据",
        "最终成果基本可复现，报告、代码、图表和 Git 版本基本一致",
      ],
    },
    {
      id: "basic",
      name: "基本完成",
      min_score: 85,
      max_score: 90,
      description: "基础 Reno 和综合测试已有真实成果，但机制完整性、实验质量或复现材料仍有明显不足。",
      requirements: [
        "慢启动、拥塞避免或丢包响应中的大部分机制已经实现",
        "已有全协议联调和真实运行结果，但异常场景或回归测试范围有限",
        "已开展性能实验，但变量控制、重复次数、统计方法或分析深度不足",
        "能够如实说明遗留问题、失败证据和后续改进方向",
      ],
    },
    {
      id: "minimum",
      name: "需要改进",
      min_score: 80,
      max_score: 85,
      description: "存在真实第三阶段工作，但基础 Reno、联调、性能实验或成果复现存在较大缺失。",
      requirements: [
        "基础 Reno 仅完成部分机制，或窗口更新与丢包响应尚未形成完整链路",
        "综合测试、原始数据、绘图脚本或构建运行说明缺失较多",
        "报告能够提供部分代码、日志、trace 或失败实验，证明开展了第三阶段工作",
        "关键结果无法复现或报告与代码明显不一致等严重问题经复核后也归入本档",
        "本档最低为 80 分，不因未完成选做挑战任务而扣分",
      ],
    },
  ],
  required_sections: [
    "第一、第二阶段成果及第三阶段新增内容",
    "第三阶段任务及完成情况",
    "基础 Reno 拥塞控制设计与实现",
    "全协议联调与功能复测",
    "性能实验设计、原始数据与结果分析",
    "典型问题、原因分析与解决过程",
    "AI 协作及人工验证记录",
    "最终 Git 提交标识、构建与运行说明",
    "尚未解决的问题、项目总结与后续改进建议",
  ],
  criteria: [
    {
      id: "reno_implementation",
      name: "基础 Reno 设计与实现",
      description: "本项 24～30 分。提供基础 Reno 的真实实现和基本说明可得 24 分基础分；根据 cwnd、ssthresh、rwnd、FlightSize 的语义准确性，慢启动、拥塞避免、RTO 与三次重复 ACK 丢包响应的完整性，以及 RFC 5681 对应关系，增加 0～6 分。",
      max_score: 30,
      required_evidence: ["关键变量与状态设计", "窗口更新和丢包响应代码对应关系", "ACK、重复 ACK、RTO、重传及状态切换 trace"],
      deduction_rules: ["混淆 rwnd、cwnd 或 FlightSize", "SYN 或 SYN-ACK 错误增加 cwnd", "窗口更新比 Reno 规则更激进", "本项扣分后不得低于 24 分"],
      platform_score_attr_id: null,
    },
    {
      id: "integration_testing",
      name: "全协议联调与功能复测",
      description: "本项 16～20 分。提供连接管理、可靠传输、流量控制和基础 Reno 的真实联调结果可得 16 分基础分；根据正常、丢包、时延、RTO、重复 ACK、小 rwnd 及 ≥100MB 传输等场景的覆盖和证据质量，增加 0～4 分。",
      max_score: 20,
      required_evidence: ["最终代码上的功能复测结果", "正常、异常和边界场景证据", "日志、抓包、trace 或自动测试输出"],
      deduction_rules: ["只展示单模块结果而无最终联调", "缺少关键丢包或窗口约束场景", "结果与代码版本不对应", "本项扣分后不得低于 16 分"],
      platform_score_attr_id: null,
    },
    {
      id: "performance_evaluation",
      name: "性能实验与结果分析",
      description: "本项 16～20 分。开展真实性能实验并保留基本结果可得 16 分基础分；根据至少两类变量的对照设计、重复次数与统计方法、吞吐率等指标、原始数据和绘图脚本，以及从协议机制和代码实现解释结果的质量，增加 0～4 分。",
      max_score: 20,
      required_evidence: ["至少两类实验变量", "环境、参数、重复次数和统计方法", "原始数据、日志、trace 和绘图脚本", "带单位、图例和说明的结果图"],
      deduction_rules: ["对照实验同时改变无关变量", "缺少原始数据或绘图脚本", "只描述趋势而不解释原因", "本项扣分后不得低于 16 分"],
      platform_score_attr_id: null,
    },
    {
      id: "reproducibility",
      name: "最终成果、版本与可复现性",
      description: "本项 12～15 分。提交最终代码、Git 版本和基本运行说明可得 12 分基础分；根据源代码可编译性、构建与运行步骤、测试脚本、材料命名、版本对应关系及主要图表复现程度，增加 0～3 分。",
      max_score: 15,
      required_evidence: ["最终可编译源代码", "最终 Git 提交标识", "构建与运行说明", "测试脚本和图表复现材料"],
      deduction_rules: ["缺少明确版本", "构建或主要实验无法按说明复现", "提交编译产物、无关大文件或敏感信息", "本项扣分后不得低于 12 分"],
      platform_score_attr_id: null,
    },
    {
      id: "analysis_ai_summary",
      name: "问题分析、AI 验证与阶段总结",
      description: "本项 12～15 分。记录真实问题、AI 使用和项目总结可得 12 分基础分；根据典型问题的现象、定位、根因、修复验证，AI 建议的人工核验，以及局限性和后续改进建议的完整程度，增加 0～3 分。",
      max_score: 15,
      required_evidence: ["典型问题定位与修复验证", "AI 建议、人工修改或拒绝及验证记录", "尚未解决问题", "项目总结与后续改进建议"],
      deduction_rules: ["隐瞒失败或异常结果", "AI 结论无人工验证", "只有结果没有定位过程", "本项扣分后不得低于 12 分"],
      platform_score_attr_id: null,
    },
  ],
  global_deduction_rules: [
    "全部分项扣分后，最终总分必须限制在 80～100 分；若计算结果低于 80 分，按 80 分计。",
    "没有基础 Reno 的代码对应关系或原始 trace，仅描述预期行为：基础 Reno 维度按 24 分计，总分最高不超过 89 分。",
    "混淆 rwnd、cwnd、ssthresh 与 FlightSize，或窗口更新明显不符合 RFC 5681：基础 Reno 维度最高不超过 25 分，最低按 24 分计。",
    "性能测试未选择至少两类变量，或没有原始数据和绘图脚本：性能实验维度按 16 分计，总分最高不超过 89 分。",
    "最终代码、图表或主要实验无法按提交说明复现：可复现性维度按 12 分计，总分最高不超过 84 分，并进入人工复核。",
    "未完成完整 Reno、NewReno、SACK/RACK、CUBIC 等挑战任务不扣分；挑战成果只有在设计、代码、独立测试和对比证据完整时才作为提升分依据。",
    "大段粘贴源码代替设计说明，或图表无法追溯到本人实验：对应维度不得获得提升分。",
    "对同一个问题原则上不重复扣分。",
    "虚构测试、原始数据、Git 或 AI 记录，或将未实现机制写成已完成：进入人工复核；确认需要评分时原则上归入 80～84 分档，不得低于 80 分。",
  ],
  calibration_rules: [
    "以 82 分、87 分、92 分、97 分分别作为需要改进、基本完成、良好完成、突出完成档位的参考锚点。",
    "先确定完成档位，再根据基础 Reno、联调证据、性能实验和可复现性在档位内上下调整。",
    "80～84 分用于基础 Reno、综合测试、性能实验或复现材料存在较大缺失的情况。",
    "85～89 分用于必做内容已有真实成果，但机制完整性、测试范围或分析深度不足的情况。",
    "90～94 分必须具备较完整的基础 Reno、最终联调、性能对照实验和版本对应证据。",
    "95～100 分必须能够用代码与原始 trace 解释关键窗口更新，且实验、图表和最终成果可复现。",
    "挑战任务只用于档位内提升，不替代基础 Reno 和必做实验；最终成绩不得超过 100 分。",
    "同一档位内分差原则上控制在 1～3 分，最终成绩不得低于 80 分。",
  ],
  late_rule: "",
  late_penalty_points: 0,
  resubmission_rule: "",
  resubmission_penalty_points: 0,
  feedback_style: "先说明第三阶段完成档位和基础 Reno 证据，再评价联调、性能实验、可复现性及主要改进项；最终成绩限定在 80～100 分。",
};

stageThreeProgressRubric.source_text = describeRubric(stageThreeProgressRubric);

const finalCourseReportRubric: Rubric = {
  title: "最终课程报告评分细则（80～100 分制）",
  source_text: "",
  total_score: 100,
  grading_mode: "holistic",
  stages: [],
  stage_scoring_instruction: "",
  overall_requirements: [
    "按照指导书第 7.2、7.3 节的报告要求和第 8.4 节的评分比例评价最终课程报告。",
    "重点评价报告内容完整性、技术正确性、设计实现测试的一致性，以及图表与实验材料的可追溯性。",
    "最终报告评价以必做内容为基础；挑战任务属于选做，不因未完成而扣分，也不得用挑战内容替代基础 Reno 等必做章节。",
    "所有完成评分的报告最终成绩限定在 80～100 分，任何扣分、封顶或校准均不得使总分低于 80 分。",
    "引用、实验数据、图表、AI 使用说明和 Git 标识必须真实；无法核验的关键成果应进入人工复核。",
    "同一完成档位内，学生分差原则上控制在 1～3 分；95 分以上必须做到内容完整、技术准确、证据可追溯且表达规范。",
  ],
  score_bands: [
    {
      id: "excellent",
      name: "突出完成",
      min_score: 95,
      max_score: 100,
      description: "报告章节完整，技术准确，设计、实现、测试和证据形成可追溯闭环。",
      requirements: [
        "课程要求的必做章节完整，任务分析、架构、总体设计和四个核心模块层次清晰",
        "连接管理、可靠传输、流量控制与基础 Reno 的技术表述准确且对应真实代码",
        "功能和性能实验方法严谨，原始数据、trace、脚本与图表可追溯",
        "典型问题、AI 人工核验、总结和参考文献真实完整",
        "95～97：各项完整准确，仅有轻微表达或格式不足",
        "98～100：还有突出的系统性分析、复现实证或高质量对比研究",
      ],
    },
    {
      id: "good",
      name: "良好完成",
      min_score: 90,
      max_score: 95,
      description: "报告主体完整且技术基本正确，设计、实现、测试和图表具有较好对应关系。",
      requirements: [
        "必做章节和主要技术内容齐全，允许存在少量细节遗漏",
        "核心机制说明基本准确，报告与代码及实验结果基本一致",
        "图表和测试结果有较充分的来源材料",
        "AI 使用说明、Git 标识、总结和参考文献基本完整",
      ],
    },
    {
      id: "basic",
      name: "基本完成",
      min_score: 85,
      max_score: 90,
      description: "报告覆盖主要内容，但技术深度、对应关系、图表证据或写作规范存在明显不足。",
      requirements: [
        "大部分必做章节已经完成，但部分章节较薄弱或结构不够清晰",
        "能够说明核心实现和主要测试，存在少量概念错误或证据缺口",
        "图表基本可读，但原始数据、单位、图例或来源说明不够完整",
        "AI 使用、问题分析、参考文献或附录记录存在缺失",
      ],
    },
    {
      id: "minimum",
      name: "需要改进",
      min_score: 80,
      max_score: 85,
      description: "报告有真实项目内容，但章节、技术准确性、证据追溯或格式规范存在较大缺失。",
      requirements: [
        "多个必做章节缺失或主要内容停留在简略描述",
        "设计、实现和测试对应关系较弱，或核心机制存在明显表述错误",
        "图表、实验数据、AI 记录、Git 标识或参考文献缺失较多",
        "关键材料无法核验或报告与代码明显不一致等严重问题经复核后也归入本档",
        "本档最低为 80 分，不因未完成选做挑战任务而扣分",
      ],
    },
  ],
  required_sections: [
    "报告摘要",
    "任务分析与标准依据",
    "已有编程框架的架构分析",
    "协议总体设计",
    "连接管理设计与实现",
    "可靠数据传输设计与实现",
    "流量控制设计与实现",
    "基础 Reno 拥塞控制设计与实现",
    "功能测试、性能测试与结果分析",
    "典型问题及调试过程",
    "挑战任务设计、实现与对比分析（如选做）",
    "AI 辅助过程及人工验证",
    "总结",
    "参考文献",
    "附录：AI 使用说明、主要 Git 提交和测试环境",
  ],
  criteria: [
    {
      id: "content_completeness",
      name: "内容完整性与相互对应",
      description: "本项 40～50 分，对应指导书报告评分的 50%。报告覆盖必做章节并包含真实项目内容可得 40 分基础分；根据任务分析、架构、总体设计、四个核心模块、功能与性能测试、问题调试及总结的完整程度，以及设计、实现和测试的一一对应质量，增加 0～10 分。",
      max_score: 50,
      required_evidence: ["课程要求的必做章节", "设计、实现与测试的对应关系", "代码、Git 版本和实验材料引用", "项目总结与局限性"],
      deduction_rules: ["缺少必做章节", "设计、实现和测试彼此脱节", "大段粘贴源码代替技术说明", "本项扣分后不得低于 40 分"],
      platform_score_attr_id: null,
    },
    {
      id: "technical_correctness",
      name: "技术正确性与逻辑表达",
      description: "本项 16～20 分，对应指导书报告评分的 20%。主要技术内容真实且基本正确可得 16 分基础分；根据 RFC 和课程要求引用的准确性、核心机制说明、重点提炼、逻辑组织及对实现取舍的解释质量，增加 0～4 分。",
      max_score: 20,
      required_evidence: ["标准依据和关键概念", "核心机制与代码对应说明", "实现范围、裁剪和取舍", "实验结论的机制解释"],
      deduction_rules: ["混淆关键 TCP 概念", "基础 Reno 误写成完整 Reno", "将未实现机制写入成果", "本项扣分后不得低于 16 分"],
      platform_score_attr_id: null,
    },
    {
      id: "visuals_traceability",
      name: "图表规范与证据可追溯性",
      description: "本项 12～15 分，对应指导书报告评分的 15%。提供与正文相关的真实图表和实验结果可得 12 分基础分；根据架构图、FSM、流程图、表格和实验图表的清晰度、编号、单位、图例、正文引用，以及追溯到本人代码、原始数据和脚本的完整程度，增加 0～3 分。",
      max_score: 15,
      required_evidence: ["架构图、状态机图或流程图", "规范的表格和实验图表", "原始数据、日志、trace 或绘图脚本来源", "图表与正文结论的对应关系"],
      deduction_rules: ["图表模糊或缺少名称、单位、图例", "图表无法追溯到原始材料", "根据预期行为人工绘制实验结果", "本项扣分后不得低于 12 分"],
      platform_score_attr_id: null,
    },
    {
      id: "ai_validation",
      name: "AI 使用与人工验证说明",
      description: "本项 8～10 分，对应指导书报告评分的 10%。如实说明 AI 的主要使用环节和基本验证方法可得 8 分基础分；根据框架分析、设计、实现、测试诊断和文档一致性检查中的代表性记录，以及人工修改、拒绝和验证证据，增加 0～2 分。",
      max_score: 10,
      required_evidence: ["AI 工具及版本和使用目的", "AI 建议摘要", "人工修改或拒绝内容", "验证方法及关联提交或材料"],
      deduction_rules: ["缺少 AI 使用说明", "AI 结论无人工核验", "记录与代码或材料不一致", "本项扣分后不得低于 8 分"],
      platform_score_attr_id: null,
    },
    {
      id: "writing_format",
      name: "语言、格式与参考文献",
      description: "本项 4～5 分，对应指导书报告评分的 5%。使用指定模板且语言和格式基本规范可得 4 分基础分；章节清晰、表达专业简洁、图表位置与编号规范、引用和参考文献完整，可增加 0～1 分。",
      max_score: 5,
      required_evidence: ["指定报告模板", "规范的章节、图表和表格编号", "正文引用与完整参考文献", "符合要求的文件命名"],
      deduction_rules: ["结构混乱或口语化严重", "图表编号和位置不规范", "正文引用无参考文献", "本项扣分后不得低于 4 分"],
      platform_score_attr_id: null,
    },
  ],
  global_deduction_rules: [
    "全部分项扣分后，最终总分必须限制在 80～100 分；若计算结果低于 80 分，按 80 分计。",
    "多个必做章节缺失，或设计、实现和测试无法建立对应关系：内容完整性维度按 40 分计，总分最高不超过 84 分。",
    "基础 Reno 误写成完整 Reno、将未实现挑战机制写成成果，或关键技术概念明显错误：技术正确性维度按 16 分计，总分最高不超过 84 分。",
    "实验图表无原始数据、日志、trace 或脚本支撑：图表与可追溯性维度按 12 分计，总分最高不超过 89 分。",
    "缺少 AI 使用说明或人工验证记录：AI 维度按 8 分计；记录明显失实时进入人工复核。",
    "大段粘贴源码代替设计与实现说明：内容完整性维度不得获得提升分。",
    "缺少正文引用、参考文献或主要 Git 提交标识：在对应维度区间内扣分，但各维度不得低于规定基础分。",
    "未完成挑战任务不扣分；选做内容只有在实现、测试和对比分析均有证据时才作为提升分依据。",
    "对同一个问题原则上不重复扣分。",
    "虚构标准条款、引用、实验数据、图表、Git 或 AI 记录，或报告与提交代码严重不一致：进入人工复核；确认需要评分时原则上归入 80～84 分档，不得低于 80 分。",
  ],
  calibration_rules: [
    "以 82 分、87 分、92 分、97 分分别作为需要改进、基本完成、良好完成、突出完成档位的参考锚点。",
    "先确定报告完成档位，再按照 50%、20%、15%、10%、5% 五个维度在档位内上下调整。",
    "80～84 分用于章节、技术准确性、对应关系或证据追溯存在较大缺失的报告。",
    "85～89 分用于主要章节基本完成，但技术深度、图表证据、AI 记录或格式规范不足的报告。",
    "90～94 分必须做到必做章节较完整、核心技术基本正确、设计实现测试基本一致且主要证据可追溯。",
    "95～100 分必须在完整性、技术正确性、图表质量、AI 人工验证和写作规范方面均无实质缺项。",
    "100 分要求报告内容和全部关键图表均可由提交代码、原始数据及脚本复现。",
    "同一档位内分差原则上控制在 1～3 分，最终成绩不得低于 80 分。",
  ],
  late_rule: "",
  late_penalty_points: 0,
  resubmission_rule: "",
  resubmission_penalty_points: 0,
  feedback_style: "先说明最终报告完成档位，再按内容完整性、技术正确性、图表证据、AI 验证和写作规范给出依据与改进建议；最终成绩限定在 80～100 分。",
};

finalCourseReportRubric.source_text = describeRubric(finalCourseReportRubric);

export const rubricTemplates: RubricTemplate[] = [
  {
    id: "stage-two-progress-report",
    label: "第二阶段进度报告",
    summary: "80～100 分 · 四档完成度 · 5 个评分维度",
    rubric: stageTwoProgressRubric,
    builtIn: true,
  },
  {
    id: "stage-three-progress-report",
    label: "第三阶段进度报告",
    summary: "80～100 分 · 基础 Reno · 联调与性能实验",
    rubric: stageThreeProgressRubric,
    builtIn: true,
  },
  {
    id: "final-course-report",
    label: "最终课程报告",
    summary: "80～100 分 · 指导书 50/20/15/10/5 比例",
    rubric: finalCourseReportRubric,
    builtIn: true,
  },
];

export function createRubricFromTemplate(template: RubricTemplate): Rubric {
  return cloneRubric(template.rubric);
}

export function loadCustomRubricTemplates(): RubricTemplate[] {
  try {
    const stored = window.localStorage.getItem(CUSTOM_TEMPLATE_STORAGE_KEY);
    if (!stored) return [];
    const parsed: unknown = JSON.parse(stored);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isStoredTemplate).map((template) => ({
      ...template,
      rubric: cloneRubric(template.rubric),
      builtIn: false,
    }));
  } catch {
    return [];
  }
}

export function upsertCustomRubricTemplate(
  templates: RubricTemplate[],
  label: string,
  rubric: Rubric,
  templateId?: string,
): { templates: RubricTemplate[]; template: RubricTemplate } {
  const normalizedLabel = label.trim();
  const existing = templateId
    ? templates.find((item) => item.id === templateId)
    : templates.find((item) => item.label === normalizedLabel);
  if (templateId && !existing) {
    throw new Error("待修改的模板不存在");
  }
  if (
    templateId
    && templates.some(
      (item) => item.id !== templateId && item.label === normalizedLabel,
    )
  ) {
    throw new Error("已有同名模板，请使用其他名称");
  }
  const template: RubricTemplate = {
    id: existing?.id ?? `custom-${crypto.randomUUID()}`,
    label: normalizedLabel,
    summary: `${rubric.total_score} 分 · ${rubric.criteria.length} 个评分项`,
    rubric: cloneRubric(rubric),
    builtIn: false,
    updatedAt: new Date().toISOString(),
  };
  const next = existing
    ? templates.map((item) => item.id === existing.id ? template : item)
    : [template, ...templates];
  persistCustomRubricTemplates(next);
  return { templates: next, template };
}

export function removeCustomRubricTemplate(
  templates: RubricTemplate[],
  templateId: string,
): RubricTemplate[] {
  const next = templates.filter((item) => item.id !== templateId);
  persistCustomRubricTemplates(next);
  return next;
}

function persistCustomRubricTemplates(templates: RubricTemplate[]) {
  window.localStorage.setItem(
    CUSTOM_TEMPLATE_STORAGE_KEY,
    JSON.stringify(templates),
  );
}

function isStoredTemplate(value: unknown): value is RubricTemplate {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<RubricTemplate>;
  return typeof candidate.id === "string"
    && typeof candidate.label === "string"
    && !!candidate.rubric
    && Array.isArray(candidate.rubric.criteria);
}

function cloneRubric(rubric: Rubric): Rubric {
  return JSON.parse(JSON.stringify(rubric)) as Rubric;
}

function describeRubric(rubric: Rubric): string {
  const lines = [
    rubric.title,
    `总分：${rubric.total_score} 分`,
    "",
    "评分原则：",
    ...(rubric.overall_requirements ?? []).map((item) => `- ${item}`),
    "",
    "完成阶段与建议分数区间：",
  ];
  (rubric.score_bands ?? []).forEach((band) => {
    lines.push(`${band.name}（${band.min_score}-${band.max_score} 分）：${band.description}`);
    lines.push(...band.requirements.map((item) => `- ${item}`));
  });
  lines.push("", "评分维度：");
  rubric.criteria.forEach((criterion, index) => {
    lines.push(`${index + 1}. ${criterion.name}（${criterion.max_score} 分）`);
    lines.push(criterion.description);
  });
  lines.push("", "强制章节：");
  lines.push(...(rubric.required_sections ?? []).map((item) => `- ${item}`));
  lines.push("", "扣分及限制规则：");
  lines.push(...(rubric.global_deduction_rules ?? []).map((item) => `- ${item}`));
  lines.push("", "分数校准要求：");
  lines.push(...(rubric.calibration_rules ?? []).map((item) => `- ${item}`));
  return lines.join("\n");
}
