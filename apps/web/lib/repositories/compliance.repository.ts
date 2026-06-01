import { api } from "@/lib/api";
import type { ComplianceTask, ApiResponse } from "@/lib/types";

export const complianceRepository = {
  async list(params?: { client_id?: string; status?: string }): Promise<ComplianceTask[]> {
    const res = await api.compliance.tasks(params) as ApiResponse<{ tasks: ComplianceTask[] }>;
    return res.success ? res.data.tasks : [];
  },

  async calendar(): Promise<ComplianceTask[]> {
    const res = await api.compliance.calendar() as ApiResponse<{ events: ComplianceTask[] }>;
    return res.success ? res.data.events : [];
  },

  async dueDates(year: number, month: number): Promise<Record<string, string>> {
    const res = await api.compliance.calculateDueDates(year, month) as ApiResponse<Record<string, string>>;
    return res.success ? res.data : {};
  },
};
