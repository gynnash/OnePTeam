import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const statusLabel: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  cancel_requested: "正在停止",
  succeeded: "已完成",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  paused: "已暂停",
  blocked: "已阻塞",
  pending: "等待中",
  confirmed: "已确认",
  assumed: "假设",
  missing: "未确认",
  conflicted: "有冲突",
  not_applicable: "不适用",
  accepted: "已接受",
  rejected: "已拒绝",
  replaced: "已替换",
  passed: "已通过",
  low: "低风险",
  medium: "中风险",
  high: "高风险",
  critical: "严重风险",
  stopped: "已停止",
  idea: "想法",
  discovery: "需求发现",
  prd_review: "PRD 待审批",
  ready: "待执行",
  executing: "实现中",
  verifying: "验证中",
  knowledge_distilling: "知识提炼",
  delivered: "已交付",
  review: "待审批",
  approved: "已批准",
  observed: "已观察",
  validated: "已验证",
  contradicted: "已反驳",
  superseded: "已过期",
  supported: "有证据",
  needs_confirmation: "待确认",
  direct: "Direct",
  plan_then_execute: "Plan → Execute",
  goal: "Goal",
  plan_then_goal: "Plan → Goal",
  default: "默认",
  runtime_permission: "权限请求",
  technical_question: "技术问题",
};

export const discoveryDimensionLabel: Record<string, string> = {
  target_user: "目标用户",
  core_problem: "核心问题",
  primary_scenario: "主场景",
  value_proposition: "价值主张",
  product_scope: "产品范围",
  release_boundary: "首发边界",
  success_metrics: "成功指标",
  constraints: "约束条件",
  roles_permissions: "角色与权限",
  data_privacy: "数据与隐私",
  payments: "支付与计费",
  migration: "数据迁移",
  integrations: "外部集成",
  multi_tenant: "多租户边界",
};

export const stageLabel: Record<string, string> = {
  init: "准备",
  understand: "理解目标",
  research: "架构研究",
  design: "方案设计",
  plan: "制定计划",
  build: "执行变更",
  implement: "执行变更",
  verify: "质量验证",
  test: "质量验证",
  review: "独立评审",
  reflect: "结果反思",
  stop: "整理交付",
  finished: "完成",
  failed: "失败",
  cancelled: "已取消",
};

export function shortTime(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
}

export function summarize(value: unknown, limit = 180) {
  const text = typeof value === "string" ? value : JSON.stringify(value ?? "");
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

export function projectHue(value: string) {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = value.charCodeAt(index) + ((hash << 5) - hash);
  }
  return 248 + (Math.abs(hash) % 52);
}
