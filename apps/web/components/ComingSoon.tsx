import { Construction } from "lucide-react";

interface ComingSoonProps {
  title?: string;
  description?: string;
  module?: string;
}

export function ComingSoon({
  title,
  description = "This module is currently under development and will be available in a future release.",
  module,
}: ComingSoonProps) {
  const heading = title ?? (module ? `${module} — Coming Soon` : "Coming Soon");
  return (
    <div className="flex-1 flex items-center justify-center p-12 bg-[#F8FAFC]">
      <div className="text-center max-w-[340px]">
        <div className="w-16 h-16 rounded-2xl bg-blue-50 border border-blue-100 flex items-center justify-center mx-auto mb-5 shadow-sm">
          <Construction size={28} className="text-blue-500" />
        </div>
        <h2 className="text-[18px] font-semibold text-[#1E293B] tracking-tight">{heading}</h2>
        <p className="text-[14px] text-[#64748B] mt-2 leading-relaxed">{description}</p>
        <div className="mt-5 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-blue-50 border border-blue-100 text-[12px] font-medium text-blue-600">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
          In development
        </div>
      </div>
    </div>
  );
}
