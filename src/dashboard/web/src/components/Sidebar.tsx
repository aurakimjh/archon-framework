import { NavLink } from "react-router-dom";
import {
  Activity,
  Banknote,
  Bot,
  ClipboardList,
  FolderKanban,
  ShieldCheck,
  Settings,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/cn";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

const NAV: NavItem[] = [
  { to: "/overview", label: "Overview", icon: Activity },
  { to: "/projects", label: "Projects", icon: FolderKanban },
  { to: "/agents", label: "Agents & Models", icon: Bot },
  { to: "/instructions", label: "Work Instructions", icon: ClipboardList },
  { to: "/gates", label: "Human Gates", icon: ShieldCheck },
  { to: "/cost", label: "Cost & Usage", icon: Banknote },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  return (
    <aside className="hidden w-60 shrink-0 border-r border-border bg-card md:flex md:flex-col">
      <div className="flex h-14 items-center gap-2 border-b border-border px-5">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <span className="text-sm font-bold">A</span>
        </div>
        <div>
          <div className="text-sm font-semibold leading-none">Archon</div>
          <div className="mt-0.5 text-[10px] uppercase tracking-wider text-muted-foreground">
            Framework
          </div>
        </div>
      </div>

      <nav className="flex-1 space-y-0.5 p-3">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground",
              )
            }
          >
            <Icon className="h-4 w-4" aria-hidden />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-border p-3 text-[11px] text-muted-foreground">
        v0.1.0 · develop
      </div>
    </aside>
  );
}
