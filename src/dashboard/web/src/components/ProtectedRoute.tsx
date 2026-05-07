import { useEffect, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { api, ApiError } from "@/lib/api";
import { wsClient } from "@/lib/ws";
import { useToken } from "@/lib/auth";

// 백엔드가 토큰을 요구하지 않는 경우 토큰 없이도 통과시킨다.
// 한 번 ping → 200이면 인증 비활성, 401이면 로그인 필요.
type Probe = "loading" | "open" | "required";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const token = useToken();
  const location = useLocation();
  const [probe, setProbe] = useState<Probe>("loading");

  useEffect(() => {
    let cancelled = false;
    api
      .get("/api/metrics")
      .then(() => !cancelled && setProbe("open"))
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) setProbe("required");
        else setProbe("open");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    if (probe === "open" || (probe === "required" && token)) {
      wsClient.connect();
      return () => wsClient.disconnect();
    }
  }, [probe, token]);

  if (probe === "loading") {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }

  if (probe === "required" && !token) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <>{children}</>;
}
