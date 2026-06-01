
import { Building2, Users, Bell, Clock } from "lucide-react";

const FIRM_FIELDS = [
  { label: "Firm Name", value: "Gavin Lobo & Associates", type: "text" },
  { label: "Membership Number", value: "ICAI-MRN-123456", type: "text" },
  { label: "PAN", value: "ABCGL1234D", type: "text" },
  { label: "GSTIN", value: "27ABCGL1234D1ZB", type: "text" },
  { label: "Email", value: "gavin@caflow.in", type: "email" },
  { label: "Phone", value: "+91 98765 43210", type: "tel" },
  { label: "Address", value: "12, MG Road, Mumbai — 400001", type: "text" },
];

const NOTIFICATION_TOGGLES = [
  { label: "Email notifications for overdue tasks", enabled: true },
  { label: "WhatsApp reminders to clients", enabled: true },
  { label: "System alerts for filing deadlines", enabled: true },
  { label: "Weekly compliance digest", enabled: false },
  { label: "AI insight notifications", enabled: true },
];

const REMINDER_TOGGLES = [
  { label: "Send GSTR-1 reminder 3 days before due", enabled: true },
  { label: "Send GSTR-3B reminder 5 days before due", enabled: true },
  { label: "Send ITR reminder 15 days before due", enabled: true },
  { label: "Send overdue notice immediately", enabled: true },
];

function ToggleList({ toggles }: { toggles: { label: string; enabled: boolean }[] }) {
  return (
    <div className="space-y-3">
      {toggles.map((t) => (
        <div key={t.label} className="flex items-center justify-between">
          <p className="text-sm text-gray-700">{t.label}</p>
          <div className={`w-9 h-5 rounded-full relative ${t.enabled ? "bg-blue-600" : "bg-gray-200"}`}>
            <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-sm ${t.enabled ? "translate-x-4" : "translate-x-0.5"}`} />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function SettingsPage() {
  return (
    <div className="p-6 max-w-3xl mx-auto space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Settings</h1>
        <p className="text-sm text-gray-500 mt-0.5">Firm configuration and preferences</p>
      </div>

      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
          <Building2 size={15} className="text-gray-500" />
          <h2 className="text-sm font-semibold text-gray-900">Firm Profile</h2>
        </div>
        <div className="px-5 py-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {FIRM_FIELDS.map((f) => (
              <div key={f.label}>
                <label className="text-xs font-medium text-gray-500 block mb-1">{f.label}</label>
                <input
                  type={f.type}
                  defaultValue={f.value}
                  className="w-full text-sm text-gray-900 border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-gray-50"
                />
              </div>
            ))}
          </div>
        </div>
        <div className="px-5 py-3 border-t border-gray-50 flex justify-end">
          <button className="px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors">
            Save Changes
          </button>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
          <Users size={15} className="text-gray-500" />
          <h2 className="text-sm font-semibold text-gray-900">Users &amp; Roles</h2>
        </div>
        <div className="px-5 py-4">
          <div className="flex items-center gap-4 py-2">
            <div className="w-8 h-8 rounded-full bg-blue-600 text-white text-xs font-semibold flex items-center justify-center shrink-0">
              GL
            </div>
            <div className="flex-1">
              <p className="text-sm font-medium text-gray-900">Gavin Lobo</p>
              <p className="text-xs text-gray-400">gavin@caflow.in</p>
            </div>
            <span className="text-xs px-2.5 py-1 bg-blue-50 text-blue-700 rounded-full font-medium">Partner</span>
          </div>
          <p className="text-xs text-gray-400 mt-3">Available roles: Partner · Manager · Executive · Reviewer</p>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
          <Bell size={15} className="text-gray-500" />
          <h2 className="text-sm font-semibold text-gray-900">Notification Preferences</h2>
        </div>
        <div className="px-5 py-4">
          <ToggleList toggles={NOTIFICATION_TOGGLES} />
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
          <Clock size={15} className="text-gray-500" />
          <h2 className="text-sm font-semibold text-gray-900">Reminder Preferences</h2>
        </div>
        <div className="px-5 py-4">
          <ToggleList toggles={REMINDER_TOGGLES} />
        </div>
      </div>
    </div>
  );
}
