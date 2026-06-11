"use client";

import { useState, useEffect, FormEvent } from "react";
import { X } from "lucide-react";
import type { Client, FirmUser } from "@/lib/types";
import type { CreateTaskInput } from "@/lib/data/tasks";

const PRIORITIES = ["low", "medium", "high", "critical"] as const;

const TASK_TEMPLATES = [
  "Collect Documents",
  "Classify Supplies — GSTR-1",
  "Compute Tax Liability — GSTR-3B",
  "Reconcile ITC — GSTR-2B",
  "Prepare ITR Computation",
  "CA Review",
  "File GSTR-1",
  "File GSTR-3B",
  "File ITR",
  "TDS Return — 26Q",
  "Advance Tax Computation",
  "Bank Reconciliation",
  "Custom",
];

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved: (task: import("@/lib/types").Task) => void;
  clients: Client[];
  teamMembers?: FirmUser[];
  defaultClientId?: string;
}

const EMPTY: CreateTaskInput = {
  client_id: "",
  title: "",
  description: "",
  priority: "medium",
  due_date: "",
  assignee_id: "",
};

export function TaskFormModal({ open, onClose, onSaved, clients, teamMembers = [], defaultClientId }: Props) {
  const [form, setForm] = useState<CreateTaskInput>({ ...EMPTY, client_id: defaultClientId ?? "" });
  const [customTitle, setCustomTitle] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setForm({ ...EMPTY, client_id: defaultClientId ?? "" });
      setCustomTitle(false);
      setError(null);
    }
  }, [open, defaultClientId]);

  function set(field: keyof CreateTaskInput, value: string) {
    setForm(f => ({ ...f, [field]: value }));
  }

  function handleTemplateChange(val: string) {
    if (val === "Custom") {
      setCustomTitle(true);
      set("title", "");
    } else {
      setCustomTitle(false);
      set("title", val);
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!form.client_id) { setError("Please select a client"); return; }
    if (!form.title.trim()) { setError("Please enter a task title"); return; }

    setSaving(true);
    setError(null);
    try {
      const { createTask } = await import("@/lib/data/tasks");
      const saved = await createTask(form);
      onSaved(saved);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save task");
    } finally {
      setSaving(false);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#F1F5F9]">
          <div>
            <h2 className="text-base font-semibold text-[#0F172A]">New Task</h2>
            <p className="text-xs text-[#64748B] mt-0.5">Create a task for a client</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-[#F1F5F9] text-[#94A3B8]">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {/* Client */}
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Client *</label>
            <select
              required
              value={form.client_id}
              onChange={e => set("client_id", e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
            >
              <option value="">Select client…</option>
              {clients.map(c => (
                <option key={c.id} value={c.id}>{c.client_name}</option>
              ))}
            </select>
          </div>

          {/* Assignee */}
          {teamMembers.length > 0 && (
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">Assign To</label>
              <select
                value={form.assignee_id ?? ""}
                onChange={e => set("assignee_id", e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
              >
                <option value="">Unassigned</option>
                {teamMembers.map(m => (
                  <option key={m.id} value={m.id}>{m.full_name ?? m.email}</option>
                ))}
              </select>
            </div>
          )}

          {/* Task type */}
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Task Type *</label>
            <select
              onChange={e => handleTemplateChange(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
            >
              <option value="">Select task type…</option>
              {TASK_TEMPLATES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>

          {/* Custom title */}
          {customTitle && (
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">Task Title *</label>
              <input
                required
                value={form.title}
                onChange={e => set("title", e.target.value)}
                placeholder="Describe the task…"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
              />
            </div>
          )}

          {/* Priority + Due Date */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">Priority</label>
              <select
                value={form.priority}
                onChange={e => set("priority", e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
              >
                {PRIORITIES.map(p => (
                  <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">Due Date</label>
              <input
                type="date"
                value={form.due_date}
                onChange={e => set("due_date", e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
              />
            </div>
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Notes</label>
            <textarea
              value={form.description}
              onChange={e => set("description", e.target.value)}
              rows={2}
              placeholder="Any additional notes…"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500 resize-none"
            />
          </div>

          {error && (
            <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <div className="flex gap-3 pt-1">
            <button
              type="button" onClick={onClose}
              className="flex-1 rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-medium text-[#334155] hover:bg-[#F8FAFC]"
            >
              Cancel
            </button>
            <button
              type="submit" disabled={saving}
              className="flex-1 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
            >
              {saving ? "Creating…" : "Create Task"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
