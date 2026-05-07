import { useState } from "react";
import { useParams } from "react-router-dom";
import {
  Activity,
  Bot,
  ChevronLeft,
  ClipboardList,
  Search,
  ShieldCheck,
} from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/EmptyState";
import { GateBadge } from "@/components/GateBadge";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { TaskStatusBadge } from "@/components/TaskStatusBadge";
import { useProjectMemory, useProjectTimeline } from "@/lib/hooks";
import { cn } from "@/lib/cn";
import type { TaskStatus, TimelineItem } from "@/types";

export function ProjectDetailPage() {
  const { id = "" } = useParams<{ id: string }>();
  const timeline = useProjectTimeline(id);
  const [q, setQ] = useState("");
  const [searched, setSearched] = useState<string | null>(null);
  const memory = useProjectMemory(id, searched);

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <Link
          to="/projects"
          className="inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground"
        >
          <ChevronLeft className="h-4 w-4" />
          Projects
        </Link>
        <h1 className="font-mono text-sm">{id}</h1>
      </div>

      <Card>
        <CardHeader className="border-b border-border pb-4">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Activity className="h-4 w-4 text-muted-foreground" />
            Timeline
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-5">
          {timeline.isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-10" />
              ))}
            </div>
          ) : (timeline.data ?? []).length === 0 ? (
            <EmptyState
              icon={ClipboardList}
              title="No activity yet"
              description="이 프로젝트에 작업·게이트 활동이 기록되면 표시됩니다."
            />
          ) : (
            <ol className="relative space-y-3">
              <span
                aria-hidden
                className="pointer-events-none absolute left-3 top-2 bottom-2 w-px bg-border"
              />
              {(timeline.data ?? []).map((it) => (
                <TimelineRow key={`${it.kind}-${it.id}`} item={it} />
              ))}
            </ol>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-border pb-4">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Search className="h-4 w-4 text-muted-foreground" />
            Memory search
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 pt-5">
          <form
            className="flex items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              setSearched(q.trim() || null);
            }}
          >
            <Input
              value={q}
              onChange={(e) => setQ(e.currentTarget.value)}
              placeholder="검색어 (예: API 변경, 인증 정책 등)"
            />
            <Button type="submit" disabled={!q.trim()}>
              Search
            </Button>
          </form>

          {!searched ? (
            <p className="text-xs text-muted-foreground">
              검색어를 입력하면 프로젝트 메모리에서 관련 항목을 찾습니다.
            </p>
          ) : memory.isLoading ? (
            <Skeleton className="h-24 w-full" />
          ) : !memory.data?.available ? (
            <EmptyState
              title="Memory unavailable"
              description={
                memory.data?.error ??
                "메모리 모듈(mem0)이 환경에 설치/구성되어 있지 않습니다."
              }
            />
          ) : memory.data.results.length === 0 ? (
            <EmptyState title="No matches" />
          ) : (
            <ul className="divide-y divide-border">
              {memory.data.results.map((r, i) => (
                <li key={i} className="py-2 text-sm">
                  <div className="text-foreground/90">{r.memory}</div>
                  {r.score > 0 && (
                    <div className="mt-0.5 text-[11px] text-muted-foreground">
                      score {r.score.toFixed(3)}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function TimelineRow({ item }: { item: TimelineItem }) {
  const isTask = item.kind === "task";
  const Icon = isTask ? Bot : ShieldCheck;
  return (
    <li className="relative pl-9">
      <span className="absolute left-1 top-1 flex h-4 w-4 items-center justify-center rounded-full bg-secondary">
        <Icon className="h-2.5 w-2.5 text-muted-foreground" aria-hidden />
      </span>
      <div className="flex flex-col gap-1 rounded-md border border-border bg-background/40 p-3">
        <div className="flex flex-wrap items-center gap-2">
          {isTask ? (
            <TaskStatusBadge status={(item.status as TaskStatus) ?? "pending"} />
          ) : (
            <Badge
              variant={
                item.status === "approved"
                  ? "success"
                  : item.status === "rejected"
                    ? "destructive"
                    : "secondary"
              }
            >
              {item.status}
            </Badge>
          )}
          {!isTask && item.gate_level && (
            <GateBadge level={item.gate_level} />
          )}
          <span className="font-mono text-xs">
            {isTask ? item.id.slice(-12) : item.id.slice(0, 12) + "…"}
          </span>
          <span className="text-xs capitalize text-muted-foreground">
            · {item.agent_role || "-"}
          </span>
          <span className="ml-auto text-[11px] text-muted-foreground">
            {new Date(item.timestamp).toLocaleString()}
          </span>
        </div>
        {isTask && item.instructions && (
          <p
            className={cn(
              "max-w-2xl truncate text-xs text-muted-foreground",
            )}
          >
            {item.instructions}
          </p>
        )}
        {!isTask && item.decided_by && (
          <p className="text-xs text-muted-foreground">
            decided by {item.decided_by}
            {item.decided_at && ` · ${new Date(item.decided_at).toLocaleString()}`}
          </p>
        )}
      </div>
    </li>
  );
}
