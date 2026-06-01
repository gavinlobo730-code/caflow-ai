import { Bot, AlertTriangle, Info, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";

interface AIInsight {
  type: "critical" | "high" | "medium" | "info";
  message: string;
  action?: string;
}

const config = {
  critical: { icon: AlertCircle, bg: "bg-red-50 border-red-200", text: "text-red-800", icon_color: "text-red-600" },
  high:     { icon: AlertTriangle, bg: "bg-orange-50 border-orange-200", text: "text-orange-800", icon_color: "text-orange-500" },
  medium:   { icon: AlertTriangle, bg: "bg-amber-50 border-amber-200", text: "text-amber-800", icon_color: "text-amber-500" },
  info:     { icon: Info, bg: "bg-blue-50 border-blue-200", text: "text-blue-800", icon_color: "text-blue-500" },
};

export function AIInsightBanner({ insights }: { insights: AIInsight[] }) {
  if (!insights.length) return null;
  return (
    <div className="space-y-2">
      {insights.map((insight, i) => {
        const c = config[insight.type];
        const Icon = c.icon;
        return (
          <div key={i} className={cn("flex items-start gap-3 border rounded-lg px-4 py-3", c.bg)}>
            <div className="flex items-center gap-1.5 shrink-0 mt-0.5">
              <Bot size={13} className={c.icon_color} />
              <Icon size={13} className={c.icon_color} />
            </div>
            <div className="flex-1 min-w-0">
              <p className={cn("text-xs font-medium", c.text)}>{insight.message}</p>
              {insight.action && (
                <p className={cn("text-xs mt-0.5 opacity-75", c.text)}>{insight.action}</p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
