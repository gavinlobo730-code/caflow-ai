"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Plus, Trash2, Edit2, CheckSquare, Tag, Clock, User,
  X, AlertCircle, Loader2, Copy,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  listTaskTemplates,
  createTaskTemplate,
  updateTaskTemplate,
  deleteTaskTemplate,
  instantiateTemplate,
} from "@/lib/data/taskTemplates";
import { getClients } from "@/lib/data/clients";
import type { TaskTemplate, Client } from "@/lib/types";

const PRIORITY_COLORS: Record<string, string> = {
  low: "bg-white/[0.06] text-white/55",
  medium: "bg-blue-100 text-blue-700",
  high: "bg-amber-100 text-amber-700",
  critical: "bg-red-100 text-red-700",
};

const ROLE_OPTIONS = ["Partner", "Manager", "Executive", "Reviewer"];

type FormState = {
  name: string;
  description: string;
  default_priority: string;
  estimated_hours: string;
  tags: string;
  default_assignee_role: string;
};

const EMPTY_FORM: FormState = {
  name: "",
  description: "",
  default_priority: "medium",
  estimated_hours: "",
  tags: "",
  default_assignee_role: "",
};

export default function TaskTemplatesPage() {
  const [templates, setTemplates] = useState<TaskTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  // Instantiate dialog
  const [instantiateId, setInstantiateId] = useState<string | null>(null);
  const [clients, setClients] = useState<Client[]>([]);
  const [instClientId, setInstClientId] = useState("");
  const [instDueDate, setInstDueDate] = useState("");
  const [instAssignTo, setInstAssignTo] = useState("");
  const [instantiating, setInstantiating] = useState(false);
  const [instError, setInstError] = useState<string | null>(null);
  const [instSuccess, setInstSuccess] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { templates: t } = await listTaskTemplates();
      setTemplates(t);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load templates");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openCreate = () => {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setShowForm(true);
  };

  const openEdit = (t: TaskTemplate) => {
    setEditingId(t.id);
    setForm({
      name: t.name,
      description: t.description ?? "",
      default_priority: t.default_priority,
      estimated_hours: t.estimated_hours ? String(t.estimated_hours) : "",
      tags: t.tags.join(", "),
      default_assignee_role: t.default_assignee_role ?? "",
    });
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      const payload = {
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        default_priority: form.default_priority,
        estimated_hours: form.estimated_hours ? parseInt(form.estimated_hours) : undefined,
        tags: form.tags ? form.tags.split(",").map(t => t.trim()).filter(Boolean) : [],
        default_assignee_role: form.default_assignee_role || undefined,
      };
      if (editingId) {
        await updateTaskTemplate(editingId, payload);
      } else {
        await createTaskTemplate(payload);
      }
      setShowForm(false);
      setEditingId(null);
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this template?")) return;
    try {
      await deleteTaskTemplate(id);
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  };

  const openInstantiate = async (id: string) => {
    setInstantiateId(id);
    setInstClientId("");
    setInstDueDate("");
    setInstAssignTo("");
    setInstError(null);
    setInstSuccess(null);
    if (clients.length === 0) {
      const list = await getClients().catch(() => [] as Client[]);
      setClients(list);
    }
  };

  const handleInstantiate = async () => {
    if (!instantiateId || !instClientId) {
      setInstError("Select a client");
      return;
    }
    setInstantiating(true);
    setInstError(null);
    try {
      const task = await instantiateTemplate(instantiateId, {
        client_id: instClientId,
        due_date: instDueDate || undefined,
        assigned_to: instAssignTo || undefined,
      });
      setInstSuccess(`Task "${task.title}" created`);
      setTimeout(() => {
        setInstantiateId(null);
        setInstSuccess(null);
      }, 1800);
    } catch (e: unknown) {
      setInstError(e instanceof Error ? e.message : "Failed to create task");
    } finally {
      setInstantiating(false);
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-white/85">Task Templates</h1>
          <p className="text-sm text-white/40 mt-0.5">Reusable templates for recurring work types</p>
        </div>
        <Button onClick={openCreate} size="sm" className="gap-1.5">
          <Plus size={14} /> New Template
        </Button>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-20 text-white/30">
          <Loader2 className="animate-spin mr-2" size={18} /> Loading templates…
        </div>
      ) : templates.length === 0 ? (
        <Card>
          <CardContent className="py-16 text-center text-white/30">
            <CheckSquare size={32} className="mx-auto mb-3 opacity-30" />
            <p className="font-medium">No templates yet</p>
            <p className="text-sm mt-1">Create reusable task templates for common work types</p>
            <Button onClick={openCreate} size="sm" className="mt-4 gap-1.5">
              <Plus size={14} /> Create Template
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {templates.map((t) => (
            <Card key={t.id} className="hover:shadow-md transition-shadow">
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <CardTitle className="text-sm font-semibold text-white/85 truncate">{t.name}</CardTitle>
                    {t.description && (
                      <p className="text-xs text-white/40 mt-1 line-clamp-2">{t.description}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={() => openInstantiate(t.id)}
                      title="Create task from template"
                      className="p-1.5 rounded text-white/30 hover:text-blue-400 hover:bg-blue-500/[0.08] transition-colors"
                    >
                      <Copy size={14} />
                    </button>
                    <button
                      onClick={() => openEdit(t)}
                      className="p-1.5 rounded text-white/30 hover:text-white/65 hover:bg-white/[0.06] transition-colors"
                    >
                      <Edit2 size={14} />
                    </button>
                    {!t.firm_id && (
                      <span title="System template — cannot delete" className="p-1.5 text-gray-200">
                        <Trash2 size={14} />
                      </span>
                    )}
                    {t.firm_id && (
                      <button
                        onClick={() => handleDelete(t.id)}
                        className="p-1.5 rounded text-white/30 hover:text-red-600 hover:bg-red-50 transition-colors"
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                </div>
              </CardHeader>
              <CardContent className="pt-0 space-y-2.5">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge className={`text-[11px] px-2 py-0.5 font-medium ${PRIORITY_COLORS[t.default_priority]}`}>
                    {t.default_priority}
                  </Badge>
                  {t.estimated_hours && (
                    <span className="flex items-center gap-1 text-[11px] text-white/40">
                      <Clock size={11} /> {t.estimated_hours}h est.
                    </span>
                  )}
                  {t.default_assignee_role && (
                    <span className="flex items-center gap-1 text-[11px] text-white/40">
                      <User size={11} /> {t.default_assignee_role}
                    </span>
                  )}
                  {!t.firm_id && (
                    <Badge className="text-[11px] px-2 py-0.5 bg-violet-100 text-violet-700">System</Badge>
                  )}
                </div>
                {t.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {t.tags.map((tag) => (
                      <span key={tag} className="flex items-center gap-0.5 text-[11px] bg-white/[0.06] text-white/55 px-2 py-0.5 rounded-full">
                        <Tag size={9} /> {tag}
                      </span>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Create / Edit dialog */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-[#131620] rounded-xl shadow-2xl w-full max-w-md p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-white/85">{editingId ? "Edit Template" : "New Template"}</h2>
              <button onClick={() => setShowForm(false)} className="text-white/30 hover:text-white/55">
                <X size={18} />
              </button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-white/65 mb-1">Name *</label>
                <input
                  value={form.name}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30"
                  placeholder="e.g. Monthly GST Filing"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-white/65 mb-1">Description</label>
                <textarea
                  value={form.description}
                  onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                  rows={2}
                  className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30 resize-none"
                  placeholder="Brief description of this template"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-white/65 mb-1">Default Priority</label>
                  <select
                    value={form.default_priority}
                    onChange={e => setForm(f => ({ ...f, default_priority: e.target.value }))}
                    className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30"
                  >
                    {["low", "medium", "high", "critical"].map(p => (
                      <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-white/65 mb-1">Est. Hours</label>
                  <input
                    type="number"
                    min="0"
                    value={form.estimated_hours}
                    onChange={e => setForm(f => ({ ...f, estimated_hours: e.target.value }))}
                    className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30"
                    placeholder="e.g. 3"
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-white/65 mb-1">Tags (comma-separated)</label>
                <input
                  value={form.tags}
                  onChange={e => setForm(f => ({ ...f, tags: e.target.value }))}
                  className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30"
                  placeholder="e.g. gst, monthly, filing"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-white/65 mb-1">Default Assignee Role</label>
                <select
                  value={form.default_assignee_role}
                  onChange={e => setForm(f => ({ ...f, default_assignee_role: e.target.value }))}
                  className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30"
                >
                  <option value="">None</option>
                  {ROLE_OPTIONS.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
            </div>

            <div className="flex gap-2 justify-end pt-2">
              <Button variant="outline" size="sm" onClick={() => setShowForm(false)}>Cancel</Button>
              <Button size="sm" onClick={handleSave} disabled={saving || !form.name.trim()}>
                {saving ? <Loader2 className="animate-spin mr-1" size={13} /> : null}
                {editingId ? "Save Changes" : "Create Template"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Instantiate dialog */}
      {instantiateId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-[#131620] rounded-xl shadow-2xl w-full max-w-sm p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-white/85">Create Task from Template</h2>
              <button onClick={() => setInstantiateId(null)} className="text-white/30 hover:text-white/55">
                <X size={18} />
              </button>
            </div>
            {instSuccess ? (
              <div className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-4 py-3 text-center">
                {instSuccess}
              </div>
            ) : (
              <div className="space-y-3">
                <div>
                  <label className="block text-xs font-medium text-white/65 mb-1">Client *</label>
                  <select
                    value={instClientId}
                    onChange={e => setInstClientId(e.target.value)}
                    className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30"
                  >
                    <option value="">Select client…</option>
                    {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-white/65 mb-1">Due Date</label>
                  <input
                    type="date"
                    value={instDueDate}
                    onChange={e => setInstDueDate(e.target.value)}
                    className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30"
                  />
                </div>
                {instError && (
                  <p className="text-xs text-red-600">{instError}</p>
                )}
                <div className="flex gap-2 justify-end pt-1">
                  <Button variant="outline" size="sm" onClick={() => setInstantiateId(null)}>Cancel</Button>
                  <Button size="sm" onClick={handleInstantiate} disabled={instantiating || !instClientId}>
                    {instantiating ? <Loader2 className="animate-spin mr-1" size={13} /> : null}
                    Create Task
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
