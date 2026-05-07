import { useWebSocketStatus } from "@/lib/hooks";
import { cn } from "@/lib/cn";

const LABEL = {
  connecting: "Connecting…",
  open: "Live",
  closed: "Offline",
  error: "Error",
} as const;

const COLOR = {
  connecting: "bg-warning",
  open: "bg-success",
  closed: "bg-muted-foreground",
  error: "bg-destructive",
} as const;

export function ConnectionPill() {
  const status = useWebSocketStatus();
  return (
    <div
      role="status"
      aria-live="polite"
      className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-xs text-muted-foreground"
    >
      <span
        className={cn(
          "inline-block h-2 w-2 rounded-full",
          COLOR[status],
          status === "open" && "animate-pulse",
        )}
      />
      {LABEL[status]}
    </div>
  );
}
