import { Check, ExternalLink, ShieldCheck } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { GateBadge } from "@/components/GateBadge";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useApproveGate } from "@/lib/hooks";
import type { GateQueueItem } from "@/types";

interface Props {
  loading: boolean;
  error: boolean;
  data: GateQueueItem[];
}

export function GateQueueTable({ loading, error, data }: Props) {
  const approve = useApproveGate();
  const navigate = useNavigate();

  if (loading) {
    return (
      <div className="space-y-2 p-4">
        {Array.from({ length: 2 }).map((_, i) => (
          <Skeleton key={i} className="h-9" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <EmptyState
        icon={ShieldCheck}
        title="Error"
        description="Gate 큐를 불러오지 못했습니다."
      />
    );
  }

  if (data.length === 0) {
    return (
      <EmptyState
        icon={ShieldCheck}
        title="No pending gates"
        description="모든 핸드오프가 자동 통과 상태입니다."
      />
    );
  }

  function onApprove(handoffId: string) {
    approve.mutate(
      { handoffId },
      {
        onSuccess: () => toast.success("Approved"),
        onError: () => toast.error("Approve failed"),
      },
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Handoff</TableHead>
          <TableHead>Project</TableHead>
          <TableHead>Level</TableHead>
          <TableHead>Agent</TableHead>
          <TableHead className="text-right">Action</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.map((g) => (
          <TableRow key={g.handoff_id}>
            <TableCell className="font-mono text-xs">
              {g.handoff_id.slice(0, 12)}…
            </TableCell>
            <TableCell>{g.project_id}</TableCell>
            <TableCell>
              <GateBadge level={g.gate_level} />
            </TableCell>
            <TableCell className="capitalize">{g.agent_role}</TableCell>
            <TableCell>
              <div className="flex justify-end gap-1.5">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onApprove(g.handoff_id)}
                  loading={
                    approve.isPending &&
                    approve.variables?.handoffId === g.handoff_id
                  }
                >
                  <Check className="h-3.5 w-3.5" />
                  Approve
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    navigate(
                      `/gates?handoff=${encodeURIComponent(g.handoff_id)}`,
                    )
                  }
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  Detail
                </Button>
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
