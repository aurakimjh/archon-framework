import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AlertTriangle, Check, ShieldCheck, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/EmptyState";
import { GateBadge } from "@/components/GateBadge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import {
  useApproveGate,
  useGate,
  useGateQueue,
  useRejectGate,
} from "@/lib/hooks";
import { cn } from "@/lib/cn";
import type { GateQueueItem } from "@/types";

export function GatesPage() {
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("handoff");
  const queue = useGateQueue();

  const items = queue.data ?? [];
  const firstId = items[0]?.handoff_id ?? null;

  // 큐가 도착했는데 선택이 없으면 첫 항목을 자동 선택.
  useEffect(() => {
    if (!selectedId && firstId) {
      setParams({ handoff: firstId }, { replace: true });
    }
  }, [selectedId, firstId, setParams]);

  function select(id: string) {
    setParams({ handoff: id }, { replace: true });
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(280px,360px)_1fr]">
      <Card>
        <CardHeader className="border-b border-border pb-4">
          <CardTitle className="flex items-center gap-2 text-sm">
            <ShieldCheck className="h-4 w-4 text-muted-foreground" />
            Pending Queue
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <GateList
            loading={queue.isLoading}
            error={queue.isError}
            data={items}
            selectedId={selectedId}
            onSelect={select}
          />
        </CardContent>
      </Card>

      {selectedId ? (
        <GateDetail
          handoffId={selectedId}
          onResolved={() => {
            // 결정 후 큐 재로드되고 첫 항목이 자동 선택될 것.
            setParams({}, { replace: true });
          }}
        />
      ) : (
        <Card>
          <CardContent className="py-16">
            <EmptyState
              icon={ShieldCheck}
              title="No gate selected"
              description="좌측에서 항목을 선택해 상세를 확인하세요."
            />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 리스트
// ---------------------------------------------------------------------------

function GateList({
  loading,
  error,
  data,
  selectedId,
  onSelect,
}: {
  loading: boolean;
  error: boolean;
  data: GateQueueItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (loading) {
    return (
      <div className="space-y-2 p-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-14" />
        ))}
      </div>
    );
  }
  if (error) {
    return (
      <EmptyState
        icon={AlertTriangle}
        title="Error"
        description="Gate 큐를 불러오지 못했습니다."
      />
    );
  }
  if (data.length === 0) {
    return (
      <EmptyState
        icon={ShieldCheck}
        title="All clear"
        description="대기 중인 Gate가 없습니다."
      />
    );
  }
  return (
    <ul className="divide-y divide-border">
      {data.map((g) => (
        <li key={g.handoff_id}>
          <button
            type="button"
            onClick={() => onSelect(g.handoff_id)}
            className={cn(
              "flex w-full flex-col gap-1 px-4 py-3 text-left transition-colors hover:bg-secondary",
              selectedId === g.handoff_id && "bg-secondary",
            )}
          >
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs">
                {g.handoff_id.slice(0, 16)}…
              </span>
              <GateBadge level={g.gate_level} />
            </div>
            <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <span>{g.project_id}</span>
              <span>·</span>
              <span className="capitalize">{g.agent_role}</span>
              {typeof g.review_score === "number" && (
                <>
                  <span>·</span>
                  <span>score {g.review_score}</span>
                </>
              )}
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// 상세 + 결정
// ---------------------------------------------------------------------------

function GateDetail({
  handoffId,
  onResolved,
}: {
  handoffId: string;
  onResolved: () => void;
}) {
  const gate = useGate(handoffId);
  const approve = useApproveGate();
  const reject = useRejectGate();

  const [comment, setComment] = useState("");
  const [reviewer, setReviewer] = useState("");

  useEffect(() => {
    setComment("");
  }, [handoffId]);

  if (gate.isLoading) {
    return (
      <Card>
        <CardContent className="space-y-3 p-6">
          <Skeleton className="h-5 w-1/2" />
          <Skeleton className="h-32" />
        </CardContent>
      </Card>
    );
  }

  if (gate.isError || !gate.data) {
    return (
      <Card>
        <CardContent className="py-16">
          <EmptyState
            icon={AlertTriangle}
            title="Gate not found"
            description="해당 핸드오프가 존재하지 않거나 이미 결정되었습니다."
          />
        </CardContent>
      </Card>
    );
  }

  const g = gate.data;
  const decided = g.status !== "pending";

  function onApprove() {
    approve.mutate(
      { handoffId, body: { comment: comment.trim() || null, reviewer: reviewer.trim() || null } },
      {
        onSuccess: () => {
          toast.success("Approved");
          onResolved();
        },
        onError: (err: unknown) =>
          toast.error(err instanceof ApiError ? err.message : "Approve failed"),
      },
    );
  }

  function onReject() {
    if (!comment.trim()) {
      toast.error("Reject 사유(comment)는 필수입니다.");
      return;
    }
    reject.mutate(
      { handoffId, body: { comment: comment.trim(), reviewer: reviewer.trim() || null } },
      {
        onSuccess: () => {
          toast.success("Rejected");
          onResolved();
        },
        onError: (err: unknown) =>
          toast.error(err instanceof ApiError ? err.message : "Reject failed"),
      },
    );
  }

  const payloadStr = useMemo(
    () => JSON.stringify(g.payload, null, 2),
    [g.payload],
  );

  return (
    <Card>
      <CardHeader className="border-b border-border pb-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="break-all font-mono text-xs">
              {g.handoff_id}
            </CardTitle>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <GateBadge level={g.gate_level} />
              <span>{g.project_id}</span>
              <span>·</span>
              <span className="capitalize">{g.agent_role || "-"}</span>
              {typeof g.review_score === "number" && (
                <>
                  <span>·</span>
                  <span>score {g.review_score}</span>
                </>
              )}
              {decided && (
                <>
                  <span>·</span>
                  <span className="capitalize">{g.status}</span>
                </>
              )}
            </div>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-5 pt-5">
        {g.trigger_reason && (
          <div>
            <Label>Trigger reason</Label>
            <p className="mt-1.5 text-sm">{g.trigger_reason}</p>
          </div>
        )}

        <div>
          <Label>Payload</Label>
          <pre className="mt-1.5 max-h-72 overflow-auto whitespace-pre rounded-md border border-border bg-background/40 p-3 text-xs text-foreground/90 scrollbar-thin">
            {payloadStr === "{}" ? "(empty)" : payloadStr}
          </pre>
        </div>

        {decided ? (
          <DecidedSummary g={g} />
        ) : (
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
              <div>
                <Label>Comment</Label>
                <Textarea
                  value={comment}
                  onChange={(e) => setComment(e.currentTarget.value)}
                  placeholder="Approve는 선택, Reject는 필수"
                  rows={3}
                />
              </div>
              <div className="sm:w-44">
                <Label>Reviewer (optional)</Label>
                <Input
                  value={reviewer}
                  onChange={(e) => setReviewer(e.currentTarget.value)}
                  placeholder="alice"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={onReject}
                loading={reject.isPending}
                disabled={!comment.trim()}
              >
                <X className="h-3.5 w-3.5" />
                Reject
              </Button>
              <Button
                size="sm"
                onClick={onApprove}
                loading={approve.isPending}
              >
                <Check className="h-3.5 w-3.5" />
                Approve
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DecidedSummary({
  g,
}: {
  g: { decision_comment: string | null; decided_by: string | null; decided_at: string | null; status: string };
}) {
  return (
    <div className="rounded-md border border-border bg-background/40 p-4 text-sm">
      <div className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">
        {g.status === "approved" ? "Approved" : "Rejected"}
        {g.decided_by && ` by ${g.decided_by}`}
        {g.decided_at && ` · ${new Date(g.decided_at).toLocaleString()}`}
      </div>
      <div className="text-foreground/90">{g.decision_comment ?? "(no comment)"}</div>
    </div>
  );
}
