export type SessionStatus = {
  status: "not_started" | "login_required" | "ready" | "expired";
  display_name: string;
  message: string;
};

export type RuntimeConfig = {
  llm_base_url: string;
  llm_model: string;
  llm_concurrency: number;
  llm_request_interval_seconds: number;
  request_timeout_seconds: number;
  llm_max_output_tokens: number;
  max_pdf_megabytes: number;
  max_model_characters: number;
  keep_downloaded_pdfs: boolean;
  require_human_confirmation_default: boolean;
  adapter_mode: "zhihuishu" | "mock";
  llm_api_key_configured: boolean;
};

export type Course = {
  id: string;
  name: string;
  term: string;
  course_number: string;
  student_count: number | null;
};

export type RubricCriterion = {
  id: string;
  name: string;
  description: string;
  max_score: string | number;
  required_evidence: string[];
  deduction_rules: string[];
  platform_score_attr_id?: string | null;
};

export type RubricStage = {
  id: string;
  name: string;
  description: string;
  completion_signals: string[];
  expected_deliverables: string[];
};

export type RubricScoreBand = {
  id: string;
  name: string;
  min_score: string | number;
  max_score: string | number;
  description: string;
  requirements: string[];
};

export type Rubric = {
  title: string;
  source_text: string;
  total_score: string | number;
  criteria: RubricCriterion[];
  grading_mode?: "holistic" | "stage_completion";
  stages?: RubricStage[];
  stage_scoring_instruction?: string;
  overall_requirements?: string[];
  score_bands?: RubricScoreBand[];
  required_sections?: string[];
  global_deduction_rules?: string[];
  calibration_rules?: string[];
  late_rule: string;
  late_penalty_points: string | number;
  resubmission_rule: string;
  resubmission_penalty_points: string | number;
  feedback_style: string;
};

export type RubricFileParseResult = {
  filename: string;
  file_type: "pdf" | "docx" | "txt" | "md";
  text: string;
  characters: number;
};

export type Homework = {
  id: string;
  course_id: string;
  title: string;
  description: string;
  total_score: string | number | null;
  status: string;
  deadline: string;
  reviewed_count: number | null;
  unreviewed_count: number | null;
  auto_publish: boolean | null;
  score_attributes: RubricCriterion[];
};

export type GradeCriterion = {
  criterion_id: string;
  score: string | number;
  evidence: string[];
  deductions: string[];
  explanation: string;
};

export type GradeDecision = {
  criterion_scores: GradeCriterion[];
  raw_score: string | number;
  final_score: string | number;
  detected_stage_id: string;
  detected_stage_name: string;
  stage_evidence: string[];
  detected_score_band_id: string;
  detected_score_band_name: string;
  score_band_evidence: string[];
  feedback: string;
  confidence: number;
  needs_review: boolean;
  review_reasons: string[];
  adjustments: string[];
};

export type SubmissionEvent = {
  event_type: string;
  message: string;
  detail: Record<string, unknown>;
  created_at: string;
};

export type Submission = {
  id: string;
  student_id: string;
  student_name: string;
  student_number_masked: string;
  class_name: string;
  status: string;
  status_message: string;
  attempt_count: number;
  pdf_files: Array<Record<string, unknown>>;
  ignored_files: Array<Record<string, unknown>>;
  grade: Partial<GradeDecision>;
  remote_receipt: Record<string, unknown>;
  events: SubmissionEvent[];
  updated_at: string;
};

export type Job = {
  id: string;
  course_id: string;
  course_name: string;
  homework_id: string;
  homework_title: string;
  rubric: Rubric;
  scope: {
    status: "unreviewed" | "all";
    class_id: string;
    student_ids: string[];
    rerun_from_job_id: string;
    overwrite_existing_scores: boolean;
    allow_conflict_overwrite: boolean;
  };
  require_human_confirmation: boolean;
  write_enabled: boolean;
  publish_after_write: boolean;
  status: string;
  error_message: string;
  total_count: number;
  completed_count: number;
  skipped_count: number;
  failed_count: number;
  review_count: number;
  recoverable_count: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  submissions: Submission[];
};
