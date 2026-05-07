// 백엔드 src/dashboard/models.py와 동기화된 타입 정의.

export type AgentRole =
  | "orchestrator"
  | "reviewer"
  | "frontend"
  | "backend"
  | "tester"
  | "devops"
  | "docs";

export type HealthStatus = "healthy" | "degraded" | "unhealthy" | "unknown";

export type GateLevel =
  | "AUTO_PASS"
  | "L1_REWORK"
  | "L2_HUMAN"
  | "L3_HALT"
  | "L4_DEPLOY";

export type MultiProviderMode = "single" | "shadow" | "consensus" | "strict";

export interface AgentRoleConfig {
  role: AgentRole;
  enabled: boolean;
  model: string;
  fallback_models: string[];
  multi_provider_mode: MultiProviderMode;
  system_prompt_override: string | null;
  max_tokens: number;
  temperature: number;
}

export interface AgentRoleConfigSet {
  schema_version: string;
  configs: Partial<Record<AgentRole, AgentRoleConfig>>;
}

export interface ModelEntry {
  model_name: string;
  provider: string | null;
  underlying_model: string | null;
}

export type TaskStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface TaskRecord {
  id: string;
  project_id: string;
  agent_role: string;
  instructions: string;
  status: TaskStatus;
  handoff_id: string | null;
  gate_decision: string | null;
  review_score: number | null;
  error: string | null;
  result_summary: string | null;
  cancelled_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string;
}

export type GateStatus = "pending" | "approved" | "rejected";

export interface GateRecord {
  handoff_id: string;
  project_id: string;
  gate_level: GateLevel | string;
  trigger_reason: string;
  agent_role: string;
  review_score: number | null;
  payload: Record<string, unknown>;
  status: GateStatus;
  decision_comment: string | null;
  decided_by: string | null;
  created_at: string;
  decided_at: string | null;
}

export interface CreateTaskRequest {
  project_id: string;
  instructions: string;
  agent_role: AgentRole | string;
  scenario?: string;
  mock?: boolean;
}

export interface CreateTaskResponse {
  status: string;
  task_id: string;
  project_id: string;
  handoff_id: string;
}

export interface GateDecisionBody {
  comment?: string | null;
  reviewer?: string | null;
}

export interface TimeseriesPoint {
  bucket: string;
  group: string | null;
  cost_usd: number;
  tokens_in: number;
  tokens_out: number;
  events: number;
}

export interface UsageSummary {
  today_cost_usd: number;
  today_tokens: number;
  month_cost_usd: number;
  month_tokens: number;
  last_24h_events: number;
  by_role_today: Record<string, number>;
  by_project_today: Record<string, number>;
}

export type BudgetPeriod = "daily" | "monthly";

export interface BudgetThreshold {
  id: number | null;
  scope: string;
  period: BudgetPeriod;
  limit_usd: number;
  notify_email: string | null;
  notify_webhook: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface BudgetStatus {
  threshold: BudgetThreshold;
  used_usd: number;
  usage_ratio: number;
  exceeded: boolean;
}

export type GroupBy = "none" | "project" | "role" | "model";

export interface UsageQueryParams {
  period?: "daily" | "hourly";
  start?: string;
  end?: string;
  group_by?: GroupBy;
  project_id?: string;
}

export interface ProjectSummary {
  project_id: string;
  project_name: string;
  status: string;
  priority: number;
  pending_tasks: number;
  completed_tasks: number;
  active_agents: number;
}

export interface AgentStatusResponse {
  role: string;
  health_status: HealthStatus | string;
  consecutive_failures: number;
  avg_latency_ms: number;
  total_executions: number;
  model: string;
}

export interface CostSummary {
  project_id: string;
  date: string;
  daily_tokens_used: number;
  daily_token_limit: number;
  total_cost_usd: number;
  agent_breakdown: Record<string, number>;
  usage_ratio: number;
}

export interface GateQueueItem {
  handoff_id: string;
  project_id: string;
  gate_level: GateLevel | string;
  trigger_reason: string;
  created_at: string;
  agent_role: string;
  review_score: number | null;
}

export interface DashboardEvent {
  event_type: string;
  payload: Record<string, unknown>;
  timestamp: string;
}

export interface PipelineMetrics {
  total_executions?: number;
  success_rate?: number;
  avg_latency_ms?: number;
  [key: string]: unknown;
}
