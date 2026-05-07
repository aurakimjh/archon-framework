import { useNavigate } from "react-router-dom";
import { FolderKanban } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { useProjects } from "@/lib/hooks";

export function ProjectsPage() {
  const projects = useProjects();
  const navigate = useNavigate();

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader className="border-b border-border pb-4">
          <CardTitle className="flex items-center gap-2 text-sm">
            <FolderKanban className="h-4 w-4 text-muted-foreground" />
            Projects
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {projects.isLoading ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-9" />
              ))}
            </div>
          ) : (projects.data ?? []).length === 0 ? (
            <EmptyState
              icon={FolderKanban}
              title="No projects registered"
              description="ProjectRegistry에 항목이 추가되면 여기에 표시됩니다."
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Priority</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(projects.data ?? []).map((p) => (
                  <TableRow
                    key={p.project_id}
                    className="cursor-pointer"
                    onClick={() => navigate(`/projects/${p.project_id}`)}
                  >
                    <TableCell className="font-mono text-xs">
                      {p.project_id}
                    </TableCell>
                    <TableCell>{p.project_name || "—"}</TableCell>
                    <TableCell>
                      <span className="text-xs capitalize text-muted-foreground">
                        {p.status}
                      </span>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {p.priority}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
