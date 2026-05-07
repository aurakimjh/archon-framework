import { LogOut } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConnectionPill } from "@/components/ConnectionPill";
import { useMe } from "@/lib/hooks";
import { clearToken, useToken } from "@/lib/auth";

export function Topbar({ title }: { title: string }) {
  const token = useToken();
  const me = useMe();
  const navigate = useNavigate();

  function handleSignOut() {
    clearToken();
    navigate("/login", { replace: true });
  }

  return (
    <header className="flex h-14 items-center justify-between border-b border-border bg-card/60 px-6 backdrop-blur">
      <div>
        <h1 className="text-base font-semibold leading-none">{title}</h1>
      </div>
      <div className="flex items-center gap-3">
        <ConnectionPill />
        {me.data && (
          <div className="hidden items-center gap-2 text-xs text-muted-foreground sm:flex">
            <span className="font-mono">{me.data.user_id}</span>
            <Badge variant="secondary">{me.data.role}</Badge>
          </div>
        )}
        {token && (
          <Button variant="ghost" size="sm" onClick={handleSignOut}>
            <LogOut className="h-4 w-4" />
            Sign out
          </Button>
        )}
      </div>
    </header>
  );
}
