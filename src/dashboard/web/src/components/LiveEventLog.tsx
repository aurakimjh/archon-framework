import { useMemo, useState } from "react";
import { Pause, Play, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/components/EmptyState";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import type { DashboardEvent } from "@/types";

interface Props {
  events: DashboardEvent[];
}

export function LiveEventLog({ events }: Props) {
  const [paused, setPaused] = useState(false);
  const [filter, setFilter] = useState("");
  const [snapshot, setSnapshot] = useState<DashboardEvent[]>([]);

  const visible = useMemo(() => {
    const source = paused ? snapshot : events;
    if (!filter.trim()) return source;
    const q = filter.toLowerCase();
    return source.filter(
      (e) =>
        e.event_type.toLowerCase().includes(q) ||
        JSON.stringify(e.payload).toLowerCase().includes(q),
    );
  }, [paused, snapshot, events, filter]);

  function togglePause() {
    if (!paused) setSnapshot(events);
    setPaused((p) => !p);
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Input
          placeholder="Filter events…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="h-8 max-w-xs"
        />
        <div className="ml-auto flex items-center gap-1.5">
          <Badge variant="secondary">{visible.length} events</Badge>
          <Button size="sm" variant="ghost" onClick={togglePause}>
            {paused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
            {paused ? "Resume" : "Pause"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setSnapshot([])}
            disabled={!paused || snapshot.length === 0}
          >
            <Trash2 className="h-3.5 w-3.5" />
            Clear
          </Button>
        </div>
      </div>

      <div className="max-h-96 overflow-y-auto rounded-md border border-border bg-background/40 scrollbar-thin">
        {visible.length === 0 ? (
          <EmptyState title="No events" description="이벤트가 도착하면 여기에 표시됩니다." />
        ) : (
          <ul className="divide-y divide-border font-mono text-xs">
            {visible.map((e, idx) => (
              <EventRow key={`${e.timestamp}-${idx}`} event={e} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function EventRow({ event }: { event: DashboardEvent }) {
  const time = new Date(event.timestamp).toLocaleTimeString();
  const tone = TYPE_TONE[event.event_type] ?? "default";

  return (
    <li className="flex items-start gap-3 px-3 py-2">
      <span className="shrink-0 text-[10px] uppercase tracking-wider text-muted-foreground">
        {time}
      </span>
      <Badge variant={tone} className="shrink-0">
        {event.event_type}
      </Badge>
      <span className={cn("min-w-0 break-all text-foreground/90")}>
        {summarize(event)}
      </span>
    </li>
  );
}

const TYPE_TONE: Record<string, "default" | "success" | "warning" | "destructive" | "secondary"> = {
  pipeline_step: "secondary",
  gate_approved: "success",
  gate_rejected: "destructive",
  project_updated: "default",
};

function summarize(event: DashboardEvent): string {
  if (event.event_type === "pipeline_step") {
    const step = (event.payload.step as string | undefined) ?? "?";
    const data = event.payload.data;
    return `${step} · ${typeof data === "string" ? data : JSON.stringify(data)}`;
  }
  return JSON.stringify(event.payload);
}
