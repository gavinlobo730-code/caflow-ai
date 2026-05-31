import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { Client } from "@/lib/types";
import { ENTITY_TYPE_LABELS } from "@/lib/services/formatting";

const CLIENTS: Client[] = [
  { id: "c-001", client_name: "Sharma Enterprises", entity_type: "Proprietorship", pan: "AABCS1429B", gstin: "27AABCS1429B1ZB", mobile: "+91 98765 43210", email: "sharma@sharmaenterprises.in", city: "Mumbai", state: "Maharashtra", state_code: "27", gst_filing_frequency: "monthly", status: "active", created_at: new Date(Date.now() - 180 * 86400000).toISOString() },
  { id: "c-002", client_name: "Patel & Sons", entity_type: "Partnership", pan: "AAPCS4229B", gstin: "27AAPCS4229B1ZC", mobile: "+91 98765 43211", email: "patel@patelandsons.in", city: "Pune", state: "Maharashtra", state_code: "27", gst_filing_frequency: "monthly", status: "active", created_at: new Date(Date.now() - 120 * 86400000).toISOString() },
  { id: "c-003", client_name: "Mehta Consulting", entity_type: "LLP", pan: "AACCS7829B", gstin: "27AACCS7829B1ZD", mobile: "+91 98765 43212", email: "mehta@mehtaconsulting.in", city: "Mumbai", state: "Maharashtra", state_code: "27", gst_filing_frequency: "monthly", status: "active", created_at: new Date(Date.now() - 90 * 86400000).toISOString() },
  { id: "c-004", client_name: "Desai Traders", entity_type: "Proprietorship", pan: "AADCS9929B", gstin: "27AADCS9929B1ZE", mobile: "+91 98765 43213", email: "desai@desaitraders.in", city: "Mumbai", state: "Maharashtra", state_code: "27", gst_filing_frequency: "monthly", status: "active", created_at: new Date(Date.now() - 60 * 86400000).toISOString() },
  { id: "c-005", client_name: "Joshi Textiles", entity_type: "Private Limited", pan: "AAJCS3329B", gstin: "27AAJCS3329B1ZF", mobile: "+91 98765 43214", email: "joshi@joshitextiles.in", city: "Nashik", state: "Maharashtra", state_code: "27", gst_filing_frequency: "monthly", status: "active", created_at: new Date(Date.now() - 45 * 86400000).toISOString() },
];

export default function ClientsPage() {
  return (
    <div className="p-6 max-w-4xl mx-auto space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Clients</h1>
        <p className="text-gray-500 text-sm mt-1">{CLIENTS.length} active clients</p>
      </div>
      <Card>
        <CardContent className="p-0 divide-y divide-gray-100">
          {CLIENTS.map((c) => (
            <Link
              key={c.id}
              href={`/clients/${c.id}`}
              className="flex items-center gap-4 px-6 py-4 hover:bg-gray-50 transition-colors group"
            >
              <div className="w-10 h-10 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center font-bold text-sm shrink-0">
                {c.client_name[0]}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-gray-900">{c.client_name}</p>
                <p className="text-xs text-gray-500 font-mono mt-0.5">{c.gstin}</p>
              </div>
              <div className="text-right mr-2">
                <p className="text-xs text-gray-500">{ENTITY_TYPE_LABELS[c.entity_type] ?? c.entity_type}</p>
                <p className="text-xs font-mono text-gray-600">{c.pan}</p>
              </div>
              <Badge variant="secondary" className="bg-green-100 text-green-700 text-xs">
                {c.status}
              </Badge>
              <ChevronRight size={16} className="text-gray-400 group-hover:text-gray-600 shrink-0" />
            </Link>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
