import { cn } from "@/lib/cn";
import type { HealthStatus } from "@/types";

const COLOR: Record<string, string> = {
  healthy: "bg-success",
  degraded: "bg-warning",
  unhealthy: "bg-destructive",
  unknown: "bg-muted-foreground",
};

export function StatusDot({
  status,
  pulse = false,
}: {
  status: HealthStatus | string;
  pulse?: boolean;
}) {
  const cls = COLOR[status] ?? COLOR.unknown;
  return (
    <span
      role="img"
      aria-label={`status: ${status}`}
      className="relative inline-flex h-2.5 w-2.5"
    >
      {pulse && status === "healthy" && (
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success/60" />
      )}
      <span className={cn("relative inline-flex h-2.5 w-2.5 rounded-full", cls)} />
    </span>
  );
}
