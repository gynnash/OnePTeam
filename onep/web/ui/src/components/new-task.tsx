import { FormEvent, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { Blocks, Code2, Search, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { api } from "../api";
import { keys } from "../queries";
import { useUIStore } from "../store";
import { Button, Modal } from "./ui";

type Workflow = "build" | "analyze" | "optimize";
const choices = [
  {
    id: "build" as const,
    title: "构建应用",
    detail: "从目标到可验证交付",
    icon: Sparkles,
  },
  {
    id: "analyze" as const,
    title: "分析代码",
    detail: "发现结构与策略机会",
    icon: Search,
  },
  {
    id: "optimize" as const,
    title: "自动优化",
    detail: "规划、实现并验证改进",
    icon: Code2,
  },
];

export function NewTaskSheet() {
  const open = useUIStore((state) => state.composerOpen);
  const setOpen = useUIStore((state) => state.setComposerOpen);
  const client = useQueryClient();
  const navigate = useNavigate();
  const [workflow, setWorkflow] = useState<Workflow>("build");
  const [goal, setGoal] = useState("");
  const [source, setSource] = useState("");
  const [name, setName] = useState("");
  const [maxCost, setMaxCost] = useState("0");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!goal.trim() || (workflow !== "build" && !source.trim())) return;
    setBusy(true);
    try {
      if (workflow === "build") {
        const result = await api.create({
          requirement: goal.trim(),
          name: name.trim() || undefined,
          workspace_path: source.trim() || undefined,
          options: { max_cost: Number(maxCost) || 0, non_interactive: true },
        });
        toast.success("构建任务已进入队列");
        navigate(`/projects/${result.project.id}/goal`);
      } else {
        const capability =
          workflow === "analyze" ? "analysis.start" : "optimization.start";
        const result = await api.startWorkflow(capability, {
          source: source.trim(),
          name: name.trim() || undefined,
          goal: goal.trim(),
          max_cost: Number(maxCost) || 0,
          max_rounds: workflow === "optimize" ? 5 : undefined,
        });
        toast.success(`任务已进入队列 · ${result.job_id.slice(0, 8)}`);
        navigate("/tasks");
      }
      setOpen(false);
      setGoal("");
      setName("");
      setSource("");
      client.invalidateQueries({ queryKey: keys.jobs });
      client.invalidateQueries({ queryKey: keys.projects });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "创建任务失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={setOpen}
      side
      title="新建任务"
      detail="选择工作流，定义这次运行的可验证目标。"
    >
      <form className="task-form" onSubmit={submit}>
        <div className="workflow-grid">
          {choices.map(({ id, title, detail, icon: Icon }) => (
            <button
              type="button"
              key={id}
              className={workflow === id ? "selected" : ""}
              onClick={() => setWorkflow(id)}
            >
              <Icon size={19} />
              <b>{title}</b>
              <span>{detail}</span>
            </button>
          ))}
        </div>
        <label className="field">
          <span>{workflow === "build" ? "目标" : "本次关注目标"}</span>
          <textarea
            autoFocus
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
            placeholder={
              workflow === "build"
                ? "例如：创建一个聚合技术动态并生成结构化周报的研究 Agent"
                : "说明希望重点分析或改进的问题"
            }
          />
        </label>
        <label className="field">
          <span>
            {workflow === "build"
              ? "已有 Git 目录（可选）"
              : "Git 目录或仓库地址"}
          </span>
          <input
            value={source}
            onChange={(event) => setSource(event.target.value)}
            placeholder="/path/to/repository"
          />
        </label>
        <div className="field-grid">
          <label className="field">
            <span>项目名称（可选）</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="自动生成"
            />
          </label>
          <label className="field">
            <span>成本上限（美元）</span>
            <input
              inputMode="decimal"
              value={maxCost}
              onChange={(event) => setMaxCost(event.target.value)}
            />
          </label>
        </div>
        <div className="form-note">
          <Blocks size={16} />
          <span>任务会在持久队列中运行；刷新页面不会丢失进度。</span>
        </div>
        <footer>
          <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button
            type="submit"
            variant="primary"
            disabled={
              busy || !goal.trim() || (workflow !== "build" && !source.trim())
            }
          >
            {busy ? "正在创建…" : "开始执行"}
          </Button>
        </footer>
      </form>
    </Modal>
  );
}
