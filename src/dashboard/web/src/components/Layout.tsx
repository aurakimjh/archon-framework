import { Outlet, useLocation } from "react-router-dom";

import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";

const TITLES: Record<string, string> = {
  "/overview": "Overview",
  "/projects": "Projects",
  "/agents": "Agents & Models",
  "/instructions": "Work Instructions",
  "/gates": "Human Gates",
  "/cost": "Cost & Usage",
  "/settings": "Settings",
};

export function Layout() {
  const location = useLocation();
  const title =
    TITLES[location.pathname] ??
    Object.entries(TITLES).find(([k]) => location.pathname.startsWith(k))?.[1] ??
    "Archon";

  return (
    <div className="flex h-full">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar title={title} />
        <main className="flex-1 overflow-y-auto scrollbar-thin">
          <div className="mx-auto w-full max-w-7xl p-6 animate-fade-in">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
