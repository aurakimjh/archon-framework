import { useMemo } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/EmptyState";
import { RoleConfigCard } from "@/components/RoleConfigCard";
import { Skeleton } from "@/components/ui/skeleton";
import { useAgentConfigSet, useModels } from "@/lib/hooks";
import type { AgentRole, AgentRoleConfig } from "@/types";

const ROLE_ORDER: AgentRole[] = [
  "orchestrator",
  "reviewer",
  "backend",
  "frontend",
  "tester",
  "devops",
  "docs",
];

export function AgentsPage() {
  const cfgQuery = useAgentConfigSet();
  const modelsQuery = useModels();

  const orderedConfigs = useMemo(() => {
    const set = cfgQuery.data?.configs ?? {};
    return ROLE_ORDER.map((role) => set[role]).filter(
      (c): c is AgentRoleConfig => Boolean(c),
    );
  }, [cfgQuery.data]);

  if (cfgQuery.isLoading || modelsQuery.isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-72" />
        ))}
      </div>
    );
  }

  if (cfgQuery.isError) {
    return (
      <Card>
        <CardContent>
          <EmptyState
            icon={AlertTriangle}
            title="Failed to load agent config"
            description="API 연결 또는 권한을 확인하세요."
            action={
              <Button
                variant="outline"
                size="sm"
                onClick={() => cfgQuery.refetch()}
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Retry
              </Button>
            }
          />
        </CardContent>
      </Card>
    );
  }

  const models = modelsQuery.data ?? [];
  const noModels = models.length === 0;

  return (
    <div className="space-y-5">
      <div className="rounded-md border border-border bg-card/40 px-4 py-3 text-sm">
        <p className="text-muted-foreground">
          역할별 에이전트의 모델·활성 여부·다중 프로바이더 모드·시스템 프롬프트
          오버라이드를 조정합니다. 변경사항은 카드 단위로 저장되며 즉시 반영됩니다.
        </p>
        {noModels && (
          <p className="mt-2 flex items-center gap-2 text-xs text-warning">
            <AlertTriangle className="h-3.5 w-3.5" />
            litellm 모델 레지스트리가 비어 있습니다. config/litellm_config.yaml
            설정을 확인하세요.
          </p>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {orderedConfigs.map((cfg) => (
          <RoleConfigCard key={cfg.role} config={cfg} models={models} />
        ))}
      </div>
    </div>
  );
}
