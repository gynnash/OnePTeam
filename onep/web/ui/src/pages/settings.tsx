import { FormEvent, useEffect, useState } from "react";
import {
  CheckCircle2,
  KeyRound,
  MonitorCog,
  Play,
  RotateCcw,
  Save,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, GlobalSettings } from "../api";
import {
  Badge,
  Button,
  Card,
  LoadFailure,
  PageTitle,
  SectionTitle,
  Skeleton,
} from "../components/ui";
import { keys } from "../queries";
import { Density, Theme, useUIStore } from "../store";

type FormState = {
  default_model: string;
  default_provider: string;
  complex_model: string;
  complex_provider: string;
  test_timeout: string;
  max_rounds: string;
  max_repairs_per_slice: string;
  max_cost: string;
  deploy_mode: string;
};
const empty: FormState = {
  default_model: "",
  default_provider: "",
  complex_model: "",
  complex_provider: "",
  test_timeout: "300",
  max_rounds: "100",
  max_repairs_per_slice: "8",
  max_cost: "0",
  deploy_mode: "verify",
};

function fromSettings(value?: GlobalSettings): FormState {
  if (!value) return empty;
  const llm = value.settings.llm;
  const pipeline = value.settings.pipeline;
  const run = value.settings.run_defaults;
  return {
    default_model: String(llm.default_model || ""),
    default_provider: String(llm.default_provider || ""),
    complex_model: String(llm.complex_model || ""),
    complex_provider: String(llm.complex_provider || ""),
    test_timeout: String(pipeline.test_timeout || 300),
    max_rounds: String(run.max_rounds || 100),
    max_repairs_per_slice: String(run.max_repairs_per_slice || 8),
    max_cost: String(run.max_cost || 0),
    deploy_mode: String(run.deploy_mode || "verify"),
  };
}

