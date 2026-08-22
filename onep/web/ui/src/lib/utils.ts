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
  stopped: "已停止",
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
