import { api } from "@/lib/api";
import type { Client, ClientWorkspace, ApiResponse } from "@/lib/types";

export const clientRepository = {
  async list(): Promise<Client[]> {
    const res = await api.clients.list() as ApiResponse<{ clients: Client[] }>;
    return res.success ? res.data.clients : [];
  },

  async getWorkspace(id: string): Promise<ClientWorkspace | null> {
    try {
      const res = await api.clients.getWorkspace(id) as ApiResponse<ClientWorkspace>;
      return res.success ? res.data : null;
    } catch {
      return null;
    }
  },

  async create(data: Partial<Client>): Promise<Client | null> {
    try {
      const res = await api.clients.create(data) as ApiResponse<{ client: Client }>;
      return res.success ? res.data.client : null;
    } catch {
      return null;
    }
  },

  async update(id: string, data: Partial<Client>): Promise<Client | null> {
    try {
      const res = await api.clients.update(id, data) as ApiResponse<{ client: Client }>;
      return res.success ? res.data.client : null;
    } catch {
      return null;
    }
  },
};
