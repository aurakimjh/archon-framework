// 백엔드 데이터를 가져오는 표준 훅 모음.

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type {
  AgentRole,
  AgentRoleConfig,
  AgentRoleConfigSet,
  AgentStatusResponse,
  AuditEvent,
  BudgetStatus,
  BudgetThreshold,
  CostSummary,
  CreateTaskRequest,
  CreateTaskResponse,
  CurrentUser,
  DashboardEvent,
  GateDecisionBody,
  GateQueueItem,
  GateRecord,
  MemorySearchResult,
  ModelEntry,
  NotificationRule,
  PipelineMetrics,
  ProjectSummary,
  TaskRecord,
  TimelineItem,
  TimeseriesPoint,
  UsageQueryParams,
  UsageSummary,
  UserRole,
  UserSummary,
} from "@/types";
import { wsClient, type ConnectionStatus } from "@/lib/ws";

export function useProjects() {
  return useQuery({
    queryKey: ["projects"],
    queryFn: () => api.get<ProjectSummary[]>("/api/projects"),
  });
}

export function useAgents() {
  return useQuery({
    queryKey: ["agents"],
    queryFn: () => api.get<AgentStatusResponse[]>("/api/agents"),
  });
}

export function useCosts() {
  return useQuery({
    queryKey: ["costs"],
    queryFn: () => api.get<CostSummary[]>("/api/cost"),
  });
}

export function useGateQueue() {
  return useQuery({
    queryKey: ["gates"],
    queryFn: () => api.get<GateQueueItem[]>("/api/gates/queue"),
  });
}

export function useMetrics() {
  return useQuery({
    queryKey: ["metrics"],
    queryFn: () => api.get<PipelineMetrics>("/api/metrics"),
  });
}

export function useAgentConfigSet() {
  return useQuery({
    queryKey: ["agent-config"],
    queryFn: () => api.get<AgentRoleConfigSet>("/api/agent-config"),
  });
}

export function useModels() {
  return useQuery({
    queryKey: ["models"],
    queryFn: () => api.get<ModelEntry[]>("/api/models"),
    staleTime: 60_000,
  });
}

export function useUpdateAgentConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { role: AgentRole; body: AgentRoleConfig }) =>
      api.put<AgentRoleConfig>(`/api/agent-config/${input.role}`, input.body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agent-config"] }),
  });
}

export function useApproveGate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { handoffId: string; body?: GateDecisionBody }) =>
      api.post(`/api/gates/${input.handoffId}/approve`, input.body ?? {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["gates"] });
      qc.invalidateQueries({ queryKey: ["gate"] });
    },
  });
}

export function useRejectGate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { handoffId: string; body: GateDecisionBody }) =>
      api.post(`/api/gates/${input.handoffId}/reject`, input.body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["gates"] });
      qc.invalidateQueries({ queryKey: ["gate"] });
    },
  });
}

export function useGate(handoffId: string | null) {
  return useQuery({
    queryKey: ["gate", handoffId],
    queryFn: () => api.get<GateRecord>(`/api/gates/${handoffId}`),
    enabled: !!handoffId,
  });
}

export function useTasks(filter?: {
  active_only?: boolean;
  project_id?: string;
  status?: string;
  limit?: number;
}) {
  const params = new URLSearchParams();
  if (filter?.active_only) params.set("active_only", "true");
  if (filter?.project_id) params.set("project_id", filter.project_id);
  if (filter?.status) params.set("status", filter.status);
  if (filter?.limit) params.set("limit", String(filter.limit));
  const qs = params.toString();
  return useQuery({
    queryKey: ["tasks", filter],
    queryFn: () =>
      api.get<TaskRecord[]>(qs ? `/api/tasks?${qs}` : "/api/tasks"),
    refetchInterval: 5000,
  });
}

export function useTask(taskId: string | null) {
  return useQuery({
    queryKey: ["task", taskId],
    queryFn: () => api.get<TaskRecord>(`/api/tasks/${taskId}`),
    enabled: !!taskId,
    refetchInterval: 3000,
  });
}

export function useCreateTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateTaskRequest) =>
      api.post<CreateTaskResponse>("/api/tasks", {
        scenario: "auto_pass",
        mock: false,
        ...body,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });
}

export function useCancelTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) =>
      api.post<{ status: string; task_id: string }>(
        `/api/tasks/${taskId}/cancel`,
        {},
      ),
    onSuccess: (_data, taskId) => {
      qc.invalidateQueries({ queryKey: ["tasks"] });
      qc.invalidateQueries({ queryKey: ["task", taskId] });
    },
  });
}

export function useUsageSummary() {
  return useQuery({
    queryKey: ["usage-summary"],
    queryFn: () => api.get<UsageSummary>("/api/usage/summary"),
    refetchInterval: 30_000,
  });
}

export function useUsageTimeseries(params: UsageQueryParams = {}) {
  const qs = new URLSearchParams();
  if (params.period) qs.set("period", params.period);
  if (params.start) qs.set("start", params.start);
  if (params.end) qs.set("end", params.end);
  if (params.group_by) qs.set("group_by", params.group_by);
  if (params.project_id) qs.set("project_id", params.project_id);
  const query = qs.toString();
  return useQuery({
    queryKey: ["usage-timeseries", params],
    queryFn: () =>
      api.get<TimeseriesPoint[]>(
        query ? `/api/usage/timeseries?${query}` : "/api/usage/timeseries",
      ),
    refetchInterval: 60_000,
  });
}

export function useBudgets() {
  return useQuery({
    queryKey: ["budgets"],
    queryFn: () => api.get<BudgetThreshold[]>("/api/budgets"),
  });
}

