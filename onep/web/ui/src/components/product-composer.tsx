import { FormEvent, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { Lightbulb, FolderGit2, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { studioApi } from "../api";
import { studioKeys } from "../queries";
import { useUIStore } from "../store";
import { Button, Modal } from "./ui";

export function ProductComposer() {
  const open = useUIStore((state) => state.composerOpen);
  const draft = useUIStore((state) => state.composerDraft);
  const setOpen = useUIStore((state) => state.setComposerOpen);
  const [idea, setIdea] = useState("");
  const [repo, setRepo] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const client = useQueryClient();

  useEffect(() => {
    if (!open) return;
    if (draft.goal !== undefined) setIdea(draft.goal);
    if (draft.source !== undefined) setRepo(draft.source);
  }, [draft, open]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!idea.trim()) return;
    setBusy(true);
    try {
      const result = await studioApi.createProject({
        idea: idea.trim(),
        repo: repo.trim(),
        name: name.trim() || undefined,
      });
      toast.success("项目已进入需求发现，不会在 PRD 批准前修改代码");
      setOpen(false);
      setIdea("");
      setRepo("");
      setName("");
      await client.invalidateQueries({ queryKey: studioKeys.projects });
      navigate(`/projects/${result.project.id}/conversation`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "创建项目失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={setOpen}
      title="从一句话开始定义产品"
      detail="OnePTeam 会先理解、提问并生成完整 PRD；确认之前不会写代码。"
      side
      footer={
        <>
          <Button variant="ghost" onClick={() => setOpen(false)}>取消</Button>
          <Button
            variant="primary"
            type="submit"
            form="product-composer"
            disabled={busy || !idea.trim()}
          >
            {busy ? "正在分析…" : "开始产品发现"}
          </Button>
        </>
      }
    >
      <form id="product-composer" className="task-form" onSubmit={submit}>
        <div className="intent-resolution">
          <Lightbulb size={19} />
          <div>
            <b>先定位产品，再交付功能</b>
            <span>系统每轮最多提出三个真正影响产品方向的问题。</span>
          </div>
        </div>
        <label className="field task-goal-field">
          <span>你想做一个什么产品？</span>
          <textarea
            autoFocus
            value={idea}
            onChange={(event) => setIdea(event.target.value)}
            placeholder="例如：让独立开发者从一句话需求形成 PRD，并由 Codex 完成可验证交付"
          />
        </label>
        <label className="field">
          <span><FolderGit2 size={14} /> 现有仓库或未来工作目录（可选）</span>
          <input
            value={repo}
            onChange={(event) => setRepo(event.target.value)}
            placeholder="/本地/代码路径；留空将使用 OnePTeam 管理目录"
          />
        </label>
        <label className="field">
          <span>项目名称（可选）</span>
          <input value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <div className="form-note">
          <ShieldCheck size={16} />
          <span>只有你批准 PRD 和当前 Release 后，Codex 才能获得写入工作树。</span>
        </div>
      </form>
    </Modal>
  );
}

