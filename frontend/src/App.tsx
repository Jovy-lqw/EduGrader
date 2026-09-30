import {
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  ClipboardCheck,
  Copy,
  Download,
  Eye,
  ExternalLink,
  FileUp,
  FileText,
  Gauge,
  History,
  LogIn,
  Pause,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  UserCheck,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "./api";
import {
  createRubricFromTemplate,
  loadCustomRubricTemplates,
  removeCustomRubricTemplate,
  upsertCustomRubricTemplate,
} from "./rubricTemplates";
import type {
  Course,
  GradeDecision,
  Homework,
  Job,
  Rubric,
  RubricCriterion,
  RuntimeConfig,
  SessionStatus,
  Submission,
} from "./types";

type View = "new" | "jobs" | "settings";
type JobTemplate = {
  version: number;
  rubric: Rubric;
  scope: "unreviewed" | "all";
  humanConfirmation: boolean;
  writeEnabled: boolean;
  studentIds: string[];
  rerunFromJobId?: string;
  courseId?: string;
  homeworkId?: string;
};

const activeJobStatuses = new Set(["preparing", "running", "stopping"]);
const completedSubmissionStatuses = new Set(["written", "dry_run_complete"]);

function App() {
  const [view, setView] = useState<View>("new");
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [session, setSession] = useState<SessionStatus>({
    status: "not_started",
    display_name: "",
    message: "浏览器尚未启动",
  });
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const selectedJobIdRef = useRef("");
  const [notice, setNotice] = useState("");
  const [jobTemplate, setJobTemplate] = useState<JobTemplate | null>(null);

  const refreshSession = useCallback(async () => {
    try {
      setSession(await api.getSession());
    } catch (error) {
      setNotice(errorMessage(error));
    }
  }, []);

  const refreshJobs = useCallback(async () => {
    try {
      const next = await api.getJobs();
      const currentSelectedId = selectedJobIdRef.current;
      const nextSelectedId = next.some((job) => job.id === currentSelectedId)
        ? currentSelectedId
        : next[0]?.id || "";
      if (nextSelectedId) {
        const detail = await api.getJob(nextSelectedId);
        setJobs(next.map((job) => job.id === detail.id ? detail : job));
      } else {
        setJobs(next);
      }
      selectedJobIdRef.current = nextSelectedId;
      setSelectedJobId(nextSelectedId);
    } catch (error) {
      setNotice(errorMessage(error));
    }
  }, []);

  const selectJob = useCallback(async (jobId: string) => {
    selectedJobIdRef.current = jobId;
    setSelectedJobId(jobId);
    try {
      const detail = await api.getJob(jobId);
      setJobs((current) => current.map(
        (job) => job.id === detail.id ? detail : job,
      ));
    } catch (error) {
      setNotice(errorMessage(error));
    }
  }, []);

  useEffect(() => {
    void Promise.all([
      api.getConfig().then(setConfig).catch((error) => setNotice(errorMessage(error))),
      refreshSession(),
      refreshJobs(),
    ]);
  }, [refreshJobs, refreshSession]);

  useEffect(() => {
    if (!jobs.some((job) => activeJobStatuses.has(job.status))) return;
    const timer = window.setInterval(() => void refreshJobs(), 1800);
    return () => window.clearInterval(timer);
  }, [jobs, refreshJobs]);

  const selectedJob = jobs.find((job) => job.id === selectedJobId);

  const handleOpenLogin = async () => {
    try {
      const result = await api.openLogin();
      setNotice(result.message);
      window.setTimeout(() => void refreshSession(), 1800);
    } catch (error) {
      setNotice(errorMessage(error));
    }
  };

  const handleJobCreated = (job: Job) => {
    selectedJobIdRef.current = job.id;
    setSelectedJobId(job.id);
    setView("jobs");
    void refreshJobs();
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark"><ClipboardCheck size={19} /></span>
          <span>EduGrader</span>
        </div>
        <div className="session-summary">
          <span className={`status-dot status-${session.status}`} />
          <span>{session.display_name || session.message}</span>
          <button className="icon-button" title="刷新登录状态" onClick={() => void refreshSession()}>
            <RefreshCw size={16} />
          </button>
        </div>
      </header>

      <aside className="sidebar">
        <nav aria-label="主导航">
          <NavButton active={view === "new"} icon={<BookOpen />} label="新建批阅" onClick={() => setView("new")} />
          <NavButton active={view === "jobs"} icon={<Gauge />} label="任务中心" badge={activeCount(jobs)} onClick={() => setView("jobs")} />
          <NavButton active={view === "settings"} icon={<Settings />} label="系统配置" onClick={() => setView("settings")} />
        </nav>
        <div className="sidebar-footer">
          <ShieldCheck size={17} />
          <span>成绩发布始终关闭</span>
        </div>
      </aside>

      <main className="workspace">
        {notice && (
          <div className="notice" role="status">
            <CircleAlert size={17} />
            <span>{notice}</span>
            <button className="icon-button" title="关闭提示" onClick={() => setNotice("")}>
              <X size={15} />
            </button>
          </div>
        )}
        {view === "new" && config && (
          <NewJobView
            config={config}
            session={session}
            jobTemplate={jobTemplate}
            onOpenLogin={handleOpenLogin}
            onCreated={handleJobCreated}
            onError={setNotice}
          />
        )}
        {view === "jobs" && (
          <JobsView
            jobs={jobs}
            selectedJob={selectedJob}
            onSelect={(jobId) => void selectJob(jobId)}
            onRefresh={refreshJobs}
            onReuseJob={(job) => {
              setJobTemplate({
                version: Date.now(),
                rubric: cloneRubric(job.rubric),
                scope: job.scope.status === "all" ? "all" : "unreviewed",
                humanConfirmation: job.require_human_confirmation,
                writeEnabled: job.write_enabled,
                studentIds: [],
              });
              setNotice("评分细则和执行设置已带入，请选择目标作业");
              setView("new");
            }}
            onRerunJob={(job) => {
              setJobTemplate({
                version: Date.now(),
                rubric: cloneRubric(job.rubric),
                scope: "all",
                humanConfirmation: job.require_human_confirmation,
                writeEnabled: true,
                studentIds: job.submissions.map((submission) => submission.student_id),
                rerunFromJobId: job.id,
                courseId: job.course_id,
                homeworkId: job.homework_id,
              });
              setNotice("已带入原任务，请修改评分细则后确认重新批阅");
              setView("new");
            }}
            onNotice={setNotice}
            onError={setNotice}
          />
        )}
        {view === "settings" && config && (
          <SettingsView
            config={config}
            onSaved={(next) => {
              setConfig(next);
              setNotice("配置已保存");
              void refreshSession();
            }}
            onError={setNotice}
          />
        )}
      </main>
    </div>
  );
}

function NavButton(props: {
  active: boolean;
  icon: React.ReactNode;
  label: string;
  badge?: number;
  onClick: () => void;
}) {
  return (
    <button className={`nav-button ${props.active ? "active" : ""}`} onClick={props.onClick}>
      {props.icon}
      <span>{props.label}</span>
      {!!props.badge && <span className="nav-badge">{props.badge}</span>}
    </button>
  );
}

function CompactSelect(props: {
  ariaLabel: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  placeholder?: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const selected = props.options.find((option) => option.value === props.value);

  useEffect(() => {
    if (!open) return;
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  useEffect(() => {
    if (props.disabled) setOpen(false);
  }, [props.disabled]);

  return (
    <div ref={root} className={`compact-select ${open ? "open" : ""}`}>
      <button
        type="button"
        className="compact-select-trigger"
        aria-label={props.ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={props.disabled}
        onClick={() => setOpen((current) => !current)}
      >
        <span className={selected ? "" : "placeholder"}>
          {selected?.label || props.placeholder || "请选择"}
        </span>
        <ChevronDown size={16} />
      </button>
      {open && (
        <div className="compact-select-menu" role="listbox" aria-label={props.ariaLabel}>
          {props.options.length === 0 ? (
            <span className="compact-select-empty">暂无可选项</span>
          ) : props.options.map((option) => (
            <button
              type="button"
              role="option"
              aria-selected={option.value === props.value}
              className={`compact-select-option ${option.value === props.value ? "selected" : ""}`}
              key={option.value}
              onClick={(event) => {
                event.preventDefault();
                props.onChange(option.value);
                setOpen(false);
              }}
            >
              <span className="compact-select-check">
                {option.value === props.value && <Check size={14} />}
              </span>
              <span>{option.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function NewJobView(props: {
  config: RuntimeConfig;
  session: SessionStatus;
  jobTemplate: JobTemplate | null;
  onOpenLogin: () => Promise<void>;
  onCreated: (job: Job) => void;
  onError: (message: string) => void;
}) {
  const [courses, setCourses] = useState<Course[]>([]);
  const [homeworks, setHomeworks] = useState<Homework[]>([]);
  const [courseId, setCourseId] = useState("");
  const [homeworkId, setHomeworkId] = useState("");
  const [rubricText, setRubricText] = useState("");
  const [rubricFileName, setRubricFileName] = useState("");
  const [rubric, setRubric] = useState<Rubric | null>(null);
  const [customRubricTemplates, setCustomRubricTemplates] = useState(
    loadCustomRubricTemplates,
  );
  const [rubricTemplateId, setRubricTemplateId] = useState(() =>
    customRubricTemplates[0]?.id ?? ""
  );
  const [showTemplateSave, setShowTemplateSave] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [editingTemplateId, setEditingTemplateId] = useState("");
  const [pendingTemplateDelete, setPendingTemplateDelete] = useState(false);
  const [creatingRubric, setCreatingRubric] = useState(false);
  const [totalScore, setTotalScore] = useState(100);
  const [scope, setScope] = useState<"unreviewed" | "all">("unreviewed");
  const [humanConfirmation, setHumanConfirmation] = useState(
    props.config.require_human_confirmation_default,
  );
  const [writeEnabled, setWriteEnabled] = useState(true);
  const [busy, setBusy] = useState("");
  const [editingCriterionId, setEditingCriterionId] = useState("");
  const [criterionDraft, setCriterionDraft] = useState({
    name: "",
    description: "",
    max_score: 0,
  });
  const [pendingDeleteId, setPendingDeleteId] = useState("");
  const [showRerunConfirm, setShowRerunConfirm] = useState(false);
  const [showStartConfirm, setShowStartConfirm] = useState(false);
  const rubricFileInput = useRef<HTMLInputElement>(null);
  const rubricTextArea = useRef<HTMLTextAreaElement>(null);
  const preserveReusedRubric = useRef(Boolean(props.jobTemplate));

  const selectedCourse = courses.find((course) => course.id === courseId);
  const selectedHomework = homeworks.find((homework) => homework.id === homeworkId);
  const isRerun = Boolean(props.jobTemplate?.rerunFromJobId);
  const availableRubricTemplates = customRubricTemplates;
  const selectedRubricTemplate = availableRubricTemplates.find(
    (template) => template.id === rubricTemplateId,
  );
  const templateMismatch = Boolean(
    selectedHomework
    && selectedRubricTemplate
    && rubricContextKey(selectedHomework.title)
    && rubricContextKey(selectedRubricTemplate.label)
    && rubricContextKey(selectedHomework.title)
      !== rubricContextKey(selectedRubricTemplate.label)
  );

  useEffect(() => {
    if (!props.jobTemplate) return;
    const reused = cloneRubric(props.jobTemplate.rubric);
    preserveReusedRubric.current = true;
    setRubric(reused);
    setRubricText(reused.source_text || formatRubricText(reused));
    setRubricFileName("");
    setTotalScore(Number(reused.total_score));
    setScope(props.jobTemplate.scope);
    setHumanConfirmation(props.jobTemplate.humanConfirmation);
    setWriteEnabled(props.jobTemplate.writeEnabled);
    if (props.jobTemplate.rerunFromJobId) {
      setCourseId(props.jobTemplate.courseId || "");
      setHomeworkId(props.jobTemplate.homeworkId || "");
      setScope("all");
    }
    setShowRerunConfirm(false);
    setShowStartConfirm(false);
    setShowTemplateSave(false);
    setEditingTemplateId("");
    setPendingTemplateDelete(false);
    setCreatingRubric(false);
    setEditingCriterionId("");
    setPendingDeleteId("");
  }, [props.jobTemplate?.version]);

  const loadCourses = async () => {
    setBusy("courses");
    try {
      const result = await api.getCourses();
      setCourses(result);
      if (result.length === 1) setCourseId(result[0].id);
    } catch (error) {
      props.onError(errorMessage(error));
    } finally {
      setBusy("");
    }
  };

  useEffect(() => {
    if (props.session.status === "ready" && courses.length === 0) {
      void loadCourses();
    }
  }, [props.session.status]);

  useEffect(() => {
    if (!courseId) {
      setHomeworks([]);
      setHomeworkId("");
      return;
    }
    setBusy("homeworks");
    api.getHomeworks(courseId)
      .then((result) => {
        setHomeworks(result);
        const rerunHomeworkId = (
          props.jobTemplate?.rerunFromJobId
          && props.jobTemplate.courseId === courseId
        )
          ? props.jobTemplate.homeworkId
          : "";
        setHomeworkId(
          rerunHomeworkId && result.some((item) => item.id === rerunHomeworkId)
            ? rerunHomeworkId
            : result.length === 1 ? result[0].id : "",
        );
      })
      .catch((error) => props.onError(errorMessage(error)))
      .finally(() => setBusy(""));
  }, [courseId, props.jobTemplate?.version]);

  useEffect(() => {
    if (!selectedHomework) return;
    if (preserveReusedRubric.current) {
      preserveReusedRubric.current = false;
      return;
    }
    if (selectedHomework.total_score !== null) {
      setTotalScore(Number(selectedHomework.total_score));
    }
    const recommendedTemplateId = recommendRubricTemplate(
      selectedHomework.title,
      availableRubricTemplates,
    );
    if (recommendedTemplateId) setRubricTemplateId(recommendedTemplateId);
    setRubric(null);
    setCreatingRubric(false);
    setEditingCriterionId("");
    setPendingDeleteId("");
    setBusy("homework-detail");
    api.getHomework(courseId, selectedHomework.id)
      .then((detail) => {
        setHomeworks((current) => current.map(
          (item) => item.id === detail.id ? detail : item,
        ));
        if (detail.total_score !== null) {
          setTotalScore(Number(detail.total_score));
        }
      })
      .catch((error) => props.onError(errorMessage(error)))
      .finally(() => setBusy(""));
  }, [homeworkId]);

  const normalize = async () => {
    if (!rubricText.trim()) return;
    setBusy("rubric");
    try {
      const platformCriteria = selectedHomework
        ? (await api.getHomework(courseId, selectedHomework.id)).score_attributes
        : [];
      const result = await api.normalizeRubric(
        rubricText,
        totalScore,
        platformCriteria,
      );
      setRubric(result);
      setCreatingRubric(false);
      setEditingCriterionId("");
      setPendingDeleteId("");
    } catch (error) {
      props.onError(errorMessage(error));
    } finally {
      setBusy("");
    }
  };

  const parseRubricFile = async (file: File) => {
    setBusy("rubric-file");
    try {
      const result = await api.parseRubricFile(file);
      setRubricText(result.text);
      setRubricFileName(result.filename);
      setRubric(null);
      setCreatingRubric(true);
      setEditingCriterionId("");
      setPendingDeleteId("");
    } catch (error) {
      props.onError(errorMessage(error));
    } finally {
      setBusy("");
    }
  };

  const applyRubricTemplate = () => {
    if (!selectedRubricTemplate) return;
    const result = createRubricFromTemplate(selectedRubricTemplate);
    setRubric(result);
    setRubricText(result.source_text);
    setTotalScore(Number(result.total_score));
    setRubricFileName("");
    setShowTemplateSave(false);
    setEditingTemplateId("");
    setPendingTemplateDelete(false);
    setCreatingRubric(false);
    setEditingCriterionId("");
    setPendingDeleteId("");
  };

  const startNewRubricTemplate = () => {
    setRubricTemplateId("");
    setRubric(null);
    setRubricText("");
    setRubricFileName("");
    setShowTemplateSave(false);
    setTemplateName("");
    setEditingTemplateId("");
    setPendingTemplateDelete(false);
    setCreatingRubric(true);
    setEditingCriterionId("");
    setPendingDeleteId("");
    window.requestAnimationFrame(() => rubricTextArea.current?.focus());
  };

  const editRubricTemplate = () => {
    if (!selectedRubricTemplate) return;
    const result = createRubricFromTemplate(selectedRubricTemplate);
    setRubric(result);
    setRubricText(result.source_text);
    setTotalScore(Number(result.total_score));
    setRubricFileName("");
    setTemplateName(selectedRubricTemplate.label);
    setEditingTemplateId(selectedRubricTemplate.id);
    setShowTemplateSave(true);
    setPendingTemplateDelete(false);
    setCreatingRubric(false);
    setEditingCriterionId("");
    setPendingDeleteId("");
  };

  const saveRubricTemplate = () => {
    if (!rubric || !templateName.trim()) return;
    try {
      const saved = upsertCustomRubricTemplate(
        customRubricTemplates,
        templateName,
        {
          ...rubric,
          source_text: formatRubricText(rubric),
        },
        editingTemplateId || undefined,
      );
      setCustomRubricTemplates(saved.templates);
      setRubricTemplateId(saved.template.id);
      setShowTemplateSave(false);
      setEditingTemplateId("");
      setPendingTemplateDelete(false);
      setCreatingRubric(false);
    } catch (error) {
      props.onError(`保存评分模板失败：${errorMessage(error)}`);
    }
  };

  const deleteRubricTemplate = () => {
    if (!selectedRubricTemplate) return;
    try {
      const nextTemplates = removeCustomRubricTemplate(
        customRubricTemplates,
        selectedRubricTemplate.id,
      );
      setCustomRubricTemplates(nextTemplates);
      setRubricTemplateId(nextTemplates[0]?.id ?? "");
      setEditingTemplateId("");
      setPendingTemplateDelete(false);
    } catch (error) {
      props.onError(`删除评分模板失败：${errorMessage(error)}`);
    }
  };

  const createAndStart = async () => {
    if (!selectedCourse || !selectedHomework || !rubric) return;
    setBusy("create");
    try {
      const created = await api.createJob({
        course_id: selectedCourse.id,
        course_name: selectedCourse.name,
        homework_id: selectedHomework.id,
        homework_title: selectedHomework.title,
        rubric,
        scope: {
          status: isRerun ? "all" : scope,
          class_id: "",
          student_ids: isRerun ? props.jobTemplate?.studentIds ?? [] : [],
          rerun_from_job_id: props.jobTemplate?.rerunFromJobId ?? "",
          overwrite_existing_scores: isRerun && writeEnabled,
        },
        require_human_confirmation: humanConfirmation,
        write_enabled: writeEnabled,
      });
      const started = await api.startJob(created.id);
      props.onCreated(started);
    } catch (error) {
      props.onError(errorMessage(error));
    } finally {
      setBusy("");
      setShowRerunConfirm(false);
      setShowStartConfirm(false);
    }
  };

  const requestStart = () => {
    if (isRerun && writeEnabled) {
      setShowRerunConfirm(true);
      return;
    }
    if (writeEnabled) {
      setShowStartConfirm(true);
      return;
    }
    void createAndStart();
  };

  const ready = props.session.status === "ready";
  const rubricTotal = rubric?.criteria.reduce((sum, item) => sum + Number(item.max_score), 0) ?? 0;
  const rubricValid = !!rubric
    && rubric.criteria.length > 0
    && Math.abs(rubricTotal - Number(rubric.total_score)) < 0.001;

  const startEditingCriterion = (criterion: RubricCriterion) => {
    setPendingDeleteId("");
    setEditingCriterionId(criterion.id);
    setCriterionDraft({
      name: criterion.name,
      description: criterion.description,
      max_score: Number(criterion.max_score),
    });
  };

  const saveCriterion = () => {
    if (!rubric || !editingCriterionId) return;
    const name = criterionDraft.name.trim();
    const maxScore = Number(criterionDraft.max_score);
    if (!name || !Number.isFinite(maxScore) || maxScore <= 0) return;
    setRubric({
      ...rubric,
      criteria: rubric.criteria.map((criterion) =>
        criterion.id === editingCriterionId
          ? {
              ...criterion,
              name,
              description: criterionDraft.description.trim(),
              max_score: maxScore,
            }
          : criterion,
      ),
    });
    setEditingCriterionId("");
  };

  const deleteCriterion = (criterionId: string) => {
    if (!rubric) return;
    setRubric({
      ...rubric,
      criteria: rubric.criteria.filter((criterion) => criterion.id !== criterionId),
    });
    setPendingDeleteId("");
    if (editingCriterionId === criterionId) setEditingCriterionId("");
  };

  return (
    <div className="page">
      <PageHeader title="新建批阅" subtitle="作业批阅任务" />

      <section className="workflow-section">
        <StepLabel number="01" title="登录会话" complete={ready} />
        <div className="section-body login-row">
          <div>
            <strong>{ready ? props.session.display_name || "已登录" : "未连接智慧树"}</strong>
            <p>{props.session.message}</p>
          </div>
          <button className="secondary-button" onClick={() => void props.onOpenLogin()}>
            <LogIn size={17} />
            {ready ? "打开智慧树" : "登录"}
          </button>
        </div>
      </section>

      <section className="workflow-section">
        <StepLabel number="02" title="选择作业" complete={!!selectedHomework} />
        <div className="section-body form-grid two-columns">
          {isRerun && (
            <div className="rerun-context">
              <RotateCcw size={17} />
              <div>
                <strong>修改后重新批阅</strong>
                <span>
                  固定处理原任务中的 {props.jobTemplate?.studentIds.length ?? 0} 人，原任务记录保留
                </span>
              </div>
            </div>
          )}
          <label>
            <span>课程</span>
            <div className="input-with-action">
              <CompactSelect
                ariaLabel="课程"
                value={courseId}
                placeholder="选择课程"
                disabled={!ready || isRerun}
                options={courses.map((course) => ({
                  value: course.id,
                  label: `${course.name} ${course.term}`.trim(),
                }))}
                onChange={setCourseId}
              />
              <button className="icon-button bordered" title="刷新课程" disabled={!ready || !!busy} onClick={() => void loadCourses()}>
                <RefreshCw size={16} />
              </button>
            </div>
          </label>
          <label>
            <span>作业</span>
            <CompactSelect
              ariaLabel="作业"
              value={homeworkId}
              placeholder="选择作业"
              disabled={!courseId || isRerun}
              options={homeworks.map((homework) => ({
                value: homework.id,
                label: homework.title,
              }))}
              onChange={setHomeworkId}
            />
          </label>
          {selectedHomework && (
            <div className="assignment-meta">
              <span>总分 {selectedHomework.total_score ?? "待读取"}</span>
              <span>未批 {selectedHomework.unreviewed_count ?? "待读取"}</span>
              <span className={selectedHomework.auto_publish ? "danger-text" : ""}>
                自动发布 {selectedHomework.auto_publish === true ? "已开启" : selectedHomework.auto_publish === false ? "已关闭" : "待校验"}
              </span>
            </div>
          )}
        </div>
      </section>

      <section className="workflow-section">
        <StepLabel number="03" title="评分细则" complete={rubricValid} />
        <div className="section-body rubric-layout">
          <div className="rubric-source">
            <label>
              <span>作业总分</span>
              <input type="number" min="1" step="1" value={totalScore} onChange={(event) => setTotalScore(Number(event.target.value))} />
            </label>
            <div className="rubric-template-picker">
              <div className="rubric-template-selection">
                <label>
                  <span>评分模板</span>
                  <CompactSelect
                    ariaLabel="评分模板"
                    value={rubricTemplateId}
                    placeholder="尚未选择模板"
                    options={availableRubricTemplates.map((template) => ({
                      value: template.id,
                      label: `自定义 · ${template.label}`,
                    }))}
                    onChange={(value) => {
                      setRubricTemplateId(value);
                      setShowTemplateSave(false);
                      setEditingTemplateId("");
                      setPendingTemplateDelete(false);
                      setCreatingRubric(false);
                    }}
                  />
                </label>
                <button
                  className="primary-button"
                  disabled={!selectedRubricTemplate || !!busy}
                  onClick={applyRubricTemplate}
                >
                  <BookOpen size={16} />
                  应用模板
                </button>
              </div>
              <div className="rubric-template-actions">
                <button
                  className="secondary-button"
                  disabled={!!busy}
                  onClick={startNewRubricTemplate}
                >
                  <Plus size={16} />
                  新建细则
                </button>
                <button
                  className="secondary-button"
                  disabled={!rubric || !!busy}
                  onClick={() => {
                    setTemplateName(rubric?.title || "");
                    setEditingTemplateId("");
                    setShowTemplateSave(true);
                    setPendingTemplateDelete(false);
                  }}
                >
                  <Save size={16} />
                  保存为模板
                </button>
                {selectedRubricTemplate && (
                  <>
                    <button
                      className="secondary-button"
                      disabled={!!busy}
                      onClick={editRubricTemplate}
                    >
                      <Pencil size={16} />
                      编辑模板
                    </button>
                    <button
                      className="secondary-button danger-secondary-button"
                      disabled={!!busy}
                      onClick={() => {
                        setPendingTemplateDelete(true);
                        setShowTemplateSave(false);
                        setEditingTemplateId("");
                      }}
                    >
                      <Trash2 size={16} />
                      删除模板
                    </button>
                  </>
                )}
              </div>
              <p>{selectedRubricTemplate?.summary}</p>
              {templateMismatch && (
                <div className="template-warning" role="alert">
                  <CircleAlert size={15} />
                  当前模板与所选作业阶段可能不一致，请确认后再应用。
                </div>
              )}
              {creatingRubric && (
                <div className="template-workflow-hint">
                  <strong>新建细则</strong>
                  <span>输入或导入评分要求，生成评分项后再保存为模板。</span>
                </div>
              )}
              {showTemplateSave && (
                <div className="rubric-template-edit-row">
                  <input
                    aria-label="模板名称"
                    value={templateName}
                    placeholder="模板名称"
                    onChange={(event) => setTemplateName(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") saveRubricTemplate();
                      if (event.key === "Escape") {
                        setShowTemplateSave(false);
                        setEditingTemplateId("");
                      }
                    }}
                  />
                  <button
                    className="icon-button bordered"
                    title={editingTemplateId ? "取消修改" : "取消保存"}
                    onClick={() => {
                      setShowTemplateSave(false);
                      setEditingTemplateId("");
                    }}
                  >
                    <X size={15} />
                  </button>
                  <button
                    className="icon-button criterion-save-button"
                    title={editingTemplateId ? "确认修改" : "确认保存"}
                    disabled={!templateName.trim()}
                    onClick={saveRubricTemplate}
                  >
                    <Check size={15} />
                  </button>
                </div>
              )}
              {pendingTemplateDelete && selectedRubricTemplate && (
                <div className="rubric-template-delete-row">
                  <span>删除“{selectedRubricTemplate.label}”？</span>
                  <button
                    className="text-button"
                    onClick={() => setPendingTemplateDelete(false)}
                  >
                    取消
                  </button>
                  <button className="text-button danger-text" onClick={deleteRubricTemplate}>
                    删除
                  </button>
                </div>
              )}
            </div>
            <div className="rubric-source-field">
              <div className="rubric-source-heading">
                <span>原始评分细则</span>
                <button
                  className="text-button rubric-upload-button"
                  disabled={!!busy}
                  onClick={() => rubricFileInput.current?.click()}
                >
                  <FileUp size={15} />
                  {busy === "rubric-file" ? "正在解析" : "导入文件"}
                </button>
                <input
                  ref={rubricFileInput}
                  className="visually-hidden"
                  type="file"
                  accept=".pdf,.docx,.txt,.md"
                  onChange={(event) => {
                    const file = event.currentTarget.files?.[0];
                    event.currentTarget.value = "";
                    if (file) void parseRubricFile(file);
                  }}
                />
              </div>
              <textarea
                ref={rubricTextArea}
                rows={10}
                value={rubricText}
                placeholder="粘贴评分细则，或导入 PDF、DOCX、TXT、MD 文件"
                onChange={(event) => setRubricText(event.target.value)}
                onKeyDown={(event) => {
                  if (event.ctrlKey && event.key.toLowerCase() === "a") {
                    event.preventDefault();
                    event.currentTarget.select();
                  }
                }}
              />
              {rubricFileName && (
                <span className="rubric-file-status">
                  <FileText size={14} />
                  {rubricFileName} · 已提取 {rubricText.length} 字
                </span>
              )}
            </div>
            <button className="secondary-button" disabled={!rubricText.trim() || !!busy} onClick={() => void normalize()}>
              <SlidersHorizontal size={17} />
              {busy === "rubric" ? "正在整理" : "生成结构化细则"}
            </button>
          </div>
          <div className="criteria-panel">
            <div className="panel-title">
              <span>评分项</span>
              {rubric && (
                <span className={rubricValid ? "" : "danger-text"}>
                  {rubricTotal} / {rubric.total_score}
                </span>
              )}
            </div>
            {!rubric && <EmptyState icon={<FileText />} text="生成后在此核对评分项" />}
            {rubric && !rubricValid && (
              <p className="rubric-total-warning">
                {rubric.criteria.length === 0
                  ? "至少保留一个评分项"
                  : `评分项合计需等于 ${rubric.total_score} 分`}
              </p>
            )}
            {rubric?.grading_mode === "stage_completion" && (
              <div className="stage-summary">
                <div>
                  <strong>先判阶段，再评完成度</strong>
                  <span>{rubric.stages?.length ?? 0} 个阶段</span>
                </div>
                <ol>
                  {(rubric.stages ?? []).map((stage) => <li key={stage.id}>{stage.name}</li>)}
                </ol>
              </div>
            )}
            {rubric && (
              (rubric.overall_requirements ?? []).length > 0
              || (rubric.score_bands ?? []).length > 0
              || (rubric.required_sections ?? []).length > 0
              || (rubric.global_deduction_rules ?? []).length > 0
              || (rubric.calibration_rules ?? []).length > 0
            ) && (
              <div className="rubric-global-summary">
                <div className="rubric-global-heading">
                  <strong>全局评分规则</strong>
                  <span>与评分项共同生效</span>
                </div>
                {(rubric.score_bands ?? []).length > 0 && (
                  <div className="score-band-strip">
                    {(rubric.score_bands ?? []).map((band) => (
                      <span key={band.id}>
                        {band.min_score}-{band.max_score} {band.name}
                      </span>
                    ))}
                  </div>
                )}
                <RubricRuleGroup title="总体要求" items={rubric.overall_requirements ?? []} />
                <RubricRuleGroup title="强制内容" items={rubric.required_sections ?? []} />
                <RubricRuleGroup title="全局扣分" items={rubric.global_deduction_rules ?? []} />
                <RubricRuleGroup title="批量校准" items={rubric.calibration_rules ?? []} />
              </div>
            )}
            {rubric?.criteria.map((criterion, index) => (
              <div
                className={`criterion-row ${editingCriterionId === criterion.id ? "editing" : ""}`}
                key={criterion.id}
              >
                <span className="criterion-index">{String(index + 1).padStart(2, "0")}</span>
                {editingCriterionId === criterion.id ? (
                  <div className="criterion-editor">
                    <label>
                      <span>名称</span>
                      <input
                        value={criterionDraft.name}
                        onChange={(event) => setCriterionDraft((current) => ({
                          ...current,
                          name: event.target.value,
                        }))}
                      />
                    </label>
                    <label>
                      <span>分值</span>
                      <input
                        type="number"
                        min="1"
                        step="1"
                        value={criterionDraft.max_score}
                        onChange={(event) => setCriterionDraft((current) => ({
                          ...current,
                          max_score: Number(event.target.value),
                        }))}
                      />
                    </label>
                    <label className="criterion-description-field">
                      <span>说明</span>
                      <textarea
                        rows={2}
                        value={criterionDraft.description}
                        onChange={(event) => setCriterionDraft((current) => ({
                          ...current,
                          description: event.target.value,
                        }))}
                      />
                    </label>
                    <div className="criterion-editor-actions">
                      <button
                        className="icon-button bordered"
                        title="取消修改"
                        onClick={() => setEditingCriterionId("")}
                      >
                        <X size={15} />
                      </button>
                      <button
                        className="icon-button criterion-save-button"
                        title="保存修改"
                        disabled={!criterionDraft.name.trim() || criterionDraft.max_score <= 0}
                        onClick={saveCriterion}
                      >
                        <Check size={15} />
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div>
                      <strong>{criterion.name}</strong>
                      <p>{criterion.description || "无补充说明"}</p>
                    </div>
                    <div className="criterion-meta">
                      <span className="score-value">{criterion.max_score} 分</span>
                      {pendingDeleteId === criterion.id ? (
                        <div className="criterion-delete-confirm">
                          <span>确认删除？</span>
                          <button className="text-button" onClick={() => setPendingDeleteId("")}>取消</button>
                          <button className="text-button danger-text" onClick={() => deleteCriterion(criterion.id)}>删除</button>
                        </div>
                      ) : (
                        <div className="criterion-actions">
                          <button
                            className="icon-button"
                            title="修改评分项"
                            onClick={() => startEditingCriterion(criterion)}
                          >
                            <Pencil size={15} />
                          </button>
                          <button
                            className="icon-button danger-icon-button"
                            title="删除评分项"
                            onClick={() => {
                              setEditingCriterionId("");
                              setPendingDeleteId(criterion.id);
                            }}
                          >
                            <Trash2 size={15} />
                          </button>
                        </div>
                      )}
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="workflow-section">
        <StepLabel number="04" title="执行设置" complete={false} />
        <div className="section-body execution-settings">
          {isRerun ? (
            <div className="rerun-scope">
              <History size={16} />
              原任务范围 · {props.jobTemplate?.studentIds.length ?? 0} 人
            </div>
          ) : (
            <div className="segmented" aria-label="批阅范围">
              <button className={scope === "unreviewed" ? "active" : ""} onClick={() => setScope("unreviewed")}>仅未批</button>
              <button className={scope === "all" ? "active" : ""} onClick={() => setScope("all")}>全部提交</button>
            </div>
          )}
          <Toggle checked={humanConfirmation} label="写入前人工确认" onChange={setHumanConfirmation} />
          <Toggle checked={writeEnabled} label="写入智慧树" onChange={setWriteEnabled} />
          <div className="publish-lock"><ShieldCheck size={16} />不发布成绩</div>
          <button className="primary-button start-button" disabled={!rubricValid || !selectedHomework || !!busy} onClick={requestStart}>
            {isRerun ? <RotateCcw size={17} /> : <Play size={17} fill="currentColor" />}
            {busy === "create" ? "正在启动" : isRerun ? "创建并重新批阅" : "创建并开始"}
          </button>
        </div>
      </section>
      {showRerunConfirm && selectedHomework && (
        <div className="dialog-backdrop" role="presentation" onMouseDown={() => setShowRerunConfirm(false)}>
          <div
            className="review-dialog rerun-confirm-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="rerun-confirm-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="dialog-header">
              <div>
                <span className="eyebrow">覆盖确认</span>
                <h2 id="rerun-confirm-title">重新批阅并覆盖未发布分数</h2>
              </div>
              <button className="icon-button" title="关闭" onClick={() => setShowRerunConfirm(false)}>
                <X size={18} />
              </button>
            </div>
            <div className="review-body">
              <div className="rerun-confirm-summary">
                <strong>{selectedHomework.title}</strong>
                <span>{props.jobTemplate?.studentIds.length ?? 0} 名原任务学生</span>
              </div>
              <p className="detail-warning">
                新任务会重新调用模型，并覆盖原任务写入的未发布分数。原任务及旧评分记录不会删除；若分数已发布或已被人工修改，系统会阻止覆盖。
              </p>
            </div>
            <div className="dialog-footer">
              <button className="secondary-button" onClick={() => setShowRerunConfirm(false)}>取消</button>
              <button className="primary-button" disabled={!!busy} onClick={() => void createAndStart()}>
                <RotateCcw size={16} />
                {humanConfirmation ? "创建重批任务" : "确认重批并覆盖"}
              </button>
            </div>
          </div>
        </div>
      )}
      {showStartConfirm && selectedHomework && selectedCourse && (
        <div
          className="dialog-backdrop"
          role="presentation"
          onMouseDown={() => setShowStartConfirm(false)}
        >
          <div
            className="review-dialog start-confirm-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="start-confirm-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="dialog-header">
              <div>
                <span className="eyebrow">开始前确认</span>
                <h2 id="start-confirm-title">确认开始批阅任务</h2>
              </div>
              <button
                className="icon-button"
                title="关闭"
                onClick={() => setShowStartConfirm(false)}
              >
                <X size={18} />
              </button>
            </div>
            <div className="review-body">
              <dl className="start-confirm-summary">
                <div><dt>课程</dt><dd>{selectedCourse.name}</dd></div>
                <div><dt>作业</dt><dd>{selectedHomework.title}</dd></div>
                <div><dt>评分细则</dt><dd>{rubric?.title}</dd></div>
                <div><dt>批阅范围</dt><dd>{scope === "all" ? "全部提交" : "仅未批"}</dd></div>
                <div><dt>人工确认</dt><dd>{humanConfirmation ? "开启" : "关闭"}</dd></div>
              </dl>
              <p className="detail-warning">
                {props.config.adapter_mode === "mock"
                  ? "当前为本地演示模式，不会连接或修改智慧树数据。"
                  : "系统会在运行前再次确认自动发布已关闭，并且只写入未发布成绩。"}
                {humanConfirmation
                  ? "每份评分仍需人工确认。"
                  : "评分通过后将自动写入，请确认配置无误。"}
              </p>
            </div>
            <div className="dialog-footer">
              <button
                className="secondary-button"
                onClick={() => setShowStartConfirm(false)}
              >
                返回检查
              </button>
              <button
                className="primary-button"
                disabled={!!busy}
                onClick={() => void createAndStart()}
              >
                <Play size={16} fill="currentColor" />
                确认并开始
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function JobsView(props: {
  jobs: Job[];
  selectedJob?: Job;
  onSelect: (id: string) => void;
  onRefresh: () => Promise<void>;
  onReuseJob: (job: Job) => void;
  onRerunJob: (job: Job) => void;
  onNotice: (message: string) => void;
  onError: (message: string) => void;
}) {
  const [reviewing, setReviewing] = useState<Submission | null>(null);
  const [openReportOnReview, setOpenReportOnReview] = useState(false);
  const [showRubric, setShowRubric] = useState(false);
  const [showReviewOnly, setShowReviewOnly] = useState(false);
  const [showIncompleteOnly, setShowIncompleteOnly] = useState(false);
  const [preparingManualReview, setPreparingManualReview] = useState("");
  const [updatingConflictOverwrite, setUpdatingConflictOverwrite] = useState(false);
  const [pendingDeleteJob, setPendingDeleteJob] = useState<Job | null>(null);
  const [deletingJob, setDeletingJob] = useState(false);
  const skippedReasons = useMemo(() => {
    const counts = new Map<string, number>();
    for (const submission of props.selectedJob?.submissions ?? []) {
      if (!["skipped", "conflict", "rejected"].includes(submission.status)) continue;
      const reason = submission.status_message || "未记录跳过原因";
      counts.set(reason, (counts.get(reason) ?? 0) + 1);
    }
    return [...counts.entries()]
      .map(([reason, count]) => ({ reason, count }))
      .sort((left, right) => right.count - left.count);
  }, [props.selectedJob]);
  const reviewReasons = useMemo(() => {
    const counts = new Map<string, number>();
    for (const submission of props.selectedJob?.submissions ?? []) {
      if (submission.status !== "waiting_confirmation") continue;
      const reason = submission.status_message || "等待人工确认";
      counts.set(reason, (counts.get(reason) ?? 0) + 1);
    }
    return [...counts.entries()]
      .map(([reason, count]) => ({ reason, count }))
      .sort((left, right) => right.count - left.count);
  }, [props.selectedJob]);
  const displayedSubmissions = useMemo(
    () => (
      showReviewOnly
        ? (props.selectedJob?.submissions ?? []).filter(
          (submission) => submission.status === "waiting_confirmation",
        )
        : showIncompleteOnly
          ? (props.selectedJob?.submissions ?? []).filter(
            (submission) => !completedSubmissionStatuses.has(submission.status),
          )
          : props.selectedJob?.submissions ?? []
    ),
    [props.selectedJob, showIncompleteOnly, showReviewOnly],
  );
  const incompleteCount = useMemo(
    () => (props.selectedJob?.submissions ?? []).filter(
      (submission) => !completedSubmissionStatuses.has(submission.status),
    ).length,
    [props.selectedJob],
  );
  const overwritableConflictCount = useMemo(
    () => (props.selectedJob?.submissions ?? []).filter(
      (submission) => (
        submission.status === "conflict"
        && (
          submission.status_message.startsWith("远端成绩与原任务记录不一致")
          || submission.status_message.startsWith("远端成绩已变化")
        )
      ),
    ).length,
    [props.selectedJob],
  );
  const canConfigureConflictOverwrite = Boolean(
    props.selectedJob?.write_enabled
    && props.selectedJob.scope.overwrite_existing_scores
    && props.selectedJob.scope.rerun_from_job_id
    && !activeJobStatuses.has(props.selectedJob.status)
    && (
      overwritableConflictCount > 0
      || props.selectedJob.scope.allow_conflict_overwrite
    )
  );

  useEffect(() => {
    setShowRubric(false);
    setShowReviewOnly(false);
    setShowIncompleteOnly(false);
    setPreparingManualReview("");
    setUpdatingConflictOverwrite(false);
  }, [props.selectedJob?.id]);

  const start = async (job: Job) => {
    try {
      await api.startJob(job.id);
      await props.onRefresh();
    } catch (error) {
      props.onError(errorMessage(error));
    }
  };
  const pause = async (job: Job) => {
    try {
      await api.pauseJob(job.id);
      await props.onRefresh();
    } catch (error) {
      props.onError(errorMessage(error));
    }
  };
  const updateConflictOverwrite = async (job: Job, enabled: boolean) => {
    setUpdatingConflictOverwrite(true);
    try {
      await api.setConflictOverwrite(job.id, enabled);
      await props.onRefresh();
    } catch (error) {
      props.onError(errorMessage(error));
    } finally {
      setUpdatingConflictOverwrite(false);
    }
  };
  const deleteJob = async () => {
    if (!pendingDeleteJob) return;
    setDeletingJob(true);
    try {
      const result = await api.deleteJob(pendingDeleteJob.id);
      setPendingDeleteJob(null);
      props.onNotice(result.message);
      await props.onRefresh();
    } catch (error) {
      props.onError(errorMessage(error));
    } finally {
      setDeletingJob(false);
    }
  };
  const openManualReview = async (
    submission: Submission,
    reportOpen: boolean,
  ) => {
    if (submission.status === "waiting_confirmation") {
      setOpenReportOnReview(reportOpen);
      setReviewing(submission);
      return;
    }
    setPreparingManualReview(submission.id);
    try {
      const prepared = await api.beginManualReview(submission.id);
      setOpenReportOnReview(reportOpen || hasPdfReport(prepared));
      setReviewing(prepared);
      await props.onRefresh();
    } catch (error) {
      props.onError(errorMessage(error));
    } finally {
      setPreparingManualReview("");
    }
  };

  return (
    <div className="page jobs-page">
      <PageHeader
        title="任务中心"
        subtitle={`${props.jobs.length} 个任务`}
        action={
          <button className="icon-button bordered" title="刷新任务" onClick={() => void props.onRefresh()}>
            <RefreshCw size={16} />
          </button>
        }
      />
      <div className="jobs-layout">
        <div className="job-list">
          {props.jobs.length === 0 && <EmptyState icon={<Gauge />} text="暂无批阅任务" />}
          {props.jobs.map((job) => (
            <button key={job.id} className={`job-list-item ${props.selectedJob?.id === job.id ? "active" : ""}`} onClick={() => props.onSelect(job.id)}>
              <div>
                <strong>{job.homework_title || job.homework_id}</strong>
                <span>{job.course_name || job.course_id}</span>
              </div>
              <div className="job-list-meta">
                <StatusBadge status={job.status} />
                <span>{job.completed_count + job.skipped_count + job.failed_count + job.review_count}/{job.total_count}</span>
                <ChevronRight size={16} />
              </div>
            </button>
          ))}
        </div>

        <div className="job-detail">
          {!props.selectedJob && <EmptyState icon={<ClipboardCheck />} text="选择一个任务查看详情" />}
          {props.selectedJob && (
            <>
              <div className="job-detail-header">
                <div>
                  <span className="eyebrow">{props.selectedJob.course_name}</span>
                  <h2>{props.selectedJob.homework_title}</h2>
                </div>
                <div className="job-actions">
                  <button
                    className="secondary-button"
                    disabled={props.selectedJob.submissions.length === 0}
                    onClick={() => exportJobRecords(props.selectedJob!)}
                  >
                    <Download size={16} />导出全部
                  </button>
                  <button className="secondary-button" onClick={() => setShowRubric(true)}>
                    <SlidersHorizontal size={16} />评分细则
                  </button>
                  {(
                    !activeJobStatuses.has(props.selectedJob.status)
                    && props.selectedJob.submissions.some(
                      (submission) => submission.status === "written",
                    )
                  ) && (
                    <button className="secondary-button" onClick={() => props.onRerunJob(props.selectedJob!)}>
                      <RotateCcw size={16} />修改后重批
                    </button>
                  )}
                  {!activeJobStatuses.has(props.selectedJob.status) && (
                    <button
                      className="secondary-button danger-secondary-button"
                      onClick={() => setPendingDeleteJob(props.selectedJob!)}
                    >
                      <Trash2 size={16} />删除任务
                    </button>
                  )}
                  {props.selectedJob.review_count > 0 && (
                    <button
                      className={showReviewOnly ? "primary-button" : "secondary-button"}
                      onClick={() => {
                        setShowReviewOnly((current) => !current);
                        setShowIncompleteOnly(false);
                      }}
                    >
                      <UserCheck size={16} />
                      待复核 ({props.selectedJob.review_count})
                    </button>
                  )}
                  {incompleteCount > 0 && (
                    <button
                      className={showIncompleteOnly ? "primary-button" : "secondary-button"}
                      onClick={() => {
                        setShowIncompleteOnly((current) => !current);
                        setShowReviewOnly(false);
                      }}
                    >
                      <CircleAlert size={16} />
                      未完成 ({incompleteCount})
                    </button>
                  )}
                  {(
                    ["created", "paused", "failed"].includes(props.selectedJob.status)
                    || (
                      ["completed", "waiting_confirmation"].includes(
                        props.selectedJob.status,
                      )
                      && props.selectedJob.recoverable_count > 0
                    )
                  ) && (
                    <button className="secondary-button" onClick={() => void start(props.selectedJob!)}>
                      <Play size={16} />
                      {props.selectedJob.status === "created"
                        ? "开始"
                        : ["completed", "waiting_confirmation"].includes(
                            props.selectedJob.status,
                          )
                          ? `重试可恢复项 (${props.selectedJob.recoverable_count})`
                          : "继续"}
                    </button>
                  )}
                  {activeJobStatuses.has(props.selectedJob.status) && (
                    <button className="secondary-button" onClick={() => void pause(props.selectedJob!)}>
                      <Pause size={16} />暂停
                    </button>
                  )}
                </div>
              </div>

              {props.selectedJob.error_message && (
                <div className="error-banner"><CircleAlert size={17} />{props.selectedJob.error_message}</div>
              )}
              <div className="metric-strip">
                <Metric label="总人数" value={props.selectedJob.total_count} />
                <Metric label="完成" value={props.selectedJob.completed_count} tone="success" />
                <Metric label="待复核" value={props.selectedJob.review_count} tone="review" />
                <Metric label="跳过" value={props.selectedJob.skipped_count} tone="warning" />
                <Metric label="失败" value={props.selectedJob.failed_count} tone="danger" />
              </div>
              <div className="mode-row">
                <span><UserCheck size={15} />{props.selectedJob.require_human_confirmation ? "人工确认" : "自动确认"}</span>
                <span><Save size={15} />{props.selectedJob.write_enabled ? "写入开启" : "试运行"}</span>
                <span><ShieldCheck size={15} />不发布</span>
              </div>
              {canConfigureConflictOverwrite && (
                <div className={`conflict-overwrite-setting ${props.selectedJob.scope.allow_conflict_overwrite ? "enabled" : ""}`}>
                  <Toggle
                    checked={props.selectedJob.scope.allow_conflict_overwrite}
                    disabled={updatingConflictOverwrite}
                    label="允许冲突继续写入"
                    onChange={(enabled) => void updateConflictOverwrite(props.selectedJob!, enabled)}
                  />
                  <span>
                    {props.selectedJob.scope.allow_conflict_overwrite
                      ? "已允许覆盖远端未发布成绩；已发布成绩和已变化的提交内容仍会阻止写入。"
                      : `${overwritableConflictCount} 条成绩冲突仍受保护，开启后将重新加入待处理队列。`}
                  </span>
                </div>
              )}
              {skippedReasons.length > 0 && (
                <div className="skip-reason-summary">
                  <div><CircleAlert size={16} /><strong>跳过原因</strong></div>
                  <ul>
                    {skippedReasons.map((item) => (
                      <li key={item.reason}>
                        <span>{item.reason}</span>
                        <strong>{item.count} 人</strong>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {reviewReasons.length > 0 && (
                <div className="skip-reason-summary review-reason-summary">
                  <div><UserCheck size={16} /><strong>待复核原因</strong></div>
                  <ul>
                    {reviewReasons.map((item) => (
                      <li key={item.reason}>
                        <span>{item.reason}</span>
                        <strong>{item.count} 人</strong>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="submission-table-wrap">
                <table className="submission-table">
                  <thead>
                    <tr>
                      <th>学生</th>
                      <th>班级</th>
                      <th>文档</th>
                      <th>评分 / 阶段</th>
                      <th>状态</th>
                      <th aria-label="操作" />
                    </tr>
                  </thead>
                  <tbody>
                    {displayedSubmissions.map((submission) => {
                      const isModelReview = (
                        submission.status === "waiting_confirmation"
                        && submission.grade.needs_review === true
                      );
                      const isCompleted = completedSubmissionStatuses.has(
                        submission.status,
                      );
                      const canManuallyGrade = (
                        !isCompleted
                        && !activeJobStatuses.has(props.selectedJob!.status)
                      );
                      return (
                      <tr key={submission.id}>
                        <td><strong>{submission.student_name || "未命名"}</strong><small>{submission.student_number_masked}</small></td>
                        <td>{submission.class_name || "-"}</td>
                        <td>{submission.pdf_files.length}</td>
                        <td>
                          {submission.grade.final_score !== undefined ? `${submission.grade.final_score} 分` : "-"}
                          {submission.grade.detected_stage_name && (
                            <small>{submission.grade.detected_stage_name}</small>
                          )}
                        </td>
                        <td>
                          <StatusBadge
                            status={submission.status}
                            label={isModelReview ? "待复核" : undefined}
                          />
                          {submission.status_message && (
                            <small className="status-reason" title={submission.status_message}>
                              {submission.status_message}
                            </small>
                          )}
                        </td>
                        <td>
                          <div className="row-actions">
                            {canManuallyGrade && hasPdfReport(submission) && (
                              <button
                                className="icon-button"
                                title={`查看${submission.student_name || "该学生"}报告`}
                                disabled={preparingManualReview === submission.id}
                                onClick={() => void openManualReview(submission, true)}
                              >
                                <FileText size={15} />
                              </button>
                            )}
                            <button
                              className="icon-button"
                              title={`导出${submission.student_name || "该学生"}评分记录`}
                              onClick={() => exportSubmissionRecord(
                                submission,
                                props.selectedJob!.rubric,
                                props.selectedJob!.course_name,
                                props.selectedJob!.homework_title,
                              )}
                            >
                              <Download size={15} />
                            </button>
                            <button
                              className={canManuallyGrade ? "text-button" : "icon-button"}
                              title={canManuallyGrade ? "手工查看并评分" : "查看处理详情"}
                              disabled={preparingManualReview === submission.id}
                              onClick={() => {
                                if (canManuallyGrade) {
                                  void openManualReview(submission, false);
                                  return;
                                }
                                setOpenReportOnReview(false);
                                setReviewing(submission);
                              }}
                            >
                              {canManuallyGrade
                                ? preparingManualReview === submission.id
                                  ? "准备中"
                                  : submission.status === "waiting_confirmation"
                                    ? "复核"
                                    : "手工评分"
                                : <Eye size={15} />}
                            </button>
                          </div>
                        </td>
                      </tr>
                      );
                    })}
                    {displayedSubmissions.length === 0 && (
                      <tr>
                        <td colSpan={6} className="empty-row">
                          {showReviewOnly ? "当前没有待复核记录" : "学生列表将在任务启动后加载"}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
      {reviewing && props.selectedJob && (
        <ReviewDialog
          submission={reviewing}
          rubric={props.selectedJob.rubric}
          courseName={props.selectedJob.course_name}
          homeworkTitle={props.selectedJob.homework_title}
          writeEnabled={props.selectedJob.write_enabled}
          modelReview={reviewing.grade.needs_review === true}
          manualReview={reviewing.status_message.startsWith("已转为手工评分")}
          initialReportOpen={openReportOnReview}
          onClose={() => {
            setReviewing(null);
            setOpenReportOnReview(false);
          }}
          onDone={async () => {
            setReviewing(null);
            setOpenReportOnReview(false);
            await props.onRefresh();
          }}
          onError={props.onError}
        />
      )}
      {showRubric && props.selectedJob && (
        <RubricDetailDialog
          rubric={props.selectedJob.rubric}
          onClose={() => setShowRubric(false)}
          onReuse={() => props.onReuseJob(props.selectedJob!)}
        />
      )}
      {pendingDeleteJob && (
        <div
          className="dialog-backdrop"
          role="presentation"
          onMouseDown={() => {
            if (!deletingJob) setPendingDeleteJob(null);
          }}
        >
          <div
            className="review-dialog delete-job-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-job-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="dialog-header">
              <div>
                <span className="eyebrow">删除任务记录</span>
                <h2 id="delete-job-title">{pendingDeleteJob.homework_title}</h2>
              </div>
              <button
                className="icon-button"
                title="关闭"
                disabled={deletingJob}
                onClick={() => setPendingDeleteJob(null)}
              >
                <X size={18} />
              </button>
            </div>
            <div className="review-body">
              <p className="detail-warning">
                将永久删除该任务、学生评分记录和处理日志。智慧树中已经写入的成绩不会被撤销。
              </p>
              <div className="delete-job-summary">
                <span>{pendingDeleteJob.course_name}</span>
                <strong>{pendingDeleteJob.total_count} 名学生</strong>
              </div>
            </div>
            <div className="dialog-footer">
              <button
                className="secondary-button"
                disabled={deletingJob}
                onClick={() => setPendingDeleteJob(null)}
              >
                取消
              </button>
              <button
                className="danger-button"
                disabled={deletingJob}
                onClick={() => void deleteJob()}
              >
                <Trash2 size={16} />
                {deletingJob ? "正在删除" : "确认删除"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function RubricRuleGroup(props: { title: string; items: string[] }) {
  if (props.items.length === 0) return null;
  return (
    <details className="rubric-rule-group">
      <summary>
        <span>{props.title}</span>
        <strong>{props.items.length} 条</strong>
      </summary>
      <ul>{props.items.map((item) => <li key={item}>{item}</li>)}</ul>
    </details>
  );
}

function RubricDetailDialog(props: {
  rubric: Rubric;
  onClose: () => void;
  onReuse: () => void;
}) {
  const [copied, setCopied] = useState(false);

  const copyRubric = async () => {
    await copyText(formatRubricText(props.rubric));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={props.onClose}>
      <div
        className="review-dialog rubric-detail-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="rubric-detail-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="dialog-header">
          <div>
            <span className="eyebrow">任务评分细则</span>
            <h2 id="rubric-detail-title">{props.rubric.title || "评分细则"}</h2>
          </div>
          <button className="icon-button" title="关闭" onClick={props.onClose}><X size={18} /></button>
        </div>
        <div className="review-body rubric-detail-body">
          <div className="rubric-detail-summary">
            <span>总分</span>
            <strong>{props.rubric.total_score}</strong>
            <span>{props.rubric.criteria.length} 个评分项</span>
          </div>
          {props.rubric.grading_mode === "stage_completion" && (
            <section className="detail-section">
              <h3>阶段判定</h3>
              <p className="grade-feedback">
                {props.rubric.stage_scoring_instruction || "先识别当前阶段，再按该阶段完成度评分。"}
              </p>
              <div className="rubric-stage-list">
                {(props.rubric.stages ?? []).map((stage, index) => (
                  <div key={stage.id}>
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <div>
                      <strong>{stage.name}</strong>
                      <p>{stage.description}</p>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}
          {(props.rubric.overall_requirements ?? []).length > 0 && (
            <section className="detail-section">
              <h3>总体要求</h3>
              <ul>
                {(props.rubric.overall_requirements ?? []).map((item) => <li key={item}>{item}</li>)}
              </ul>
            </section>
          )}
          {(props.rubric.score_bands ?? []).length > 0 && (
            <section className="detail-section">
              <h3>完成度分档</h3>
              <div className="rubric-score-band-list">
                {(props.rubric.score_bands ?? []).map((band) => (
                  <div key={band.id}>
                    <div>
                      <strong>{band.name}</strong>
                      <span>{band.min_score}-{band.max_score} 分</span>
                    </div>
                    {band.description && <p>{band.description}</p>}
                    {band.requirements.length > 0 && (
                      <ul>{band.requirements.map((item) => <li key={item}>{item}</li>)}</ul>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}
          {(props.rubric.required_sections ?? []).length > 0 && (
            <section className="detail-section">
              <h3>强制内容清单</h3>
              <ul>
                {(props.rubric.required_sections ?? []).map((item) => <li key={item}>{item}</li>)}
              </ul>
            </section>
          )}
          <section className="detail-section">
            <h3>评分项</h3>
            <div className="rubric-detail-list">
              {props.rubric.criteria.map((criterion, index) => (
                <div className="rubric-detail-item" key={criterion.id}>
                  <span className="criterion-index">{String(index + 1).padStart(2, "0")}</span>
                  <div>
                    <div className="rubric-detail-item-title">
                      <strong>{criterion.name}</strong>
                      <span>{criterion.max_score} 分</span>
                    </div>
                    {criterion.description && <p>{criterion.description}</p>}
                    {criterion.required_evidence.length > 0 && (
                      <div className="grade-reason-list">
                        <span>证据</span>
                        <ul>
                          {criterion.required_evidence.map((item) => <li key={item}>{item}</li>)}
                        </ul>
                      </div>
                    )}
                    {criterion.deduction_rules.length > 0 && (
                      <div className="grade-reason-list deductions">
                        <span>扣分</span>
                        <ul>
                          {criterion.deduction_rules.map((item) => <li key={item}>{item}</li>)}
                        </ul>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
          {(props.rubric.late_rule || props.rubric.resubmission_rule) && (
            <section className="detail-section">
              <h3>附加规则</h3>
              <ul>
                {props.rubric.late_rule && (
                  <li>迟交：{props.rubric.late_rule}（扣 {props.rubric.late_penalty_points} 分）</li>
                )}
                {props.rubric.resubmission_rule && (
                  <li>重交：{props.rubric.resubmission_rule}（扣 {props.rubric.resubmission_penalty_points} 分）</li>
                )}
              </ul>
            </section>
          )}
          {(props.rubric.global_deduction_rules ?? []).length > 0 && (
            <section className="detail-section detail-warning">
              <h3>全局扣分与限制</h3>
              <ul>
                {(props.rubric.global_deduction_rules ?? []).map((item) => <li key={item}>{item}</li>)}
              </ul>
            </section>
          )}
          {(props.rubric.calibration_rules ?? []).length > 0 && (
            <section className="detail-section">
              <h3>批量校准原则</h3>
              <ul>
                {(props.rubric.calibration_rules ?? []).map((item) => <li key={item}>{item}</li>)}
              </ul>
            </section>
          )}
          {props.rubric.feedback_style && (
            <section className="detail-section">
              <h3>评语要求</h3>
              <p className="grade-feedback">{props.rubric.feedback_style}</p>
            </section>
          )}
          {props.rubric.source_text && (
            <section className="detail-section">
              <h3>原始评分细则</h3>
              <pre className="rubric-source-text">{props.rubric.source_text}</pre>
            </section>
          )}
        </div>
        <div className="dialog-footer">
          <button className="secondary-button" onClick={() => void copyRubric()}>
            {copied ? <Check size={16} /> : <Copy size={16} />}
            {copied ? "已复制" : "复制细则"}
          </button>
          <button className="primary-button" onClick={props.onReuse}>
            <BookOpen size={16} />复用到新任务
          </button>
        </div>
      </div>
    </div>
  );
}

function ReviewDialog(props: {
  submission: Submission;
  rubric: Rubric;
  courseName: string;
  homeworkTitle: string;
  writeEnabled: boolean;
  modelReview: boolean;
  manualReview: boolean;
  initialReportOpen: boolean;
  onClose: () => void;
  onDone: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const initialGrade = Array.isArray(props.submission.grade.criterion_scores)
    ? props.submission.grade as GradeDecision
    : null;
  const [grade, setGrade] = useState<GradeDecision | null>(initialGrade);
  const [scoreDrafts, setScoreDrafts] = useState<Record<string, string>>(
    () => Object.fromEntries(
      (initialGrade?.criterion_scores ?? []).map((item) => [
        item.criterion_id,
        props.manualReview && Number(item.score) === 0
          ? ""
          : String(item.score),
      ]),
    ),
  );
  const [manualTotalDraft, setManualTotalDraft] = useState(
    props.manualReview && Number(initialGrade?.final_score) !== 0
      ? String(initialGrade?.final_score)
      : "",
  );
  const [busy, setBusy] = useState(false);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const pdfFile = getPdfReportFile(props.submission);
  const [showReport, setShowReport] = useState(
    props.initialReportOpen && !!pdfFile,
  );
  const reportUrl = `/api/submissions/${encodeURIComponent(props.submission.id)}/report`;
  const canReview = props.submission.status === "waiting_confirmation";
  const manualTotal = Number(manualTotalDraft);
  const total = useMemo(
    () => props.manualReview
      ? (manualTotalDraft.trim() ? Number(manualTotalDraft) : 0)
      : grade?.criterion_scores.reduce((sum, item) => {
        const value = scoreDrafts[item.criterion_id]?.trim();
        return value ? sum + Number(value) : sum;
      }, 0) ?? 0,
    [grade, manualTotalDraft, props.manualReview, scoreDrafts],
  );
  const manualTotalValid = (
    manualTotalDraft.trim() !== ""
    && Number.isFinite(manualTotal)
    && Number.isInteger(manualTotal)
    && manualTotal >= 0
    && manualTotal <= Number(props.rubric.total_score)
  );
  const scoreBandValid = (
    (props.rubric.score_bands ?? []).length === 0
    || !!findScoreBand(props.rubric, total)
  );
  const scoreValuesValid = Boolean(
    grade
    && grade.criterion_scores.every((item) => {
      const criterion = props.rubric.criteria.find(
        (candidate) => candidate.id === item.criterion_id,
      );
      const value = scoreDrafts[item.criterion_id]?.trim() ?? "";
      const score = Number(value);
      return value !== ""
        && Number.isFinite(score)
        && Number.isInteger(score)
        && score >= 0
        && score <= Number(criterion?.max_score ?? 0);
    })
  );
  const canApprove = Boolean(
    grade
    && (
      props.manualReview
        ? manualTotalValid
        : (
          scoreValuesValid
          && total <= Number(props.rubric.total_score)
          && scoreBandValid
        )
    )
  );
  const processEvents = (props.submission.events ?? []).filter(
    (event, index, events) => index === 0 || event.message !== events[index - 1].message,
  );

  const updateCriterion = (id: string, value: string) => {
    if (!grade) return;
    setHasUnsavedChanges(true);
    setScoreDrafts((current) => ({ ...current, [id]: value }));
    setGrade((current) => {
      if (!current) return current;
      const parsedScore = value.trim() === "" ? 0 : Number(value);
      const score = Number.isFinite(parsedScore) ? parsedScore : 0;
      const criterionScores = current.criterion_scores.map((item) =>
        item.criterion_id === id ? { ...item, score } : item
      );
      const nextTotal = criterionScores.reduce(
        (sum, item) => sum + Number(item.score),
        0,
      );
      const scoreBand = findScoreBand(props.rubric, nextTotal);
      const scoreBandChanged = (
        scoreBand?.id ?? ""
      ) !== current.detected_score_band_id;
      return {
        ...current,
        raw_score: nextTotal,
        final_score: nextTotal,
        criterion_scores: criterionScores,
        detected_score_band_id: scoreBand?.id ?? "",
        detected_score_band_name: scoreBand?.name ?? "",
        score_band_evidence: scoreBandChanged && scoreBand
          ? [`人工调整后分项合计 ${nextTotal} 分，落入该档位。`]
          : current.score_band_evidence,
      };
    });
  };

  const requestClose = () => {
    if (
      canReview
      && hasUnsavedChanges
      && !window.confirm("当前评分修改尚未写入，确定关闭吗？")
    ) {
      return;
    }
    props.onClose();
  };

  const approve = async () => {
    if (!grade) return;
    setBusy(true);
    try {
      await api.approveSubmission(props.submission.id, {
        ...grade,
        raw_score: total,
        final_score: total,
      }, props.manualReview ? manualTotal : undefined);
      await props.onDone();
    } catch (error) {
      props.onError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  const reject = async () => {
    setBusy(true);
    try {
      await api.rejectSubmission(props.submission.id);
      await props.onDone();
    } catch (error) {
      props.onError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={requestClose}>
      <div className={`review-dialog ${showReport ? "review-dialog-report-open" : ""}`} role="dialog" aria-modal="true" aria-labelledby="submission-detail-title" onMouseDown={(event) => event.stopPropagation()}>
        <div className="dialog-header">
          <div>
            <span className="eyebrow">
              {canReview
                ? props.manualReview
                  ? "手工评分"
                  : props.modelReview
                    ? "模型复核"
                    : "人工确认"
                : "处理详情"}
            </span>
            <h2 id="submission-detail-title">{props.submission.student_name}</h2>
          </div>
          <div className="dialog-header-actions">
            {pdfFile && (
              <button
                className="secondary-button"
                onClick={() => setShowReport((current) => !current)}
              >
                <FileText size={16} />
                {showReport ? "收起 PDF" : "查看 PDF"}
              </button>
            )}
            <button className="icon-button" title="关闭" onClick={requestClose}><X size={18} /></button>
          </div>
        </div>
        <div className={`review-dialog-content ${showReport ? "review-comparison" : ""}`}>
          {showReport && (
            <section className="report-viewer" aria-label="学生报告">
              <div className="report-viewer-header">
                <div>
                  <span className="eyebrow">原始 PDF</span>
                  <strong>{props.submission.student_name}的提交报告</strong>
                </div>
                <a
                  className="icon-button bordered"
                  href={reportUrl}
                  target="_blank"
                  rel="noreferrer"
                  title="在新窗口打开 PDF"
                >
                  <ExternalLink size={15} />
                </a>
              </div>
              <iframe
                className="report-pdf"
                src={reportUrl}
                title={`${props.submission.student_name}原始 PDF`}
              />
            </section>
          )}
          <div className="review-body">
          <div className="submission-status-detail">
            <StatusBadge status={props.submission.status} />
            <span>{props.submission.status_message || "暂无状态说明"}</span>
          </div>

          {grade ? (
            <>
              {props.manualReview && canReview && (
                <section className="manual-total-editor">
                  <label htmlFor={`manual-total-${props.submission.id}`}>
                    最终总分
                  </label>
                  <div>
                    <input
                      id={`manual-total-${props.submission.id}`}
                      aria-label="最终总分"
                      type="number"
                      inputMode="numeric"
                      min="0"
                      max={Number(props.rubric.total_score)}
                      step="1"
                      value={manualTotalDraft}
                      autoFocus
                      onChange={(event) => {
                        setHasUnsavedChanges(true);
                        setManualTotalDraft(event.target.value);
                      }}
                    />
                    <span>/ {props.rubric.total_score}</span>
                  </div>
                  <p>直接填写该学生的最终成绩，无需拆分到评分项。</p>
                </section>
              )}
              {!props.manualReview && grade.detected_stage_name && (
                <section className="detected-stage">
                  <div>
                    <span>识别阶段</span>
                    <strong>{grade.detected_stage_name}</strong>
                  </div>
                  {(grade.stage_evidence ?? []).length > 0 && (
                    <ul>{grade.stage_evidence.map((item) => <li key={item}>{item}</li>)}</ul>
                  )}
                </section>
              )}
              {!props.manualReview && grade.detected_score_band_name && (
                <section className="detected-stage detected-score-band">
                  <div>
                    <span>完成度分档</span>
                    <strong>{grade.detected_score_band_name}</strong>
                  </div>
                  {(grade.score_band_evidence ?? []).length > 0 && (
                    <ul>{grade.score_band_evidence.map((item) => <li key={item}>{item}</li>)}</ul>
                  )}
                </section>
              )}
              {!props.manualReview && <div className="grade-overview">
                <span>原始分 <strong>{grade.raw_score}</strong></span>
                <span>最终分 <strong>{grade.final_score}</strong></span>
                <span>置信度 <strong>{Math.round(grade.confidence * 100)}%</strong></span>
              </div>}
              {!props.manualReview && <section className="detail-section">
                <h3>分项评分依据</h3>
                {grade.criterion_scores.map((item) => {
                  const criterion = props.rubric.criteria.find((candidate) => candidate.id === item.criterion_id);
                  return (
                    <div className="review-criterion" key={item.criterion_id}>
                      <div>
                        <strong>{criterion?.name || item.criterion_id}</strong>
                        {item.explanation && <p>{item.explanation}</p>}
                        {item.evidence.length > 0 && (
                          <div className="grade-reason-list">
                            <span>证据</span>
                            <ul>{item.evidence.map((evidence) => <li key={evidence}>{evidence}</li>)}</ul>
                          </div>
                        )}
                        {item.deductions.length > 0 && (
                          <div className="grade-reason-list deductions">
                            <span>扣分</span>
                            <ul>{item.deductions.map((deduction) => <li key={deduction}>{deduction}</li>)}</ul>
                          </div>
                        )}
                      </div>
                      {canReview ? (
                        <label className="manual-score-field">
                          <input
                            aria-label={`${criterion?.name || item.criterion_id}得分`}
                            type="number"
                            inputMode="numeric"
                            min="0"
                            max={Number(criterion?.max_score ?? 0)}
                            step="1"
                            value={scoreDrafts[item.criterion_id] ?? ""}
                            onChange={(event) => updateCriterion(
                              item.criterion_id,
                              event.target.value,
                            )}
                          />
                          <span>/ {criterion?.max_score}</span>
                        </label>
                      ) : (
                        <span className="review-score">{item.score} / {criterion?.max_score ?? "-"}</span>
                      )}
                    </div>
                  );
                })}
              </section>}

              {grade.review_reasons.length > 0 && (
                <section className="detail-section detail-warning">
                  <h3>需要复核</h3>
                  <ul>{grade.review_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
                </section>
              )}
              {grade.adjustments.length > 0 && (
                <section className="detail-section">
                  <h3>规则调整</h3>
                  <ul>{grade.adjustments.map((adjustment) => <li key={adjustment}>{adjustment}</li>)}</ul>
                </section>
              )}
              <section className="detail-section">
                <h3>教师评语 <span className="optional-label">选填</span></h3>
                {canReview ? (
                  <textarea
                    rows={3}
                    value={grade.feedback}
                    placeholder="可选填人工评语"
                    onChange={(event) => {
                      setHasUnsavedChanges(true);
                      setGrade((current) => current
                        ? { ...current, feedback: event.target.value }
                        : current);
                    }}
                  />
                ) : (
                  <p className="grade-feedback">{grade.feedback || "无"}</p>
                )}
              </section>
            </>
          ) : (
            <div className="detail-empty">该记录尚未生成评分结果，具体原因见状态说明和处理过程。</div>
          )}

          {(props.submission.pdf_files.length > 0 || props.submission.ignored_files.length > 0) && (
            <section className="detail-section">
              <h3>附件处理</h3>
              <ul className="attachment-list">
                {props.submission.pdf_files.map((file, index) => (
                  <li key={`selected-${index}`}>
                    <span>{String(file.name || `文档 ${index + 1}`)}</span>
                    <strong>已解析</strong>
                  </li>
                ))}
                {props.submission.ignored_files.map((file, index) => (
                  <li key={`ignored-${index}`}>
                    <span>{String(file.name || `附件 ${index + 1}`)}</span>
                    <strong>{String(file.ignored_reason || "已忽略")}</strong>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="detail-section">
            <h3><History size={15} />处理过程</h3>
            {processEvents.length > 0 ? (
              <ol className="process-timeline">
                {processEvents.map((event, index) => (
                  <li key={`${event.created_at}-${event.event_type}-${index}`}>
                    <time>{formatDateTime(event.created_at)}</time>
                    <span>{event.message}</span>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="timeline-empty">历史记录仅保留了当前状态，后续处理将自动记录完整过程。</p>
            )}
          </section>
          </div>
        </div>
        <div className="dialog-footer">
          {grade && (
            <div className="review-total-group">
              <span className="review-total">总分 {total}</span>
              {props.manualReview && !manualTotalValid && (
                <small>请输入 0 至 {props.rubric.total_score} 的整数</small>
              )}
              {!props.manualReview && !scoreValuesValid && (
                <small>请填写所有分项，并使用有效整数</small>
              )}
              {!props.manualReview && scoreValuesValid && !scoreBandValid && (
                <small>总分不在评分细则定义的档位内</small>
              )}
            </div>
          )}
          <button
            className="secondary-button"
            onClick={() => exportSubmissionRecord(
              props.submission,
              props.rubric,
              props.courseName,
              props.homeworkTitle,
              grade ?? undefined,
            )}
          >
            <Download size={16} />导出记录
          </button>
          {canReview ? (
            <>
              <button className="danger-button" disabled={busy} onClick={() => void reject()}>
                {props.manualReview
                  ? "拒绝并标记不写入"
                  : props.modelReview
                    ? "维持跳过"
                    : "拒绝写入"}
              </button>
              <button
                className="primary-button"
                title={props.manualReview && !manualTotalValid
                  ? `请输入 0 至 ${props.rubric.total_score} 的整数`
                  : !props.manualReview && !scoreValuesValid
                    ? "请填写所有分项，并使用有效整数"
                    : !props.manualReview && !scoreBandValid
                    ? "分项总分需要落入评分细则定义的分数档位"
                    : undefined}
                disabled={busy || !canApprove}
                onClick={() => void approve()}
              >
                <Check size={17} />
                {props.manualReview
                  ? props.writeEnabled ? "确认总分并写入" : "确认总分"
                  : props.writeEnabled ? "确认写入" : "确认评分"}
              </button>
            </>
          ) : (
            <button className="secondary-button" onClick={props.onClose}>关闭</button>
          )}
        </div>
      </div>
    </div>
  );
}

function SettingsView(props: {
  config: RuntimeConfig;
  onSaved: (config: RuntimeConfig) => void;
  onError: (message: string) => void;
}) {
  const [form, setForm] = useState(props.config);
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      const payload = { ...form, llm_api_key_configured: undefined, ...(apiKey ? { llm_api_key: apiKey } : {}) };
      const saved = await api.saveConfig(payload);
      setApiKey("");
      props.onSaved(saved);
    } catch (error) {
      props.onError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page settings-page">
      <PageHeader title="系统配置" subtitle="本机配置" />
      <section className="settings-section">
        <h2>平台连接</h2>
        <div className="form-grid two-columns">
          <label>
            <span>运行模式</span>
            <div className="segmented">
              <button className={form.adapter_mode === "zhihuishu" ? "active" : ""} onClick={() => setForm({ ...form, adapter_mode: "zhihuishu" })}>智慧树</button>
              <button className={form.adapter_mode === "mock" ? "active" : ""} onClick={() => setForm({ ...form, adapter_mode: "mock" })}>本地演示</button>
            </div>
          </label>
          <label>
            <span>请求超时（秒）</span>
            <input type="number" min="10" max="300" value={form.request_timeout_seconds} onChange={(event) => setForm({ ...form, request_timeout_seconds: Number(event.target.value) })} />
          </label>
        </div>
      </section>
      <section className="settings-section">
        <h2>大模型</h2>
        <div className="form-grid two-columns">
          <label><span>OpenAI 兼容地址</span><input value={form.llm_base_url} onChange={(event) => setForm({ ...form, llm_base_url: event.target.value })} /></label>
          <label><span>模型名称</span><input value={form.llm_model} onChange={(event) => setForm({ ...form, llm_model: event.target.value })} /></label>
          <label><span>并发评分数</span><input type="number" min="1" value={form.llm_concurrency} onChange={(event) => setForm({ ...form, llm_concurrency: Number(event.target.value) })} /></label>
          <label><span>请求间隔（秒）</span><input type="number" min="0" step="0.1" value={form.llm_request_interval_seconds} onChange={(event) => setForm({ ...form, llm_request_interval_seconds: Number(event.target.value) })} /></label>
          <label><span>最大输出 Token</span><input type="number" min="512" step="512" value={form.llm_max_output_tokens} onChange={(event) => setForm({ ...form, llm_max_output_tokens: Number(event.target.value) })} /></label>
          <label className="full-width">
            <span>API Key {form.llm_api_key_configured && <em>已配置</em>}</span>
            <input type="password" value={apiKey} placeholder={form.llm_api_key_configured ? "留空保持现有密钥" : "输入 API Key"} autoComplete="new-password" onChange={(event) => setApiKey(event.target.value)} />
          </label>
        </div>
      </section>
      <section className="settings-section">
        <h2>文档处理</h2>
        <div className="form-grid two-columns">
          <label><span>单份文档上限（MB）</span><input type="number" min="1" max="500" value={form.max_pdf_megabytes} onChange={(event) => setForm({ ...form, max_pdf_megabytes: Number(event.target.value) })} /></label>
          <label><span>模型文本字符上限</span><input type="number" min="10000" max="500000" step="10000" value={form.max_model_characters} onChange={(event) => setForm({ ...form, max_model_characters: Number(event.target.value) })} /></label>
          <Toggle checked={form.keep_downloaded_pdfs} label="保留已下载文档" onChange={(value) => setForm({ ...form, keep_downloaded_pdfs: value })} />
          <Toggle checked={form.require_human_confirmation_default} label="默认人工确认" onChange={(value) => setForm({ ...form, require_human_confirmation_default: value })} />
        </div>
      </section>
      <div className="settings-actions">
        <button className="primary-button" disabled={busy} onClick={() => void save()}><Save size={17} />{busy ? "正在保存" : "保存配置"}</button>
      </div>
    </div>
  );
}

function PageHeader(props: { title: string; subtitle: string; action?: React.ReactNode }) {
  return <div className="page-header"><div><span className="eyebrow">{props.subtitle}</span><h1>{props.title}</h1></div>{props.action}</div>;
}

function StepLabel(props: { number: string; title: string; complete: boolean }) {
  return <div className="step-label"><span>{props.complete ? <Check size={14} /> : props.number}</span><h2>{props.title}</h2></div>;
}

function Toggle(props: {
  checked: boolean;
  disabled?: boolean;
  label: string;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="toggle-control">
      <button
        type="button"
        role="switch"
        aria-checked={props.checked}
        className={props.checked ? "checked" : ""}
        disabled={props.disabled}
        onClick={() => props.onChange(!props.checked)}
      >
        <span />
      </button>
      <span>{props.label}</span>
    </label>
  );
}

function EmptyState(props: { icon: React.ReactNode; text: string }) {
  return <div className="empty-state">{props.icon}<span>{props.text}</span></div>;
}

function Metric(props: { label: string; value: number; tone?: string }) {
  return <div className={`metric ${props.tone || ""}`}><strong>{props.value}</strong><span>{props.label}</span></div>;
}

const statusLabels: Record<string, string> = {
  created: "待启动",
  preparing: "准备中",
  running: "运行中",
  stopping: "暂停中",
  paused: "已暂停",
  waiting_confirmation: "待确认",
  completed: "已完成",
  failed: "失败",
  pending: "等待中",
  fetching: "拉取中",
  parsing: "解析中",
  grading: "评分中",
  writing: "写入中",
  written: "已写入",
  dry_run_complete: "试运行完成",
  skipped: "已跳过",
  conflict: "冲突",
  rejected: "已拒绝",
};

function StatusBadge({ status, label }: { status: string; label?: string }) {
  return <span className={`status-badge badge-${status}`}>{label || statusLabels[status] || status}</span>;
}

function activeCount(jobs: Job[]) {
  return jobs.filter((job) => activeJobStatuses.has(job.status) || job.status === "waiting_confirmation").length;
}

function getPdfReportFile(submission: Submission) {
  return submission.pdf_files.find((file) => (
    String(file.document_type || file.suffix || "").toLowerCase() === "pdf"
    || String(file.name || "").toLowerCase().endsWith(".pdf")
  ));
}

function hasPdfReport(submission: Submission) {
  return !!getPdfReportFile(submission);
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function findScoreBand(
  rubric: Rubric,
  score: number,
): NonNullable<Rubric["score_bands"]>[number] | undefined {
  return (rubric.score_bands ?? []).find((band) => {
    const minimum = Number(band.min_score);
    const maximum = Number(band.max_score);
    return score >= minimum && (
      score < maximum
      || (maximum === Number(rubric.total_score) && score === maximum)
    );
  });
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function cloneRubric(rubric: Rubric): Rubric {
  return {
    ...rubric,
    stages: (rubric.stages ?? []).map((stage) => ({
      ...stage,
      completion_signals: [...stage.completion_signals],
      expected_deliverables: [...stage.expected_deliverables],
    })),
    overall_requirements: [...(rubric.overall_requirements ?? [])],
    score_bands: (rubric.score_bands ?? []).map((band) => ({
      ...band,
      requirements: [...band.requirements],
    })),
    required_sections: [...(rubric.required_sections ?? [])],
    global_deduction_rules: [...(rubric.global_deduction_rules ?? [])],
    calibration_rules: [...(rubric.calibration_rules ?? [])],
    criteria: rubric.criteria.map((criterion) => ({
      ...criterion,
      required_evidence: [...criterion.required_evidence],
      deduction_rules: [...criterion.deduction_rules],
    })),
  };
}

function rubricContextKey(value: string): string {
  if (/阶段二|第二阶段/.test(value)) return "stage-two";
  if (/阶段三|第三阶段/.test(value)) return "stage-three";
  if (/最终|大报告/.test(value)) return "final-report";
  return "";
}

function recommendRubricTemplate(
  homeworkTitle: string,
  templates: Array<{ id: string; label: string }>,
): string {
  const contextKey = rubricContextKey(homeworkTitle);
  if (!contextKey) return "";
  return templates.find(
    (template) => rubricContextKey(template.label) === contextKey,
  )?.id ?? "";
}

function formatRubricText(rubric: Rubric) {
  const lines = [
    rubric.title || "评分细则",
    `总分：${rubric.total_score} 分`,
    "",
  ];
  if (rubric.grading_mode === "stage_completion") {
    lines.push("评分方式：先判阶段，再按当前阶段完成度评分");
    if (rubric.stage_scoring_instruction) {
      lines.push(rubric.stage_scoring_instruction);
    }
    lines.push("", "阶段定义：");
    (rubric.stages ?? []).forEach((stage, index) => {
      lines.push(`${index + 1}. ${stage.name}`);
      if (stage.description) lines.push(stage.description);
      if (stage.completion_signals.length > 0) {
        lines.push(`完成标志：${stage.completion_signals.join("；")}`);
      }
      if (stage.expected_deliverables.length > 0) {
        lines.push(`应有成果：${stage.expected_deliverables.join("；")}`);
      }
    });
    lines.push("");
  }
  if ((rubric.overall_requirements ?? []).length > 0) {
    lines.push("总体要求：");
    lines.push(...(rubric.overall_requirements ?? []).map((item) => `- ${item}`));
    lines.push("");
  }
  if ((rubric.score_bands ?? []).length > 0) {
    lines.push("完成度分档：");
    (rubric.score_bands ?? []).forEach((band) => {
      lines.push(`${band.min_score}-${band.max_score} 分 ${band.name}`);
      if (band.description) lines.push(band.description);
      lines.push(...band.requirements.map((item) => `- ${item}`));
    });
    lines.push("");
  }
  if ((rubric.required_sections ?? []).length > 0) {
    lines.push("强制内容清单：");
    lines.push(...(rubric.required_sections ?? []).map((item) => `- ${item}`));
    lines.push("");
  }
  lines.push("评分项：");
  rubric.criteria.forEach((criterion, index) => {
    lines.push(`${index + 1}. ${criterion.name}（${criterion.max_score} 分）`);
    if (criterion.description) lines.push(criterion.description);
    if (criterion.required_evidence.length > 0) {
      lines.push("证据要求：");
      lines.push(...criterion.required_evidence.map((item) => `- ${item}`));
    }
    if (criterion.deduction_rules.length > 0) {
      lines.push("扣分规则：");
      lines.push(...criterion.deduction_rules.map((item) => `- ${item}`));
    }
    lines.push("");
  });
  if ((rubric.global_deduction_rules ?? []).length > 0) {
    lines.push("全局扣分与限制：");
    lines.push(...(rubric.global_deduction_rules ?? []).map((item) => `- ${item}`));
    lines.push("");
  }
  if ((rubric.calibration_rules ?? []).length > 0) {
    lines.push("批量校准原则：");
    lines.push(...(rubric.calibration_rules ?? []).map((item) => `- ${item}`));
    lines.push("");
  }
  if (rubric.late_rule) {
    lines.push(`迟交规则：${rubric.late_rule}（扣 ${rubric.late_penalty_points} 分）`);
  }
  if (rubric.resubmission_rule) {
    lines.push(`重交规则：${rubric.resubmission_rule}（扣 ${rubric.resubmission_penalty_points} 分）`);
  }
  if (rubric.feedback_style) lines.push(`评语要求：${rubric.feedback_style}`);
  return lines.join("\n").trim();
}

function exportJobRecords(job: Job) {
  const headers = [
    "学生姓名",
    "学号",
    "班级",
    "状态",
    "状态说明",
    "原始分",
    "最终分",
    "识别阶段",
    "阶段判定依据",
    "完成度分档",
    "分档判定依据",
    "置信度",
    "需要复核",
    "教师评语",
    "分项评分依据",
    "规则调整",
    "附件处理",
    "处理过程",
    "更新时间",
  ];
  const rows = job.submissions.map((submission) => {
    const grade = submission.grade;
    return [
      submission.student_name,
      submission.student_number_masked,
      submission.class_name,
      statusLabels[submission.status] || submission.status,
      submission.status_message,
      grade.raw_score ?? "",
      grade.final_score ?? "",
      grade.detected_stage_name ?? "",
      grade.stage_evidence?.join("\n") ?? "",
      grade.detected_score_band_name ?? "",
      grade.score_band_evidence?.join("\n") ?? "",
      typeof grade.confidence === "number" ? `${Math.round(grade.confidence * 100)}%` : "",
      grade.needs_review === undefined ? "" : grade.needs_review ? "是" : "否",
      grade.feedback ?? "",
      formatCriterionResult(grade, job.rubric),
      grade.adjustments?.join("\n") ?? "",
      formatAttachmentResult(submission),
      formatProcessEvents(submission),
      formatDateTime(submission.updated_at),
    ];
  });
  const csv = `\uFEFF${[headers, ...rows]
    .map((row) => row.map(csvCell).join(","))
    .join("\r\n")}`;
  downloadFile(
    `${safeFilename(job.course_name)}-${safeFilename(job.homework_title)}-评分记录.csv`,
    csv,
    "text/csv;charset=utf-8",
  );
}

function exportSubmissionRecord(
  submission: Submission,
  rubric: Rubric,
  courseName: string,
  homeworkTitle: string,
  gradeOverride?: Partial<GradeDecision>,
) {
  const grade = gradeOverride ?? submission.grade;
  const sections = [
    "学生评分记录",
    `课程：${courseName || "-"}`,
    `作业：${homeworkTitle || "-"}`,
    `学生：${submission.student_name || "未命名"}`,
    `学号：${submission.student_number_masked || "-"}`,
    `班级：${submission.class_name || "-"}`,
    `状态：${statusLabels[submission.status] || submission.status}`,
    `状态说明：${submission.status_message || "无"}`,
    `更新时间：${formatDateTime(submission.updated_at)}`,
    "",
    "【评分结果】",
    `原始分：${grade.raw_score ?? "-"}`,
    `最终分：${grade.final_score ?? "-"}`,
    `识别阶段：${grade.detected_stage_name || "-"}`,
    `阶段判定依据：${grade.stage_evidence?.join("；") || "-"}`,
    `完成度分档：${grade.detected_score_band_name || "-"}`,
    `分档判定依据：${grade.score_band_evidence?.join("；") || "-"}`,
    `置信度：${typeof grade.confidence === "number" ? `${Math.round(grade.confidence * 100)}%` : "-"}`,
    `需要复核：${grade.needs_review === undefined ? "-" : grade.needs_review ? "是" : "否"}`,
    `教师评语：${grade.feedback || "无"}`,
    "",
    "【分项评分依据】",
    formatCriterionResult(grade, rubric) || "尚未生成",
    "",
    "【规则调整】",
    grade.adjustments?.join("\n") || "无",
    "",
    "【附件处理】",
    formatAttachmentResult(submission) || "无",
    "",
    "【处理过程】",
    formatProcessEvents(submission) || "无",
  ];
  downloadFile(
    `${safeFilename(homeworkTitle)}-${safeFilename(submission.student_name || submission.student_id)}-评分记录.txt`,
    sections.join("\n"),
    "text/plain;charset=utf-8",
  );
}

function formatCriterionResult(grade: Partial<GradeDecision>, rubric: Rubric) {
  return (grade.criterion_scores ?? []).map((item, index) => {
    const criterion = rubric.criteria.find((candidate) => candidate.id === item.criterion_id);
    const lines = [
      `${index + 1}. ${criterion?.name || item.criterion_id}：${item.score} / ${criterion?.max_score ?? "-"}`,
    ];
    if (item.explanation) lines.push(`说明：${item.explanation}`);
    if (item.evidence.length > 0) lines.push(`证据：${item.evidence.join("；")}`);
    if (item.deductions.length > 0) lines.push(`扣分：${item.deductions.join("；")}`);
    return lines.join("\n");
  }).join("\n\n");
}

function formatAttachmentResult(submission: Submission) {
  const selected = submission.pdf_files.map(
    (file) => `${String(file.name || "未命名文档")}：已解析`,
  );
  const ignored = submission.ignored_files.map(
    (file) => `${String(file.name || "未命名附件")}：${String(file.ignored_reason || "已忽略")}`,
  );
  return [...selected, ...ignored].join("\n");
}

function formatProcessEvents(submission: Submission) {
  return submission.events
    .filter((event, index, events) => index === 0 || event.message !== events[index - 1].message)
    .map((event) => `${formatDateTime(event.created_at)} ${event.message}`)
    .join("\n");
}

function csvCell(value: unknown) {
  let text = String(value ?? "");
  if (/^[=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replace(/"/g, "\"\"")}"`;
}

function safeFilename(value: string) {
  return value.replace(/[\\/:*?"<>|\u0000-\u001F]/g, "_").trim() || "未命名";
}

function downloadFile(filename: string, content: string, contentType: string) {
  const blob = new Blob([content], { type: contentType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

async function copyText(value: string) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch {
      // Fall back for browsers that expose Clipboard API without permission.
    }
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

export default App;