export function useBudgetStatus() {
  return useQuery({
    queryKey: ["budgets", "status"],
    queryFn: () => api.get<BudgetStatus[]>("/api/budgets/status"),
    refetchInterval: 30_000,
  });
}

export function useUpsertBudget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Omit<BudgetThreshold, "id" | "created_at" | "updated_at">) =>
      api.put<BudgetThreshold>("/api/budgets", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["budgets"] });
    },
  });
}

export function useDeleteBudget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.del(`/api/budgets/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["budgets"] });
    },
  });
}

export function useSeedUsage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input?: { days?: number; events_per_day?: number }) => {
      const qs = new URLSearchParams();
      if (input?.days) qs.set("days", String(input.days));
      if (input?.events_per_day)
        qs.set("events_per_day", String(input.events_per_day));
      const path = `/api/usage/seed${qs.toString() ? "?" + qs.toString() : ""}`;
      return api.post<{ status: string; events: number }>(path);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["usage-summary"] });
      qc.invalidateQueries({ queryKey: ["usage-timeseries"] });
    },
  });
}

// --- Slice 5: 사용자 / 감사 로그 ---

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<CurrentUser>("/api/me"),
    staleTime: 60_000,
    retry: false,
  });
}

export function useUsers() {
  return useQuery({
    queryKey: ["users"],
    queryFn: () => api.get<UserSummary[]>("/api/users"),
    retry: (n, e: unknown) =>
      typeof e === "object" &&
      e !== null &&
      "status" in e &&
      (e as { status?: number }).status === 403
        ? false
        : n < 1,
  });
}

export function useUpsertUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { user_id: string; name?: string; role: UserRole }) =>
      api.put<{ user_id: string; name: string; role: UserRole }>(
        "/api/users",
        input,
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (user_id: string) => api.del(`/api/users/${user_id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useIssueToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { user_id: string; label?: string }) =>
      api.post<{ token: string; label: string }>(
        `/api/users/${input.user_id}/tokens`,
        { label: input.label ?? "" },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useRevokeToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { user_id: string; token_id: string }) =>
      api.del(`/api/users/${input.user_id}/tokens/${input.token_id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useAudit(filter?: {
  user_id?: string;
  action?: string;
  q?: string;
  limit?: number;
}) {
  const qs = new URLSearchParams();
  if (filter?.user_id) qs.set("user_id", filter.user_id);
  if (filter?.action) qs.set("action", filter.action);
  if (filter?.q) qs.set("q", filter.q);
  if (filter?.limit) qs.set("limit", String(filter.limit));
  const q = qs.toString();
  return useQuery({
    queryKey: ["audit", filter],
    queryFn: () => api.get<AuditEvent[]>(q ? `/api/audit?${q}` : "/api/audit"),
    retry: false,
  });
}

// --- Slice 6: project detail ---

export function useProjectTimeline(projectId: string | null, limit = 50) {
  return useQuery({
    queryKey: ["project-timeline", projectId, limit],
    queryFn: () =>
      api.get<TimelineItem[]>(
        `/api/projects/${projectId}/timeline?limit=${limit}`,
      ),
    enabled: !!projectId,
    refetchInterval: 10_000,
  });
}

export function useProjectMemory(projectId: string | null, q: string | null) {
  return useQuery({
    queryKey: ["project-memory", projectId, q],
    queryFn: () =>
      api.get<MemorySearchResult>(
        `/api/projects/${projectId}/memory?q=${encodeURIComponent(q ?? "")}`,
      ),
    enabled: !!projectId && !!q && q.length > 0,
  });
}

// --- Slice 7: notification rules ---

export function useNotificationRules() {
  return useQuery({
    queryKey: ["notification-rules"],
    queryFn: () => api.get<NotificationRule[]>("/api/notification-rules"),
    retry: false,
  });
}

export function useUpsertNotificationRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (rule: Omit<NotificationRule, "created_at" | "updated_at">) =>
      api.put<NotificationRule>("/api/notification-rules", rule),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["notification-rules"] }),
  });
}

export function useDeleteNotificationRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.del(`/api/notification-rules/${id}`),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["notification-rules"] }),
  });
}

export function useTestNotification() {
  return useMutation({
    mutationFn: (rule_id: number) =>
      api.post<{ status: string }>("/api/notifications/test", { rule_id }),
  });
}

export function useEnvInfo() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () =>
      api.get<{
        status: string;
        version: string;
        env: string;
        auth_required: boolean;
      }>("/api/health"),
    staleTime: 30_000,
  });
}

export function useWebSocketStatus(): ConnectionStatus {
  const [status, setStatus] = useState<ConnectionStatus>(wsClient.getStatus());
  useEffect(() => wsClient.onStatus(setStatus), []);
  return status;
}

const MAX_EVENT_LOG = 200;

export function useEventLog() {
  const [events, setEvents] = useState<DashboardEvent[]>([]);
  const qc = useQueryClient();

  useEffect(() => {
    return wsClient.on((evt) => {
      setEvents((prev) => [evt, ...prev].slice(0, MAX_EVENT_LOG));
      // 데이터 변경 이벤트는 관련 쿼리를 무효화한다.
      if (evt.event_type === "gate_approved" || evt.event_type === "gate_rejected") {
        qc.invalidateQueries({ queryKey: ["gates"] });
      }
      if (evt.event_type === "project_updated") {
        qc.invalidateQueries({ queryKey: ["projects"] });
      }
    });
  }, [qc]);

  return events;
}
