import { Suspense, lazy } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "@/components/Layout";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AgentsPage } from "@/pages/Agents";
import { GatesPage } from "@/pages/Gates";
import { InstructionsPage } from "@/pages/Instructions";
import { LoginPage } from "@/pages/Login";
import { OverviewPage } from "@/pages/Overview";
import { PlaceholderPage } from "@/pages/Placeholder";

// recharts(약 400KB)는 /cost에서만 필요하므로 분리 로드.
const CostPage = lazy(() =>
  import("@/pages/Cost").then((m) => ({ default: m.CostPage })),
);

function PageFallback() {
  return (
    <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
      Loading…
    </div>
  );
}

export function Router() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route path="/" element={<Navigate to="/overview" replace />} />
        <Route path="/overview" element={<OverviewPage />} />
        <Route
          path="/projects"
          element={<PlaceholderPage title="Projects" slice="Slice 3" />}
        />
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/instructions" element={<InstructionsPage />} />
        <Route path="/gates" element={<GatesPage />} />
        <Route
          path="/cost"
          element={
            <Suspense fallback={<PageFallback />}>
              <CostPage />
            </Suspense>
          }
        />
        <Route
          path="/settings"
          element={<PlaceholderPage title="Settings" slice="Slice 2" />}
        />
      </Route>
      <Route path="*" element={<Navigate to="/overview" replace />} />
    </Routes>
  );
}
