"use client";
export const runtime = "edge";

import { useState } from "react";
import { Bell, ChevronLeft, ChevronRight } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/ui/use-toast";

const CLIENTS = [
  {
    id: "1",
    name: "Sharma Enterprises",
    gstin: "27AABCS1429B1ZB",
    status: "GSTR-1 due in 3 days",
    urgency: "red",
    details: [
      { type: "GSTR-1", due: "3 days", status: "pending" },
      { type: "GSTR-3B", due: "18 days", status: "pending" },
    ],
  },
  {
    id: "2",
    name: "Patel & Sons",
    gstin: "27AAPCS4229B1ZC",
    status: "GSTR-3B due in 8 days",
    urgency: "green",
    details: [
      { type: "GSTR-1", due: "Filed", status: "filed" },
      { type: "GSTR-3B", due: "8 days", status: "pending" },
    ],
  },
  {
    id: "3",
    name: "Mehta Consulting",
    gstin: "27AACCS7829B1ZD",
    status: "GSTR-1 OVERDUE",
    urgency: "overdue",
    details: [
      { type: "GSTR-1", due: "2 days overdue", status: "overdue" },
      { type: "GSTR-3B", due: "10 days overdue", status: "overdue" },
    ],
  },
  {
    id: "4",
    name: "Desai Traders",
    gstin: "27AADCS9929B1ZE",
    status: "All clear this month",
    urgency: "green",
    details: [
      { type: "GSTR-1", due: "Filed", status: "filed" },
      { type: "GSTR-3B", due: "Filed", status: "filed" },
    ],
  },
  {
    id: "5",
    name: "Joshi Textiles",
    gstin: "27AAJCS3329B1ZF",
    status: "ITR due in 12 days",
    urgency: "amber",
    details: [
      { type: "GSTR-1", due: "Filed", status: "filed" },
      { type: "GSTR-3B", due: "Filed", status: "filed" },
      { type: "ITR", due: "12 days", status: "pending" },
    ],
  },
];

const urgencyStyles: Record<string, string> = {
  red: "border-l-red-500 bg-red-50",
  overdue: "border-l-red-700 bg-red-100",
  amber: "border-l-amber-500 bg-amber-50",
  green: "border-l-green-500 bg-green-50",
};

const urgencyBadge: Record<string, string> = {
  red: "bg-red-100 text-red-700",
  overdue: "bg-red-200 text-red-800 font-bold",
  amber: "bg-amber-100 text-amber-700",
  green: "bg-green-100 text-green-700",
};

const statusColor: Record<string, string> = {
  filed: "text-green-600",
  pending: "text-amber-600",
  overdue: "text-red-700 font-bold",
};

export default function CalendarPage() {
  const [selectedClient, setSelectedClient] = useState(CLIENTS[0]);
  const { toast } = useToast();

  const sendReminder = (clientName: string) => {
    toast({
      title: "Reminder Sent",
      description: `WhatsApp reminder sent to ${clientName}`,
    });
  };

  const now = new Date();
  const monthName = now.toLocaleString("default", { month: "long", year: "numeric" });

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Compliance Calendar</h1>
          <p className="text-gray-500 text-sm mt-1">Track deadlines across all clients</p>
        </div>
        <div className="flex items-center gap-2 text-gray-600">
          <button className="p-1 hover:bg-gray-100 rounded"><ChevronLeft size={18} /></button>
          <span className="text-sm font-medium w-36 text-center">{monthName}</span>
          <button className="p-1 hover:bg-gray-100 rounded"><ChevronRight size={18} /></button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="space-y-2">
          <p className="text-xs text-gray-500 uppercase tracking-wide font-semibold mb-3">Clients</p>
          {CLIENTS.map((client) => (
            <div
              key={client.id}
              onClick={() => setSelectedClient(client)}
              className={`
                border-l-4 rounded-r-lg px-4 py-3 cursor-pointer transition-all
                ${urgencyStyles[client.urgency]}
                ${selectedClient.id === client.id ? "ring-2 ring-blue-500 ring-offset-1" : "hover:opacity-90"}
              `}
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold text-gray-900">{client.name}</p>
                  <p className="text-xs text-gray-500 mt-0.5 font-mono">{client.gstin}</p>
                </div>
                <span className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${urgencyBadge[client.urgency]}`}>
                  {client.urgency === "overdue" ? "OVERDUE" : client.urgency === "red" ? "Urgent" : client.urgency === "amber" ? "Soon" : "On Track"}
                </span>
              </div>
              <p className="text-xs text-gray-600 mt-1">{client.status}</p>
            </div>
          ))}
        </div>

        <div className="lg:col-span-2">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-3">
              <div>
                <CardTitle className="text-base">{selectedClient.name}</CardTitle>
                <p className="text-xs text-gray-500 font-mono mt-0.5">{selectedClient.gstin}</p>
              </div>
              <button
                onClick={() => sendReminder(selectedClient.name)}
                className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white text-sm rounded-lg hover:bg-green-700 transition-colors"
              >
                <Bell size={14} />
                Send Reminder
              </button>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-gray-500 uppercase tracking-wide font-semibold mb-3">Compliance Status</p>
              <div className="space-y-3">
                {selectedClient.details.map((item, i) => (
                  <div key={i} className="flex items-center justify-between py-3 border-b border-gray-100 last:border-0">
                    <div>
                      <p className="text-sm font-medium text-gray-900">{item.type}</p>
                      <p className={`text-xs mt-0.5 ${statusColor[item.status]}`}>
                        {item.status === "filed"
                          ? "Filed"
                          : item.status === "overdue"
                          ? `${item.due}`
                          : `Due in ${item.due}`}
                      </p>
                    </div>
                    <Badge
                      variant="secondary"
                      className={
                        item.status === "filed"
                          ? "bg-green-100 text-green-700"
                          : item.status === "overdue"
                          ? "bg-red-100 text-red-700"
                          : "bg-amber-100 text-amber-700"
                      }
                    >
                      {item.status}
                    </Badge>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
