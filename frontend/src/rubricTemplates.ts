import type { Rubric } from "./types";

export type RubricTemplate = {
  id: string;
  label: string;
  summary: string;
  rubric: Rubric;
  updatedAt?: string;
};

const CUSTOM_TEMPLATE_STORAGE_KEY = "edugrader.custom-rubric-templates.v1";

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
