import { LogOut } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { ConnectionPill } from "@/components/ConnectionPill";
import { clearToken, useToken } from "@/lib/auth";

export function Topbar({ title }: { title: string }) {
  const token = useToken();
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
