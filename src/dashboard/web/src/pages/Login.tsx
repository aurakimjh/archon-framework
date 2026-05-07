import { useState, type FormEvent } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import { setToken } from "@/lib/auth";

interface LocationState {
  from?: { pathname?: string };
}

export function LoginPage() {
  const [token, setTokenInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as LocationState | null)?.from?.pathname ?? "/overview";

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!token.trim()) return;
    setSubmitting(true);

    setToken(token.trim());

    try {
      await api.get("/api/metrics");
      toast.success("Signed in");
      navigate(from, { replace: true });
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 401) {
        toast.error("Invalid token");
      } else {
        toast.error("Could not reach server");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex h-full items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="space-y-2 text-center">
          <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <ShieldCheck className="h-5 w-5" aria-hidden />
          </div>
          <CardTitle className="text-lg">Archon Dashboard</CardTitle>
          <p className="text-xs text-muted-foreground">
            ARCHON_DASHBOARD_TOKEN 으로 로그인
          </p>
        </CardHeader>
        <CardContent>
          <form className="space-y-3" onSubmit={handleSubmit}>
            <label className="block">
              <span className="mb-1.5 block text-xs font-medium text-muted-foreground">
                Dashboard Token
              </span>
              <Input
                type="password"
                value={token}
                onChange={(e) => setTokenInput(e.target.value)}
                placeholder="Enter token"
                autoFocus
                required
              />
            </label>
            <Button
              type="submit"
              className="w-full"
              loading={submitting}
              disabled={!token.trim()}
            >
              Sign in
            </Button>
            <p className="text-center text-[11px] text-muted-foreground">
              서버에 토큰이 설정되지 않은 경우 빈 값으로도 접속 가능합니다.
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
