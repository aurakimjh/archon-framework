import { useMemo } from "react";
import {
  Activity,
  Banknote,
  Bot,
  CircleAlert,
  FolderKanban,
  ShieldCheck,
} from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/EmptyState";
import { StatCard } from "@/components/StatCard";
import { StatusDot } from "@/components/StatusDot";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useAgents,
  useCosts,
  useEventLog,
  useGateQueue,
  useMetrics,
  useProjects,
} from "@/lib/hooks";
import { LiveEventLog } from "@/components/LiveEventLog";
import { GateQueueTable } from "@/components/GateQueueTable";
import type { AgentStatusResponse, ProjectSummary } from "@/types";

export function OverviewPage() {
  const projects = useProjects();
  const agents = useAgents();
  const costs = useCosts();
  const gates = useGateQueue();
  const metrics = useMetrics();
  const events = useEventLog();

  const totalCost = useMemo(
    () => (costs.data ?? []).reduce((s, c) => s + (c.total_cost_usd ?? 0), 0),
    [costs.data],
  );
  const successRate = metrics.data?.success_rate;
  const totalExecs = metrics.data?.total_executions ?? 0;

  return (
    <div className="space-y-6">
      {/* --- Stat row --- */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <StatCard
          icon={FolderKanban}
          label="Projects"
          value={projects.data?.length ?? 0}
          loading={projects.isLoading}
        />
        <StatCard
          icon={Bot}
          label="Active Agents"
          value={agents.data?.length ?? 0}
          loading={agents.isLoading}
        />
        <StatCard
          icon={Banknote}
          label="Today's Cost"
          value={`$${totalCost.toFixed(2)}`}
          loading={costs.isLoading}
        />
        <StatCard
          icon={ShieldCheck}
          label="Gate Queue"
          value={gates.data?.length ?? 0}
          tone={gates.data && gates.data.length > 0 ? "warning" : "default"}
          loading={gates.isLoading}
        />
        <StatCard
          icon={Activity}
          label="Success Rate"
          value={
            totalExecs > 0 && successRate !== undefined
              ? `${Math.round(successRate * 100)}%`
              : "—"
          }
          hint={
            totalExecs > 0 ? `${totalExecs} runs` : "no runs yet"
          }
          loading={metrics.isLoading}
        />
      </div>

      {/* --- Tables row --- */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <FolderKanban className="h-4 w-4 text-muted-foreground" />
              Projects
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ProjectsTable
              loading={projects.isLoading}
              error={projects.isError}
              data={projects.data ?? []}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <Bot className="h-4 w-4 text-muted-foreground" />
              Agent Health
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <AgentsTable
              loading={agents.isLoading}
              error={agents.isError}
              data={agents.data ?? []}
            />
          </CardContent>
        </Card>
      </div>

      {/* --- Gates --- */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <ShieldCheck className="h-4 w-4 text-muted-foreground" />
            Human Gate Queue
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <GateQueueTable
            loading={gates.isLoading}
            error={gates.isError}
            data={gates.data ?? []}
          />
        </CardContent>
      </Card>

      {/* --- Events --- */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <Activity className="h-4 w-4 text-muted-foreground" />
            Live Events
          </CardTitle>
        </CardHeader>
        <CardContent>
          <LiveEventLog events={events} />
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 내부 컴포넌트
// ---------------------------------------------------------------------------

interface ProjectsTableProps {
  loading: boolean;
  error: boolean;
  data: ProjectSummary[];
}

function ProjectsTable({ loading, error, data }: ProjectsTableProps) {
  if (loading) return <TableLoading rows={3} cols={4} />;
  if (error) return <TableError message="프로젝트 목록을 불러오지 못했습니다." />;
  if (data.length === 0) {
    return (
      <EmptyState
        icon={FolderKanban}
        title="No projects yet"
        description="프로젝트가 등록되면 여기에 표시됩니다."
      />
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>ID</TableHead>
          <TableHead>Name</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Priority</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.map((p) => (
          <TableRow key={p.project_id}>
            <TableCell className="font-mono text-xs">{p.project_id}</TableCell>
            <TableCell>{p.project_name || "—"}</TableCell>
            <TableCell>
              <span className="text-xs capitalize text-muted-foreground">
                {p.status}
              </span>
            </TableCell>
            <TableCell className="text-right tabular-nums">{p.priority}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

interface AgentsTableProps {
  loading: boolean;
  error: boolean;
  data: AgentStatusResponse[];
}

function AgentsTable({ loading, error, data }: AgentsTableProps) {
  if (loading) return <TableLoading rows={3} cols={4} />;
  if (error) return <TableError message="에이전트 상태를 불러오지 못했습니다." />;
  if (data.length === 0) {
    return (
      <EmptyState
        icon={Bot}
        title="No agents registered"
        description="에이전트가 활성화되면 헬스 상태가 표시됩니다."
      />
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Role</TableHead>
          <TableHead>Health</TableHead>
          <TableHead className="text-right">Failures</TableHead>
          <TableHead className="text-right">Latency</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.map((a) => (
          <TableRow key={a.role}>
            <TableCell className="capitalize">
              <div className="flex items-center gap-2">
                <StatusDot status={a.health_status} pulse />
                {a.role}
              </div>
            </TableCell>
            <TableCell>
              <span className="text-xs capitalize text-muted-foreground">
                {a.health_status}
              </span>
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {a.consecutive_failures}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {a.avg_latency_ms.toFixed(0)} ms
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function TableLoading({ rows, cols }: { rows: number; cols: number }) {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex gap-3">
          {Array.from({ length: cols }).map((_, c) => (
            <Skeleton key={c} className="h-5 flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}

function TableError({ message }: { message: string }) {
  return (
    <EmptyState
      icon={CircleAlert}
      title="Error"
      description={message}
    />
  );
}
