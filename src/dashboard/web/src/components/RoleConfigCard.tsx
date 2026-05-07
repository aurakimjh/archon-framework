import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, RotateCcw, Save } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import { useUpdateAgentConfig } from "@/lib/hooks";
import { cn } from "@/lib/cn";
import type {
  AgentRole,
  AgentRoleConfig,
  ModelEntry,
  MultiProviderMode,
} from "@/types";

const PROVIDER_MODES: { value: MultiProviderMode; label: string; hint: string }[] =
  [
    { value: "single", label: "Single", hint: "단일 모델만 사용" },
    {
      value: "shadow",
      label: "Shadow",
      hint: "primary 사용, 다른 모델은 비차단 비교",
    },
    { value: "consensus", label: "Consensus", hint: "다수결 합의" },
    { value: "strict", label: "Strict", hint: "불일치 시 L2_HUMAN 상향" },
  ];

interface Props {
  config: AgentRoleConfig;
  models: ModelEntry[];
}

export function RoleConfigCard({ config, models }: Props) {
  const [draft, setDraft] = useState<AgentRoleConfig>(config);
  const baselineRef = useRef(config);
  const update = useUpdateAgentConfig();

  // 서버 baseline이 갱신되면 dirty가 아닐 때만 폼을 동기화한다.
  useEffect(() => {
    const isClean =
      JSON.stringify(draft) === JSON.stringify(baselineRef.current);
    baselineRef.current = config;
    if (isClean) setDraft(config);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(config);

  function patch(p: Partial<AgentRoleConfig>) {
    setDraft((d) => ({ ...d, ...p }));
  }

  function reset() {
    setDraft(config);
  }

  function save() {
    update.mutate(
      { role: draft.role, body: draft },
      {
        onSuccess: () => toast.success(`${draft.role} saved`),
        onError: (err: unknown) => {
          const msg =
            err instanceof ApiError ? err.message : "Save failed";
          toast.error(msg);
        },
      },
    );
  }

  const modelOptions = useMemo(() => {
    const ensure = models.some((m) => m.model_name === draft.model)
      ? models
      : [...models, { model_name: draft.model, provider: null, underlying_model: null }];
    return ensure;
  }, [models, draft.model]);

  const selectedDetail = modelOptions.find((m) => m.model_name === draft.model);

  return (
    <Card
      className={cn(
        "transition-all",
        dirty && "ring-1 ring-warning/50",
        !draft.enabled && "opacity-70",
      )}
    >
      <CardHeader className="flex flex-row items-center justify-between space-y-0 border-b border-border pb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-secondary text-muted-foreground">
            <Bot className="h-4 w-4" aria-hidden />
          </div>
          <div>
            <div className="text-sm font-semibold capitalize">{draft.role}</div>
            <div className="text-[11px] text-muted-foreground">
              {ROLE_HINT[draft.role] ?? "agent"}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {dirty && <Badge variant="warning">unsaved</Badge>}
          <Switch
            checked={draft.enabled}
            onChange={(e) => patch({ enabled: e.currentTarget.checked })}
            aria-label={`${draft.role} enabled`}
          />
        </div>
      </CardHeader>

      <CardContent className="space-y-4 pt-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Model">
            <Select
              value={draft.model}
              onChange={(e) => patch({ model: e.currentTarget.value })}
              disabled={!draft.enabled}
            >
              {modelOptions.map((m) => (
                <option key={m.model_name} value={m.model_name}>
                  {m.model_name}
                  {m.underlying_model ? ` — ${m.underlying_model}` : ""}
                </option>
              ))}
            </Select>
            {selectedDetail?.provider && (
              <p className="mt-1 text-[11px] text-muted-foreground">
                provider: {selectedDetail.provider}
              </p>
            )}
          </Field>

          <Field label="Multi-provider mode">
            <Select
              value={draft.multi_provider_mode}
              onChange={(e) =>
                patch({
                  multi_provider_mode: e.currentTarget.value as MultiProviderMode,
                })
              }
              disabled={!draft.enabled}
            >
              {PROVIDER_MODES.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </Select>
            <p className="mt-1 text-[11px] text-muted-foreground">
              {
                PROVIDER_MODES.find((m) => m.value === draft.multi_provider_mode)
                  ?.hint
              }
            </p>
          </Field>

          <Field label="Max tokens">
            <Input
              type="number"
              min={128}
              max={200_000}
              value={draft.max_tokens}
              onChange={(e) =>
                patch({ max_tokens: Number(e.currentTarget.value) || 0 })
              }
              disabled={!draft.enabled}
            />
          </Field>

          <Field label="Temperature">
            <Input
              type="number"
              min={0}
              max={2}
              step={0.05}
              value={draft.temperature}
              onChange={(e) =>
                patch({ temperature: Number(e.currentTarget.value) || 0 })
              }
              disabled={!draft.enabled}
            />
          </Field>
        </div>

        <Field label="System prompt override (optional)">
          <Textarea
            value={draft.system_prompt_override ?? ""}
            onChange={(e) =>
              patch({
                system_prompt_override:
                  e.currentTarget.value.trim() === ""
                    ? null
                    : e.currentTarget.value,
              })
            }
            placeholder="비워두면 에이전트의 기본 시스템 프롬프트를 사용합니다."
            disabled={!draft.enabled}
            rows={4}
          />
        </Field>

        <div className="flex items-center justify-end gap-2 pt-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={reset}
            disabled={!dirty || update.isPending}
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Reset
          </Button>
          <Button
            size="sm"
            onClick={save}
            disabled={!dirty}
            loading={update.isPending}
          >
            <Save className="h-3.5 w-3.5" />
            Save
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

const ROLE_HINT: Partial<Record<AgentRole, string>> = {
  orchestrator: "워크플로우 조정 / 핸드오프",
  reviewer: "리뷰·품질 게이트",
  backend: "API · DB · 비즈니스 로직",
  frontend: "UI · 상호작용",
  tester: "테스트 작성 · 커버리지",
  devops: "CI · 배포 · 인프라",
  docs: "문서 · 변경 로그",
};

