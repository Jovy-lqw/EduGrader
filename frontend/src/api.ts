import type {
  Course,
  GradeDecision,
  Homework,
  Job,
  Rubric,
  RubricCriterion,
  RubricFileParseResult,
  RuntimeConfig,
  SessionStatus,
  Submission,
} from "./types";

type ConfigUpdate = Omit<RuntimeConfig, "llm_api_key_configured"> & {
  llm_api_key?: string;
};

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {
    ...init,
    headers,
  });
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch {
      // Keep the HTTP fallback message.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  getConfig: () => request<RuntimeConfig>("/api/config"),
  saveConfig: (config: ConfigUpdate) =>
    request<RuntimeConfig>("/api/config", {
      method: "PUT",
      body: JSON.stringify(config),
    }),
  openLogin: () =>
    request<{ message: string }>("/api/session/open-login", {
      method: "POST",
    }),
  getSession: () => request<SessionStatus>("/api/session/status"),
  getCourses: () => request<Course[]>("/api/courses"),
  getHomeworks: (courseId: string) =>
    request<Homework[]>(
      `/api/courses/${encodeURIComponent(courseId)}/homeworks`,
    ),
  getHomework: (courseId: string, homeworkId: string) =>
    request<Homework>(
      `/api/courses/${encodeURIComponent(courseId)}/homeworks/${encodeURIComponent(homeworkId)}`,
    ),
  normalizeRubric: (
    sourceText: string,
    totalScore: number,
    platformCriteria: RubricCriterion[],
  ) =>
    request<Rubric>("/api/rubrics/normalize", {
      method: "POST",
      body: JSON.stringify({
        source_text: sourceText,
        total_score: totalScore,
        platform_criteria: platformCriteria,
      }),
    }),
  parseRubricFile: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<RubricFileParseResult>("/api/rubrics/parse-file", {
      method: "POST",
      body,
    });
  },
  getJobs: () => request<Job[]>("/api/jobs"),
  getJob: (jobId: string) =>
    request<Job>(`/api/jobs/${encodeURIComponent(jobId)}`),
  deleteJob: (jobId: string) =>
    request<{ message: string }>(`/api/jobs/${encodeURIComponent(jobId)}`, {
      method: "DELETE",
    }),
  createJob: (payload: {
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
      allow_conflict_overwrite?: boolean;
    };
    require_human_confirmation: boolean;
    write_enabled: boolean;
  }) =>
    request<Job>("/api/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  startJob: (jobId: string) =>
    request<Job>(`/api/jobs/${encodeURIComponent(jobId)}/start`, {
      method: "POST",
    }),
  pauseJob: (jobId: string) =>
    request<Job>(`/api/jobs/${encodeURIComponent(jobId)}/pause`, {
      method: "POST",
    }),
  setConflictOverwrite: (jobId: string, enabled: boolean) =>
    request<Job>(
      `/api/jobs/${encodeURIComponent(jobId)}/conflict-overwrite`,
      {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      },
    ),
  beginManualReview: (submissionId: string) =>
    request<Submission>(
      `/api/submissions/${encodeURIComponent(submissionId)}/manual-review`,
      { method: "POST" },
    ),
  approveSubmission: (
    submissionId: string,
    grade: GradeDecision,
    manualTotalScore?: number,
  ) =>
    request<Submission>(
      `/api/submissions/${encodeURIComponent(submissionId)}/approve`,
      {
        method: "POST",
        body: JSON.stringify({
          grade,
          ...(manualTotalScore === undefined
            ? {}
            : { manual_total_score: manualTotalScore }),
        }),
      },
    ),
  rejectSubmission: (submissionId: string) =>
    request<Submission>(
      `/api/submissions/${encodeURIComponent(submissionId)}/reject`,
      { method: "POST" },
    ),
};
