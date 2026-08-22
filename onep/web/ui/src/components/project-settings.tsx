import { useEffect, useState } from "react";
import { Download, FlaskConical, Play, Save, Trash2 } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { api, Project, ProjectSettings } from "../api";
import { keys } from "../queries";
import { Button, Card, Modal, SectionTitle } from "./ui";

export function ProjectSettingsPanel({
  project,
  settings,
}: {
  project: Project;
  settings?: ProjectSettings;
}) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const [form, setForm] = useState<Record<string, string>>({});
  const [commands, setCommands] = useState("");
  const [removeOpen, setRemoveOpen] = useState(false);
  const [confirmName, setConfirmName] = useState("");
  useEffect(() => {
    if (settings) {
      const value = settings.defaults;
      setForm(
        Object.fromEntries(
          Object.entries(value).map(([key, item]) => [key, String(item ?? "")]),
        ),
      );
      setCommands(((value.test_commands as string[]) || []).join("\n"));
    }
  }, [settings]);
  const save = useMutation({
    mutationFn: () =>
      api.updateProjectSettings(project.id, settings?.revision || "", {
        max_rounds: Number(form.max_rounds),
        max_repairs_per_slice: Number(form.max_repairs_per_slice),
        max_cost: Number(form.max_cost),
        deploy_mode: form.deploy_mode,
        non_interactive: true,
        verbose: form.verbose === "true",
        default_model: form.default_model || "",
        default_provider: form.default_provider || "",
        complex_model: form.complex_model || "",
        complex_provider: form.complex_provider || "",
        test_commands: commands
          .split("\n")
          .map((value) => value.trim())
          .filter(Boolean),
      }),
    onSuccess: (value) => {
      client.setQueryData(keys.projectSettings(project.id), value);
      toast.success("项目设置已保存，将在下次调用时生效");
    },
    onError: (error) => toast.error(error.message),
  });
  const discover = useMutation({
    mutationFn: () => api.discoverTests(project.id),
    onSuccess: (value) => {
      setCommands(value.commands.join("\n"));
      toast.success("已发现质量命令，尚未执行");
    },
    onError: (error) => toast.error(error.message),
  });
  const testModel = useMutation({
    mutationFn: () => api.testModel(project.id, "default"),
    onSuccess: () => toast.success("连接测试已进入队列，可能产生少量模型费用"),
    onError: (error) => toast.error(error.message),
  });
  const remove = useMutation({
    mutationFn: () => api.removeProject(project.id),
    onSuccess: () => {
      toast.success("项目记录已删除，源码和审计历史已保留");
      navigate("/projects");
      client.invalidateQueries({ queryKey: keys.projects });
    },
    onError: (error) => toast.error(error.message),
  });
  const update = (key: string, value: string) =>
    setForm((current) => ({ ...current, [key]: value }));
  async function download(format: "md" | "json") {
    try {
      const { data } = await api.exportAnalysis(project.id, format);
      const url = URL.createObjectURL(
        new Blob([data.content], { type: data.media_type }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = data.filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "导出失败");
    }
  }
  return (
    <div className="settings-grid project-settings">
      <Card>
        <SectionTitle eyebrow="PROJECT" title="项目" />
        <dl>
          <dt>工作目录</dt>
          <dd>{project.workspace_path}</dd>
          <dt>项目 ID</dt>
          <dd>{project.id}</dd>
          <dt>模式</dt>
          <dd>{project.mode}</dd>
        </dl>
        <div className="settings-actions">
          <Button onClick={() => download("md")}>
            <Download size={14} />
            导出分析
          </Button>
          <Button variant="danger" onClick={() => setRemoveOpen(true)}>
            <Trash2 size={14} />
            删除项目记录
          </Button>
        </div>
      </Card>
      <Card>
        <SectionTitle
          eyebrow="NEXT INVOCATION"
          title="项目执行设置"
          meta={
            settings?.is_running ? (
              <span className="inline-note">当前运行不会改变</span>
            ) : undefined
          }
        />
        <div className="settings-group two">
          <label className="field">
            <span>最大轮次</span>
            <input
              type="number"
              min="1"
              value={form.max_rounds || ""}
              onChange={(event) => update("max_rounds", event.target.value)}
            />
          </label>
          <label className="field">
            <span>每切片修复次数</span>
            <input
              type="number"
              min="1"
              value={form.max_repairs_per_slice || ""}
              onChange={(event) =>
                update("max_repairs_per_slice", event.target.value)
              }
            />
          </label>
          <label className="field">
            <span>成本上限</span>
            <input
              type="number"
              min="0"
              step="0.1"
              value={form.max_cost || ""}
              onChange={(event) => update("max_cost", event.target.value)}
            />
          </label>
          <label className="field">
            <span>部署模式</span>
            <select
              value={form.deploy_mode || "verify"}
              onChange={(event) => update("deploy_mode", event.target.value)}
            >
              <option value="verify">验证后停止</option>
              <option value="local">保留本地服务</option>
              <option value="none">跳过</option>
            </select>
          </label>
          <label className="field">
            <span>默认模型覆盖</span>
            <input
              value={form.default_model || ""}
              onChange={(event) => update("default_model", event.target.value)}
              placeholder="继承全局"
            />
          </label>
          <label className="field">
            <span>默认 Provider</span>
            <input
              value={form.default_provider || ""}
              onChange={(event) =>
                update("default_provider", event.target.value)
              }
              placeholder="继承全局"
            />
          </label>
          <label className="field">
            <span>复杂模型覆盖</span>
            <input
              value={form.complex_model || ""}
              onChange={(event) => update("complex_model", event.target.value)}
              placeholder="继承全局"
            />
          </label>
          <label className="field">
            <span>复杂 Provider</span>
            <input
              value={form.complex_provider || ""}
              onChange={(event) =>
                update("complex_provider", event.target.value)
              }
              placeholder="继承全局"
            />
          </label>
        </div>
        <label className="field">
          <span>质量命令（每行一条）</span>
          <textarea
            className="commands-editor"
            value={commands}
            onChange={(event) => setCommands(event.target.value)}
            placeholder="pytest -q\nnpm run build"
          />
        </label>
        <div className="settings-actions">
          <Button
            onClick={() => discover.mutate()}
            disabled={discover.isPending}
          >
            <FlaskConical size={14} />
            发现命令
          </Button>
          <Button
            onClick={() => testModel.mutate()}
            disabled={testModel.isPending}
          >
            <Play size={14} />
            测试模型
          </Button>
          <Button
            variant="primary"
            onClick={() => save.mutate()}
            disabled={save.isPending}
          >
            <Save size={14} />
            保存项目设置
          </Button>
        </div>
      </Card>
      <Modal
        open={removeOpen}
        onOpenChange={setRemoveOpen}
        title="删除项目记录"
        detail="源码和工作目录会保留，历史审计记录也不会被清除。"
        footer={
          <>
            <Button variant="ghost" onClick={() => setRemoveOpen(false)}>
              取消
            </Button>
            <Button
              variant="danger"
              disabled={confirmName !== project.name || remove.isPending}
              onClick={() => remove.mutate()}
            >
              确认删除
            </Button>
          </>
        }
      >
        <label className="field">
          <span>输入项目名以确认：{project.name}</span>
          <input
            autoFocus
            value={confirmName}
            onChange={(event) => setConfirmName(event.target.value)}
          />
        </label>
      </Modal>
    </div>
  );
}
