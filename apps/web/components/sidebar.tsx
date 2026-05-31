"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Home,
  Upload,
  MessageSquare,
  Calendar,
  Users,
  Settings,
  ChevronLeft,
  ChevronRight,
  CheckSquare,
  UserCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "Dashboard", icon: Home },
  { href: "/tasks", label: "Tasks", icon: CheckSquare },
  { href: "/parser", label: "Document Parser", icon: Upload },
  { href: "/assistant", label: "GST Assistant", icon: MessageSquare },
  { href: "/calendar", label: "Compliance Calendar", icon: Calendar },
  { href: "/clients", label: "Clients", icon: Users },
  { href: "/team", label: "Team", icon: UserCheck },
];

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();

  return (
    <aside
      className={cn(
        "flex flex-col bg-white border-r border-gray-200 transition-all duration-300",
        collapsed ? "w-16" : "w-60"
      )}
    >
      <div className="flex items-center justify-between p-4 border-b border-gray-200">
        {!collapsed && (
          <span className="font-bold text-blue-700 text-lg tracking-tight">CAflow AI</span>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="ml-auto p-1 rounded hover:bg-gray-100 text-gray-500"
        >
          {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
        </button>
      </div>

      <nav className="flex-1 py-4 space-y-1 px-2">
        {navItems.map(({ href, label, icon: Icon }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                active
                  ? "bg-blue-50 text-blue-700"
                  : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
              )}
            >
              <Icon size={20} className="shrink-0" />
              {!collapsed && <span>{label}</span>}
            </Link>
          );
        })}
      </nav>

      <div className="p-4 border-t border-gray-200 flex items-center gap-3">
        <div className="w-8 h-8 rounded-full bg-blue-700 text-white flex items-center justify-center text-sm font-bold shrink-0">
          GL
        </div>
        {!collapsed && (
          <>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-900 truncate">Gavin Lobo, CA</p>
              <p className="text-xs text-gray-500 truncate">Practice Manager</p>
            </div>
            <button className="text-gray-400 hover:text-gray-600">
              <Settings size={16} />
            </button>
          </>
        )}
      </div>
    </aside>
  );
}
