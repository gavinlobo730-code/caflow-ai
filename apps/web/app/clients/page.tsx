import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const CLIENTS = [
  { name: "Sharma Enterprises", gstin: "27AABCS1429B1ZB", pan: "AABCS1429B", status: "active" },
  { name: "Patel & Sons", gstin: "27AAPCS4229B1ZC", pan: "AAPCS4229B", status: "active" },
  { name: "Mehta Consulting", gstin: "27AACCS7829B1ZD", pan: "AACCS7829B", status: "overdue" },
  { name: "Desai Traders", gstin: "27AADCS9929B1ZE", pan: "AADCS9929B", status: "active" },
  { name: "Joshi Textiles", gstin: "27AAJCS3329B1ZF", pan: "AAJCS3329B", status: "pending" },
];

export default function ClientsPage() {
  return (
    <div className="p-6 max-w-4xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Clients</h1>
          <p className="text-gray-500 text-sm mt-1">{CLIENTS.length} active clients</p>
        </div>
      </div>
      <Card>
        <CardContent className="p-0 divide-y divide-gray-100">
          {CLIENTS.map((c, i) => (
            <div key={i} className="flex items-center gap-4 px-6 py-4">
              <div className="w-10 h-10 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center font-bold text-sm shrink-0">
                {c.name[0]}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-gray-900">{c.name}</p>
                <p className="text-xs text-gray-500 font-mono mt-0.5">{c.gstin}</p>
              </div>
              <div className="text-right">
                <p className="text-xs text-gray-500">PAN</p>
                <p className="text-xs font-mono text-gray-700">{c.pan}</p>
              </div>
              <Badge
                variant="secondary"
                className={
                  c.status === "active"
                    ? "bg-green-100 text-green-700"
                    : c.status === "overdue"
                    ? "bg-red-100 text-red-700"
                    : "bg-amber-100 text-amber-700"
                }
              >
                {c.status}
              </Badge>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
