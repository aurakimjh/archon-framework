import { type LucideIcon, Inbox } from "lucide-react";
import { type ReactNode } from "react";

import { cn } from "@/lib/cn";

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 px-4 py-10 text-center",
        className,
      )}
    >
      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-secondary text-muted-foreground">
        <Icon className="h-5 w-5" aria-hidden />
      </div>
      <div>
        <div className="text-sm font-medium text-foreground">{title}</div>
        {description && (
          <div className="mt-1 text-xs text-muted-foreground">{description}</div>
        )}
      </div>
      {action}
    </div>
  );
}
