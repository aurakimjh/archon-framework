import { Badge } from "@/components/ui/badge";
import type { GateLevel } from "@/types";

const VARIANT: Record<string, "success" | "warning" | "default" | "destructive" | "secondary"> = {
  AUTO_PASS: "success",
  L1_REWORK: "warning",
  L2_HUMAN: "default",
  L3_HALT: "destructive",
  L4_DEPLOY: "success",
};

export function GateBadge({ level }: { level: GateLevel | string }) {
  const variant = VARIANT[level] ?? "secondary";
  return <Badge variant={variant}>{level}</Badge>;
}
