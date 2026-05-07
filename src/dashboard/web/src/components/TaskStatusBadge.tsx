import { Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { TaskStatus } from "@/types";

const STYLE: Record<
  TaskStatus,
  { variant: "default" | "success" | "warning" | "destructive" | "secondary"; label: string; spinning?: boolean }
> = {
  pending: { variant: "secondary", label: "Pending" },
  running: { variant: "warning", label: "Running", spinning: true },
  succeeded: { variant: "success", label: "Succeeded" },
  failed: { variant: "destructive", label: "Failed" },
  cancelled: { variant: "secondary", label: "Cancelled" },
};

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  const s = STYLE[status];
  return (
    <Badge variant={s.variant}>
      {s.spinning && <Loader2 className="mr-1 inline h-3 w-3 animate-spin" />}
      {s.label}
    </Badge>
  );
}
