import { useMemo, useState, type FormEvent } from "react";
import {
  Activity,
  AlertTriangle,
  Ban,
  ClipboardList,
  PlayCircle,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/EmptyState";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { TaskStatusBadge } from "@/components/TaskStatusBadge";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import {
  useCancelTask,
  useCreateTask,
  useEnvInfo,
  useTasks,
} from "@/lib/hooks";
import { cn } from "@/lib/cn";
import type { AgentRole, CreateTaskRequest, TaskRecord } from "@/types";

const ROLES: AgentRole[] = [
  "backend",
  "frontend",
  "tester",
  "devops",
  "docs",
  "reviewer",
  "orchestrator",
];

const SCENARIOS = [
  { value: "auto_pass", label: "Auto Pass (clean)" },
  { value: "l1", label: "L1 Rework" },
  { value: "l2", label: "L2 Human" },
  { value: "l1_exhausted", label: "L1 Exhausted" },
] as const;

type Tab = "active" | "all";

export function InstructionsPage() {
  const env = useEnvInfo();
  const isDev = env.data?.env === "development";

  const [tab, setTab] = useState<Tab>("active");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const tasks = useTasks(
    tab === "active" ? { active_only: true, limit: 50 } : { limit: 50 },
  );

  const selectedTask = useMemo(
    () => (tasks.data ?? []).find((t) => t.id === selectedId) ?? null,
    [tasks.data, selectedId],
  );

  return (
    <div className="space-y-5">
      <NewInstructionCard isDev={isDev} />

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 border-b border-border pb-4">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Activity className="h-4 w-4 text-muted-foreground" />
            Tasks
          </CardTitle>
          <div className="flex rounded-md border border-border bg-card text-xs">
            <TabButton active={tab === "active"} onClick={() => setTab("active")}>
              Active
            </TabButton>
            <TabButton active={tab === "all"} onClick={() => setTab("all")}>
              All
            </TabButton>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <TaskList
            loading={tasks.isLoading}
            error={tasks.isError}
            data={tasks.data ?? []}
            selectedId={selectedId}
            onSelect={(id) => setSelectedId((cur) => (cur === id ? null : id))}
          />
        </CardContent>
      </Card>

      {selectedTask && (
        <TaskDetail
          task={selectedTask}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 신규 작업지시서
// ---------------------------------------------------------------------------

function NewInstructionCard({ isDev }: { isDev: boolean }) {
  const create = useCreateTask();
  const [form, setForm] = useState<CreateTaskRequest>({
    project_id: "",
    instructions: "",
    agent_role: "backend",
    scenario: "auto_pass",
    mock: false,
  });

  function patch(p: Partial<CreateTaskRequest>) {
    setForm((f) => ({ ...f, ...p }));
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!form.project_id.trim() || !form.instructions.trim()) return;
    create.mutate(form, {
      onSuccess: (res) => {
        toast.success(`Task ${res.task_id.slice(-8)} started`);
        patch({ instructions: "" });
      },
      onError: (err: unknown) => {
        const msg = err instanceof ApiError ? err.message : "Failed";
        toast.error(msg);
      },
    });
  }

  return (
    <Card>
      <CardHeader className="border-b border-border pb-4">
        <CardTitle className="flex items-center gap-2 text-sm">
          <ClipboardList className="h-4 w-4 text-muted-foreground" />
          New work instruction
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 pt-5">
        <form className="space-y-4" onSubmit={submit}>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Project ID">
              <Input
                value={form.project_id}
                onChange={(e) => patch({ project_id: e.currentTarget.value })}
                placeholder="my-project"
                required
              />
            </Field>
            <Field label="Agent role">
              <Select
                value={form.agent_role}
                onChange={(e) =>
                  patch({ agent_role: e.currentTarget.value as AgentRole })
                }
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </Select>
            </Field>
            {isDev && (
              <Field label="Scenario (dev)">
                <Select
                  value={form.scenario}
                  onChange={(e) => patch({ scenario: e.currentTarget.value })}
                >
                  {SCENARIOS.map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.label}
                    </option>
                  ))}
                </Select>
              </Field>
            )}
          </div>

          <Field label="Instructions">
            <Textarea
              value={form.instructions}
              onChange={(e) => patch({ instructions: e.currentTarget.value })}
              placeholder="에이전트에게 전달할 작업 내용을 명확하게 작성하세요…"
              rows={5}
              required
            />
          </Field>

          <div className="flex items-center justify-between gap-4">
            {isDev && (
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                <Switch
                  checked={!!form.mock}
                  onChange={(e) =>
                    patch({ mock: e.currentTarget.checked })
                  }
                />
                Mock pipeline (dev only)
              </label>
            )}
            <Button
              type="submit"
              loading={create.isPending}
              disabled={
                !form.project_id.trim() || !form.instructions.trim()
              }
              className="ml-auto"
            >
              <PlayCircle className="h-4 w-4" />
              Submit
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// 리스트 / 상세
// ---------------------------------------------------------------------------

interface ListProps {
  loading: boolean;
  error: boolean;
  data: TaskRecord[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

function TaskList({ loading, error, data, selectedId, onSelect }: ListProps) {
  if (loading) {
    return (
      <div className="space-y-2 p-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-9" />
        ))}
      </div>
    );
  }
  if (error) {
    return (
      <EmptyState
        icon={AlertTriangle}
        title="Error"
        description="작업 목록을 불러오지 못했습니다."
      />
    );
  }
  if (data.length === 0) {
    return (
      <EmptyState
        icon={ClipboardList}
        title="No tasks yet"
        description="위 폼으로 첫 작업지시서를 등록하세요."
      />
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Task</TableHead>
          <TableHead>Project</TableHead>
          <TableHead>Role</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Created</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.map((t) => (
          <TableRow
            key={t.id}
            onClick={() => onSelect(t.id)}
            className={cn(
              "cursor-pointer",
              selectedId === t.id && "bg-secondary",
            )}
          >
            <TableCell className="font-mono text-xs">
              {t.id.slice(-12)}
            </TableCell>
            <TableCell>{t.project_id}</TableCell>
            <TableCell className="capitalize">{t.agent_role}</TableCell>
            <TableCell>
              <TaskStatusBadge status={t.status} />
            </TableCell>
            <TableCell className="text-right text-xs text-muted-foreground tabular-nums">
              {formatRelative(t.created_at)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function TaskDetail({
  task,
  onClose,
}: {
  task: TaskRecord;
  onClose: () => void;
}) {
  const cancel = useCancelTask();
  const isActive = task.status === "pending" || task.status === "running";

  function onCancel() {
    if (!confirm(`Task ${task.id.slice(-8)}을(를) 취소하시겠습니까?`)) return;
    cancel.mutate(task.id, {
      onSuccess: () => {
        toast.success("Cancelled");
        onClose();
      },
      onError: () => toast.error("Cancel failed"),
    });
  }

  const duration = useMemo(() => {
    if (!task.started_at) return null;
    const end = task.completed_at
      ? new Date(task.completed_at).getTime()
      : Date.now();
    return Math.round((end - new Date(task.started_at).getTime()) / 1000);
  }, [task.started_at, task.completed_at]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between space-y-0 border-b border-border pb-4">
        <div>
          <CardTitle className="font-mono text-xs">{task.id}</CardTitle>
          <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
            <TaskStatusBadge status={task.status} />
            <span className="capitalize">· {task.agent_role}</span>
            <span>· {task.project_id}</span>
            {duration !== null && <span>· {duration}s</span>}
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
      </CardHeader>
      <CardContent className="space-y-4 pt-5">
        <div>
          <Label>Instructions</Label>
          <pre className="mt-1.5 max-h-60 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-background/50 p-3 text-xs text-foreground/90 scrollbar-thin">
            {task.instructions}
          </pre>
        </div>

        {task.gate_decision && (
          <div className="grid gap-1">
            <Label>Gate decision</Label>
            <div className="text-sm">
              {task.gate_decision}
              {typeof task.review_score === "number" && (
                <span className="ml-2 text-xs text-muted-foreground">
                  score {task.review_score}
                </span>
              )}
            </div>
          </div>
        )}

        {task.error && (
          <div>
            <Label>Error</Label>
            <pre className="mt-1.5 max-h-40 overflow-auto whitespace-pre-wrap rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive scrollbar-thin">
              {task.error}
            </pre>
          </div>
        )}

        <div className="flex items-center justify-end gap-2 pt-1">
          {isActive && (
            <Button
              variant="destructive"
              size="sm"
              loading={cancel.isPending}
              onClick={onCancel}
            >
              <Ban className="h-3.5 w-3.5" />
              Cancel task
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

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

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "px-3 py-1 transition-colors",
        active
          ? "bg-primary/15 text-primary"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function formatRelative(iso: string): string {
  const dt = new Date(iso).getTime();
  const sec = Math.round((Date.now() - dt) / 1000);
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}
