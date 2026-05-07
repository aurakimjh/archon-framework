import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Banknote,
  CalendarRange,
  Coins,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/EmptyState";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { StatCard } from "@/components/StatCard";
import { TimeseriesAreaChart } from "@/components/charts/TimeseriesAreaChart";
import { ApiError } from "@/lib/api";
import {
  useBudgetStatus,
  useDeleteBudget,
  useEnvInfo,
  useSeedUsage,
  useUpsertBudget,
  useUsageSummary,
  useUsageTimeseries,
} from "@/lib/hooks";
import { cn } from "@/lib/cn";
import type { BudgetPeriod, BudgetStatus, GroupBy } from "@/types";

type Range = "7d" | "30d" | "90d";

export function CostPage() {
  const env = useEnvInfo();
  const isDev = env.data?.env === "development";

  const summary = useUsageSummary();
  const budgets = useBudgetStatus();

  const [range, setRange] = useState<Range>("30d");
  const [groupBy, setGroupBy] = useState<GroupBy>("role");

  const start = useMemo(() => isoStartOfRange(range), [range]);
  const ts = useUsageTimeseries({
    period: "daily",
    start,
    group_by: groupBy,
  });

  return (
    <div className="space-y-5">
      <Header
        isDev={isDev}
        onSeed={() => {
          // 시드 후 자동으로 invalidate
        }}
      />

      <StatRow loading={summary.isLoading} data={summary.data} />

      <BudgetSection statuses={budgets.data ?? []} loading={budgets.isLoading} />

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 border-b border-border pb-4">
          <CardTitle className="flex items-center gap-2 text-sm">
            <CalendarRange className="h-4 w-4 text-muted-foreground" />
            Daily cost
          </CardTitle>
          <div className="flex items-center gap-2">
            <Select
              value={groupBy}
              onChange={(e) => setGroupBy(e.currentTarget.value as GroupBy)}
              className="h-8 w-32 text-xs"
            >
              <option value="none">no grouping</option>
              <option value="role">by role</option>
              <option value="project">by project</option>
              <option value="model">by model</option>
            </Select>
            <div className="flex rounded-md border border-border bg-card text-xs">
              {(["7d", "30d", "90d"] as Range[]).map((r) => (
                <button
                  key={r}
                  onClick={() => setRange(r)}
                  className={cn(
                    "px-3 py-1 transition-colors",
                    range === r
                      ? "bg-primary/15 text-primary"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent className="pt-5">
          {ts.isLoading ? (
            <Skeleton className="h-72 w-full" />
          ) : ts.isError ? (
            <EmptyState
              icon={AlertTriangle}
              title="Error"
              description="시계열 데이터를 불러오지 못했습니다."
            />
          ) : (ts.data ?? []).length === 0 ? (
            <EmptyState
              icon={Coins}
              title="No usage yet"
              description={
                isDev
                  ? "상단 'Seed sample data' 로 데모 데이터를 채워보세요."
                  : "에이전트 호출이 시작되면 시계열이 표시됩니다."
              }
            />
          ) : (
            <TimeseriesAreaChart data={ts.data ?? []} field="cost_usd" />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Header (with dev seeder)
// ---------------------------------------------------------------------------

function Header({ isDev, onSeed }: { isDev: boolean; onSeed: () => void }) {
  const seed = useSeedUsage();
  return (
    <div className="flex items-center justify-between rounded-md border border-border bg-card/40 px-4 py-3 text-sm">
      <p className="text-muted-foreground">
        에이전트별·프로젝트별 LLM 비용·토큰 사용량을 시계열로 추적합니다.
      </p>
      <div className="flex items-center gap-2">
        {isDev && (
          <Button
            variant="outline"
            size="sm"
            loading={seed.isPending}
            onClick={() =>
              seed.mutate(
                { days: 14, events_per_day: 24 },
                {
                  onSuccess: (r) => {
                    toast.success(`Seeded ${r.events} events`);
                    onSeed();
                  },
                  onError: () => toast.error("Seed failed"),
                },
              )
            }
          >
            <Sparkles className="h-3.5 w-3.5" />
            Seed sample data
          </Button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stat row
// ---------------------------------------------------------------------------

function StatRow({
  loading,
  data,
}: {
  loading: boolean;
  data: { today_cost_usd: number; month_cost_usd: number; today_tokens: number; last_24h_events: number; month_tokens: number } | undefined;
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <StatCard
        icon={Banknote}
        label="Today"
        value={`$${(data?.today_cost_usd ?? 0).toFixed(2)}`}
        hint={`${formatTokens(data?.today_tokens ?? 0)} tokens`}
        loading={loading}
      />
      <StatCard
        icon={Banknote}
        label="This month"
        value={`$${(data?.month_cost_usd ?? 0).toFixed(2)}`}
        hint={`${formatTokens(data?.month_tokens ?? 0)} tokens`}
        loading={loading}
      />
      <StatCard
        icon={Coins}
        label="Today's tokens"
        value={formatTokens(data?.today_tokens ?? 0)}
        loading={loading}
      />
      <StatCard
        icon={RefreshCw}
        label="Last 24h events"
        value={data?.last_24h_events ?? 0}
        loading={loading}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Budgets
// ---------------------------------------------------------------------------

function BudgetSection({
  statuses,
  loading,
}: {
  statuses: BudgetStatus[];
  loading: boolean;
}) {
  return (
    <Card>
      <CardHeader className="border-b border-border pb-4">
        <CardTitle className="flex items-center gap-2 text-sm">
          <AlertTriangle className="h-4 w-4 text-muted-foreground" />
          Budget thresholds
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 pt-5">
        {loading ? (
          <Skeleton className="h-16 w-full" />
        ) : statuses.length === 0 ? (
          <EmptyState
            title="No budgets configured"
            description="아래에서 첫 임계치를 추가하세요."
          />
        ) : (
          <div className="space-y-3">
            {statuses.map((s) => (
              <BudgetRow key={s.threshold.id} status={s} />
            ))}
          </div>
        )}

        <NewBudgetForm />
      </CardContent>
    </Card>
  );
}

function BudgetRow({ status }: { status: BudgetStatus }) {
  const del = useDeleteBudget();
  const ratio = Math.min(1.5, status.usage_ratio);
  const percent = Math.min(150, Math.round(ratio * 100));
  const tone =
    status.exceeded
      ? "bg-destructive"
      : ratio > 0.8
        ? "bg-warning"
        : "bg-success";

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between text-sm">
        <div className="flex items-center gap-2">
          <span className="font-medium">{status.threshold.scope}</span>
          <span className="text-xs text-muted-foreground">
            · {status.threshold.period}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span
            className={cn(
              "text-xs tabular-nums",
              status.exceeded
                ? "text-destructive"
                : "text-muted-foreground",
            )}
          >
            ${status.used_usd.toFixed(2)} / ${status.threshold.limit_usd.toFixed(2)}
            <span className="ml-1">({percent}%)</span>
          </span>
          <Button
            size="icon"
            variant="ghost"
            onClick={() => {
              if (status.threshold.id == null) return;
              if (!confirm(`Delete budget for ${status.threshold.scope}?`)) return;
              del.mutate(status.threshold.id, {
                onSuccess: () => toast.success("Deleted"),
              });
            }}
            aria-label="delete budget"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-secondary">
        <div
          className={cn("h-full rounded-full transition-all", tone)}
          style={{ width: `${Math.min(100, percent)}%` }}
        />
      </div>
    </div>
  );
}

function NewBudgetForm() {
  const upsert = useUpsertBudget();
  const [scope, setScope] = useState("global");
  const [period, setPeriod] = useState<BudgetPeriod>("daily");
  const [limit, setLimit] = useState("");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const n = Number(limit);
    if (!Number.isFinite(n) || n < 0) {
      toast.error("limit_usd는 0 이상의 숫자");
      return;
    }
    upsert.mutate(
      {
        scope: scope.trim() || "global",
        period,
        limit_usd: n,
        notify_email: null,
        notify_webhook: null,
      },
      {
        onSuccess: () => {
          toast.success("Saved");
          setLimit("");
        },
        onError: (err: unknown) =>
          toast.error(err instanceof ApiError ? err.message : "Save failed"),
      },
    );
  }

  return (
    <form
      onSubmit={submit}
      className="grid gap-3 border-t border-border pt-4 sm:grid-cols-[1fr_120px_120px_auto]"
    >
      <div className="space-y-1.5">
        <Label>Scope</Label>
        <Input
          value={scope}
          onChange={(e) => setScope(e.currentTarget.value)}
          placeholder="global · project:my-app · role:backend"
        />
      </div>
      <div className="space-y-1.5">
        <Label>Period</Label>
        <Select
          value={period}
          onChange={(e) => setPeriod(e.currentTarget.value as BudgetPeriod)}
        >
          <option value="daily">Daily</option>
          <option value="monthly">Monthly</option>
        </Select>
      </div>
      <div className="space-y-1.5">
        <Label>Limit USD</Label>
        <Input
          type="number"
          min={0}
          step={0.5}
          value={limit}
          onChange={(e) => setLimit(e.currentTarget.value)}
          placeholder="e.g. 25"
          required
        />
      </div>
      <div className="flex items-end">
        <Button
          type="submit"
          loading={upsert.isPending}
          disabled={!limit}
        >
          <Plus className="h-3.5 w-3.5" />
          Add / Update
        </Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function isoStartOfRange(r: Range): string {
  const days = r === "7d" ? 7 : r === "30d" ? 30 : 90;
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  d.setUTCHours(0, 0, 0, 0);
  return d.toISOString();
}

function formatTokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}K`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}
