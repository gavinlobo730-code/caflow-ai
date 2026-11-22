"use client";

import { ClientLookup } from "@/components/lookups/ClientLookup";
import { useState, useEffect, useCallback } from "react";
import {
  Plus, Trash2, Edit2, CheckSquare, Tag, Clock, User,
  Loader2, Copy,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { DateInput } from "@/components/ui/date-input";
import { useDateProblems } from "@/lib/dates/useDateProblems";
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
import { arrayOrEmpty } from "@/lib/api/shape";
import { Callout } from "@/components/ui/callout";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/states";
import { EmptyStateAction, EmptyStateActions } from "@/components/ui/empty-state-action";
import { SectionPlaceholder } from "@/components/ui/page-frame";

const PRIORITY_COLORS: Record<string, string> = {
  low: "bg-sev-low-surface text-sev-low",
  medium: "bg-sev-medium-surface text-sev-medium",
  high: "bg-sev-high-surface text-sev-high",
  critical: "bg-sev-critical-surface text-sev-critical",
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
  // The due date is optional and a blank one creates the task with none: text that is not a date read as blank, so a task meant to be due
  // on a date was created with no deadline and nothing said (frontend_ux-19).
  const instDates = useDateProblems();
  const [instSuccess, setInstSuccess] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { templates: t } = await listTaskTemplates();
      setTemplates(arrayOrEmpty(t));
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
      tags: (t.tags ?? []).join(", "),
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
    if (!(await confirmDialog({ message: "Delete this template?", danger: true, confirmLabel: "Delete" }))) return;
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
    if (instDates.first) {
      instDates.refuseWith(setInstError);
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
      <PageHeader
        title="Task Templates"
        subtitle="Reusable templates for recurring work types"
        actions={
          <Button onClick={openCreate} size="sm" className="gap-1.5">
            <Plus size={14} /> New Template
          </Button>
        }
      />

      {error && <Callout tone="problem">{error}</Callout>}

      {loading ? (
        <SectionPlaceholder label="Loading templates" shape="cards" rows={6} />
      ) : templates.length === 0 ? (
        <Card>
          <EmptyState
            icon={<CheckSquare size={32} />}
            title="No templates yet"
            description="A template is a reusable task for a common piece of work, so it is set up once and not typed again for every client."
            action={
              <EmptyStateActions>
                <EmptyStateAction requires={["task", "write"]} icon={<Plus size={14} />} label="Create Template"
                  onClick={openCreate} />
              </EmptyStateActions>
            }
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {templates.map((t) => (
            <Card key={t.id} className="hover:shadow-md transition-shadow">
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <CardTitle className="text-sm font-semibold text-ps-ink truncate">{t.name}</CardTitle>
                    {t.description && (
                      <p className="text-xs text-ps-label mt-1 line-clamp-2">{t.description}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={() => openInstantiate(t.id)}
                      title="Create task from template"
                      className="p-1.5 rounded text-ps-hint hover:text-blue-600 hover:bg-blue-50 transition-colors"
                    >
                      <Copy size={14} />
                    </button>
                    <button
                      onClick={() => openEdit(t)}
                      className="p-1.5 rounded text-ps-hint hover:text-ps-body hover:bg-ps-muted transition-colors"
                    >
                      <Edit2 size={14} />
                    </button>
                    {!t.firm_id && (
                      <span title="System template — cannot delete" className="p-1.5 text-gray-200">
                        <Trash2 size={14} />
                      </span>
                    )}
                    {t.firm_id && (
                      <Button variant="plain" size="none"
                        onClick={() => handleDelete(t.id)}
                        className="p-1.5 rounded text-ps-hint hover:text-red-600 hover:bg-state-problem-hover transition-colors"
                      >
                        <Trash2 size={14} />
                      </Button>
                    )}
                  </div>
                </div>
              </CardHeader>
              <CardContent className="pt-0 space-y-2.5">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge className={`text-2xs px-2 py-0.5 font-medium ${PRIORITY_COLORS[t.default_priority]}`}>
                    {t.default_priority}
                  </Badge>
                  {t.estimated_hours && (
                    <span className="flex items-center gap-1 text-2xs text-ps-label">
                      <Clock size={11} /> {t.estimated_hours}h est.
                    </span>
                  )}
                  {t.default_assignee_role && (
                    <span className="flex items-center gap-1 text-2xs text-ps-label">
                      <User size={11} /> {t.default_assignee_role}
                    </span>
                  )}
                  {!t.firm_id && (
                    <Badge className="text-2xs px-2 py-0.5 bg-violet-100 text-violet-700">System</Badge>
                  )}
                </div>
                {(t.tags?.length ?? 0) > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {(t.tags ?? []).map((tag) => (
                      <span key={tag} className="flex items-center gap-0.5 text-2xs bg-ps-muted text-ps-label px-2 py-0.5 rounded-full">
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
        <Modal title={editingId ? "Edit Template" : "New Template"} maxWidthClass="max-w-md" onClose={() => { if (!saving) setShowForm(false); }}>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-ps-body mb-1">Name *</label>
                <input aria-label="Name"
                  value={form.name}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
                  placeholder="e.g. Monthly GST Filing"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-ps-body mb-1">Description</label>
                <textarea aria-label="Description"
                  value={form.description}
                  onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                  rows={2}
                  className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30 resize-none"
                  placeholder="Brief description of this template"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-ps-body mb-1">Default Priority</label>
                  <select aria-label="Default Priority"
                    value={form.default_priority}
                    onChange={e => setForm(f => ({ ...f, default_priority: e.target.value }))}
                    className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
                  >
                    {["low", "medium", "high", "critical"].map(p => (
                      <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-ps-body mb-1">Est. Hours</label>
                  <input aria-label="Est. Hours"
                    type="number"
                    min="0"
                    value={form.estimated_hours}
                    onChange={e => setForm(f => ({ ...f, estimated_hours: e.target.value }))}
                    className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
                    placeholder="e.g. 3"
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-ps-body mb-1">Tags (comma-separated)</label>
                <input aria-label="Tags (comma-separated)"
                  value={form.tags}
                  onChange={e => setForm(f => ({ ...f, tags: e.target.value }))}
                  className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
                  placeholder="e.g. gst, monthly, filing"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-ps-body mb-1">Default Assignee Role</label>
                <select aria-label="Default Assignee Role"
                  value={form.default_assignee_role}
                  onChange={e => setForm(f => ({ ...f, default_assignee_role: e.target.value }))}
                  className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
                >
                  <option value="">None</option>
                  {ROLE_OPTIONS.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
            </div>

            <div className="flex gap-2 justify-end pt-2">
              <Button disabled={saving} variant="outline" size="sm" onClick={() => setShowForm(false)}>Cancel</Button>
              <Button size="sm" onClick={handleSave} disabled={saving || !form.name.trim()}>
                {saving ? <Loader2 className="animate-spin mr-1" size={13} /> : null}
                {editingId ? "Save Changes" : "Create Template"}
              </Button>
            </div>
        </Modal>
      )}

      {/* Instantiate dialog */}
      {instantiateId && (
        <Modal title="Create Task from Template" onClose={() => { if (!instantiating) setInstantiateId(null); }}>
            {instSuccess ? (
              <div className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-4 py-3 text-center">
                {instSuccess}
              </div>
            ) : (
              <div className="space-y-3">
                <div>
                  <label className="block text-xs font-medium text-ps-body mb-1">Client *</label>
                  <ClientLookup ariaLabel="Client"
                    clients={clients}
                    value={instClientId}
                    onChange={setInstClientId}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-ps-body mb-1">Due Date</label>
                  <DateInput
                    aria-label="Due date"
                    value={instDueDate}
                    onChange={setInstDueDate}
                    onStateChange={instDates.watch("due", "Due date")}
                    className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
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
        </Modal>
      )}
    </div>
  );
}