export function GlobalSettingsPage() {
  const query = useQuery({
    queryKey: keys.globalSettings,
    queryFn: api.globalSettings,
  });
  const client = useQueryClient();
  const [form, setForm] = useState<FormState>(empty);
  const theme = useUIStore((state) => state.theme);
  const setTheme = useUIStore((state) => state.setTheme);
  const density = useUIStore((state) => state.density);
  const setDensity = useUIStore((state) => state.setDensity);
  useEffect(() => {
    if (query.data) setForm(fromSettings(query.data));
  }, [query.data]);
  const save = useMutation({
    mutationFn: () =>
      api.updateGlobalSettings(query.data?.revision || "", {
        llm: {
          default_model: form.default_model,
          default_provider: form.default_provider,
          complex_model: form.complex_model,
          complex_provider: form.complex_provider,
        },
        pipeline: { test_timeout: Number(form.test_timeout) },
        run_defaults: {
          max_rounds: Number(form.max_rounds),
          max_repairs_per_slice: Number(form.max_repairs_per_slice),
          max_cost: Number(form.max_cost),
          deploy_mode: form.deploy_mode,
        },
      }),
    onSuccess: (value) => {
      client.setQueryData(keys.globalSettings, value);
      toast.success("全局设置已保存，将应用到后续任务");
    },
    onError: (error) => toast.error(error.message),
  });
  const test = useMutation({
    mutationFn: (kind: "default" | "complex") => api.testModel("", kind),
    onSuccess: () => toast.success("连接测试已进入队列，可能产生少量模型费用"),
    onError: (error) => toast.error(error.message),
  });
  const providers = (query.data?.settings.llm.providers || {}) as Record<
    string,
    { configured?: boolean; source?: string }
  >;
  const update = (key: keyof FormState, value: string) =>
    setForm((current) => ({ ...current, [key]: value }));
  return (
    <div className="page">
      <PageTitle
        eyebrow="SYSTEM"
        title="设置"
        detail="管理界面偏好、模型路由和后续任务的默认执行合同。密钥不会通过 Web 返回。"
        actions={
          <Button
            variant="primary"
            disabled={save.isPending || !query.data}
            onClick={() => save.mutate()}
          >
            <Save size={16} />
            保存变更
          </Button>
        }
      />
      {query.isLoading ? (
        <Skeleton className="h-96" />
      ) : query.isError ? (
        <Card>
          <LoadFailure
            title="无法读取全局设置"
            detail="现有配置没有被修改。重新连接服务后再试。"
            onRetry={() => query.refetch()}
          />
        </Card>
      ) : (
        <form
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            save.mutate();
          }}
          className="settings-grid"
        >
          <Card>
            <SectionTitle eyebrow="APPEARANCE" title="界面" />
            <div className="settings-group">
              <label className="field">
                <span>主题</span>
                <select
                  value={theme}
                  onChange={(event) => setTheme(event.target.value as Theme)}
                >
                  <option value="system">跟随系统</option>
                  <option value="light">浅色</option>
                  <option value="dark">深色</option>
                </select>
              </label>
              <label className="field">
                <span>信息密度</span>
                <select
                  value={density}
                  onChange={(event) =>
                    setDensity(event.target.value as Density)
                  }
                >
                  <option value="comfortable">舒适</option>
                  <option value="compact">紧凑</option>
                </select>
              </label>
            </div>
          </Card>
          <Card>
            <SectionTitle
              eyebrow="MODEL ROUTING"
              title="模型"
              meta={
                <span className="inline-note">
                  <KeyRound size={13} />
                  密钥仅显示状态
                </span>
              }
            />
            <div className="settings-group two">
              <label className="field">
                <span>默认模型</span>
                <input
                  value={form.default_model}
                  onChange={(event) =>
                    update("default_model", event.target.value)
                  }
                />
              </label>
              <label className="field">
                <span>默认 Provider</span>
                <input
                  value={form.default_provider}
                  onChange={(event) =>
                    update("default_provider", event.target.value)
                  }
                />
              </label>
              <label className="field">
                <span>复杂模型</span>
                <input
                  value={form.complex_model}
                  onChange={(event) =>
                    update("complex_model", event.target.value)
                  }
                />
              </label>
              <label className="field">
                <span>复杂 Provider</span>
                <input
                  value={form.complex_provider}
                  onChange={(event) =>
                    update("complex_provider", event.target.value)
                  }
                />
              </label>
            </div>
            <div className="provider-list">
              {Object.entries(providers).map(([name, state]) => (
                <div key={name}>
                  <Badge value={state.configured ? "succeeded" : "failed"} />
                  <b>{name}</b>
                  <span>
                    {state.configured
                      ? `已通过 ${state.source} 配置`
                      : `请设置 ${name.toUpperCase()}_API_KEY`}
                  </span>
                </div>
              ))}
            </div>
            <div className="settings-actions">
              <Button
                type="button"
                onClick={() => test.mutate("default")}
                disabled={test.isPending}
              >
                <Play size={14} />
                测试默认模型
              </Button>
              <Button
                type="button"
                onClick={() => test.mutate("complex")}
                disabled={test.isPending}
              >
                <Play size={14} />
                测试复杂模型
              </Button>
            </div>
          </Card>
          <Card>
            <SectionTitle
              eyebrow="RUN DEFAULTS"
              title="执行默认值"
              meta={<span>仅影响后续任务</span>}
            />
            <div className="settings-group two">
              <label className="field">
                <span>最大工程轮次</span>
                <input
                  type="number"
                  min="1"
                  value={form.max_rounds}
                  onChange={(event) => update("max_rounds", event.target.value)}
                />
              </label>
              <label className="field">
                <span>每切片修复次数</span>
                <input
                  type="number"
                  min="1"
                  value={form.max_repairs_per_slice}
                  onChange={(event) =>
                    update("max_repairs_per_slice", event.target.value)
                  }
                />
              </label>
              <label className="field">
                <span>成本上限（美元）</span>
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  value={form.max_cost}
                  onChange={(event) => update("max_cost", event.target.value)}
                />
              </label>
              <label className="field">
                <span>测试超时（秒）</span>
                <input
                  type="number"
                  min="1"
                  value={form.test_timeout}
                  onChange={(event) =>
                    update("test_timeout", event.target.value)
                  }
                />
              </label>
              <label className="field">
                <span>部署验证</span>
                <select
                  value={form.deploy_mode}
                  onChange={(event) =>
                    update("deploy_mode", event.target.value)
                  }
                >
                  <option value="verify">验证后停止</option>
                  <option value="local">保留本地服务</option>
                  <option value="none">跳过</option>
                </select>
              </label>
            </div>
          </Card>
          <Card className="settings-summary">
            <MonitorCog size={22} />
            <h2>生效规则</h2>
            <ul>
              <li>
                <CheckCircle2 size={14} />
                当前运行使用不可变配置快照
              </li>
              <li>
                <CheckCircle2 size={14} />
                全局修改只影响后续任务
              </li>
              <li>
                <CheckCircle2 size={14} />
                项目可覆盖模型和执行参数
              </li>
            </ul>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setForm(fromSettings(query.data))}
            >
              <RotateCcw size={14} />
              放弃未保存修改
            </Button>
          </Card>
        </form>
      )}
    </div>
  );
}
