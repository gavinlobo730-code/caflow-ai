"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import { ChevronLeft, Palette, Image, Globe, Save, Upload, Eye } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";
import { RoleGuard } from "@/components/RoleGuard";
import { api, type ApiResp } from "@/lib/api/index";

// ── Types ──────────────────────────────────────────────────────────────────
interface Branding {
  id?: string;
  logo_url?: string | null;
  secondary_logo_url?: string | null;
  tagline?: string | null;
  primary_color: string;
  secondary_color: string;
  accent_color: string;
  font_family: string;
  social_links?: Record<string, string>;
}

const FONTS = ["Inter", "Roboto", "Poppins", "Lato", "Montserrat", "Open Sans", "Nunito"];

const DEFAULT_BRANDING: Branding = {
  logo_url: null,
  secondary_logo_url: null,
  tagline: "",
  primary_color: "#2563EB",
  secondary_color: "#1E40AF",
  accent_color: "#3B82F6",
  font_family: "Inter",
  social_links: {},
};

// ── Toast ──────────────────────────────────────────────────────────────────
function Toast({ message, type, onClose }: { message: string; type: "success" | "error"; onClose: () => void }) {
  useEffect(() => {
    const t = setTimeout(onClose, 4000);
    return () => clearTimeout(t);
  }, [onClose]);
  return (
    <div className={`fixed bottom-6 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-xl shadow-lg text-sm font-medium ${
      type === "success" ? "bg-green-600 text-white" : "bg-red-600 text-white"
    }`}>
      <span>{message}</span>
      <button onClick={onClose} className="opacity-70 hover:opacity-100 text-lg leading-none">×</button>
    </div>
  );
}

// ── Color Swatch Input ─────────────────────────────────────────────────────
function ColorInput({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="text-xs font-medium text-[#64748B] block mb-1">{label}</label>
      <div className="flex items-center gap-2">
        <div className="relative">
          <div className="w-8 h-8 rounded-lg border border-[#E2E8F0] overflow-hidden cursor-pointer">
            <input
              type="color"
              value={value}
              onChange={(e) => onChange(e.target.value.toUpperCase())}
              className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
            />
            <div className="w-full h-full" style={{ backgroundColor: value }} />
          </div>
        </div>
        <input
          type="text"
          value={value}
          onChange={(e) => {
            const v = e.target.value.toUpperCase();
            if (/^#[0-9A-F]{0,6}$/.test(v)) onChange(v);
          }}
          maxLength={7}
          placeholder="#000000"
          className="w-28 text-sm font-mono text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC]"
        />
      </div>
    </div>
  );
}

// ── Live Preview ───────────────────────────────────────────────────────────
function BrandingPreview({ branding, firmName }: { branding: Branding; firmName: string }) {
  return (
    <div className="rounded-xl border border-[#E2E8F0] overflow-hidden shadow-sm">
      {/* Header bar */}
      <div className="px-5 py-3 flex items-center justify-between" style={{ backgroundColor: branding.primary_color }}>
        {branding.logo_url ? (
          <img src={branding.logo_url} alt="Logo" className="h-8 object-contain" />
        ) : (
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-white/20 flex items-center justify-center">
              <span className="text-white font-bold text-sm">{firmName?.[0] ?? "F"}</span>
            </div>
            <span className="text-white font-semibold text-sm" style={{ fontFamily: branding.font_family }}>
              {firmName || "Your Firm Name"}
            </span>
          </div>
        )}
        <span className="text-white/70 text-xs" style={{ fontFamily: branding.font_family }}>
          {branding.tagline || "Chartered Accountants"}
        </span>
      </div>

      {/* Sample invoice body */}
      <div className="bg-white px-5 py-4 space-y-3">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs text-[#94A3B8] uppercase tracking-wide mb-0.5">Invoice To</p>
            <p className="text-sm font-medium text-[#0F172A]" style={{ fontFamily: branding.font_family }}>Sample Client Pvt. Ltd.</p>
            <p className="text-xs text-[#64748B]">123 Business Park, Mumbai</p>
          </div>
          <div className="text-right">
            <p className="text-xs text-[#94A3B8] mb-0.5">Invoice #</p>
            <p className="text-sm font-bold" style={{ color: branding.primary_color, fontFamily: branding.font_family }}>INV-2025-001</p>
          </div>
        </div>

        <div className="border-t border-[#E2E8F0] pt-3">
          <div className="flex justify-between text-xs text-[#64748B] mb-2">
            <span>Professional Services — FY 2025-26</span>
            <span className="font-medium text-[#0F172A]">₹50,000.00</span>
          </div>
          <div className="flex justify-between text-xs text-[#64748B]">
            <span>GST @ 18%</span>
            <span className="font-medium text-[#0F172A]">₹9,000.00</span>
          </div>
        </div>

        <div className="flex justify-between items-center border-t border-[#E2E8F0] pt-3">
          <span className="text-sm font-semibold text-[#0F172A]">Total Due</span>
          <span className="text-base font-bold" style={{ color: branding.accent_color, fontFamily: branding.font_family }}>₹59,000.00</span>
        </div>

        {/* Accent bar */}
        <div className="rounded-lg px-3 py-2 text-xs text-white" style={{ backgroundColor: branding.secondary_color, fontFamily: branding.font_family }}>
          Thank you for your business. Payment due within 15 days.
        </div>
      </div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────
export default function BrandingPage() {
  const { user } = useAuth();
  const [branding, setBranding] = useState<Branding>(DEFAULT_BRANDING);
  const firmName = "";
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const showToast = (message: string, type: "success" | "error") => setToast({ message, type });

  const load = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const res = await api.branding.get() as ApiResp<{ branding: Branding }>;
      if (res.success && res.data.branding && Object.keys(res.data.branding).length > 0) {
        setBranding({ ...DEFAULT_BRANDING, ...res.data.branding });
      }
      setLoadError(null);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to load branding settings";
      showToast(msg, "error");
      setLoadError(msg);
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => { load(); }, [load]);

  async function handleSave() {
    setSaving(true);
    try {
      await api.branding.update({
        logo_url: branding.logo_url || null,
        secondary_logo_url: branding.secondary_logo_url || null,
        tagline: branding.tagline || null,
        primary_color: branding.primary_color,
        secondary_color: branding.secondary_color,
        accent_color: branding.accent_color,
        font_family: branding.font_family,
        social_links: branding.social_links || {},
      });
      showToast("Branding saved successfully", "success");
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Failed to save", "error");
    } finally {
      setSaving(false);
    }
  }

  async function handleLogoUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const res = await api.branding.uploadLogo(file) as ApiResp<{ logo_url: string }>;
      if (res.success) {
        setBranding((b) => ({ ...b, logo_url: res.data.logo_url }));
        showToast("Logo uploaded", "success");
      }
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Upload failed", "error");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  function update(field: keyof Branding, value: unknown) {
    setBranding((b) => ({ ...b, [field]: value }));
  }

  return (
    <RoleGuard allowed={["Partner"]}>
      <div className="p-6 max-w-5xl mx-auto space-y-5">
        {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}

        <div>
          <Link href="/settings" className="inline-flex items-center gap-1 text-xs text-[#94A3B8] hover:text-[#475569] transition-colors mb-1">
            <ChevronLeft size={13} /> Settings
          </Link>
          <h1 className="text-xl font-semibold text-[#0F172A]">Firm Branding</h1>
          <p className="text-sm text-[#64748B] mt-0.5">Customize your firm&apos;s visual identity across all documents and client communications.</p>
        </div>

        {loadError && !loading && (
          <div className="flex items-center justify-between gap-3 bg-red-50 border border-red-100 rounded-xl px-4 py-3">
            <p className="text-xs text-red-700">
              Couldn&apos;t load your saved branding — showing defaults. {loadError}
            </p>
            <button onClick={load} className="text-xs px-3 py-1.5 border border-red-200 rounded-lg hover:bg-red-100 text-red-700 shrink-0">
              Retry
            </button>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {/* ── Left: Settings ───────────────────────────────────────────── */}
          <div className="space-y-4">

            {/* Logo */}
            <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
              <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
                <Image size={15} className="text-[#64748B]" />
                <h2 className="text-sm font-semibold text-[#0F172A]">Logo</h2>
              </div>
              <div className="px-5 py-4 space-y-3">
                {branding.logo_url && (
                  <div className="flex items-center gap-3 p-3 bg-[#F8FAFC] rounded-lg border border-[#E2E8F0]">
                    <img src={branding.logo_url} alt="Logo" className="h-10 object-contain" />
                    <button
                      onClick={() => update("logo_url", null)}
                      className="text-xs text-red-500 hover:text-red-700"
                    >
                      Remove
                    </button>
                  </div>
                )}
                <div className="flex gap-2">
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    disabled={uploading}
                    className="flex items-center gap-1.5 px-3 py-1.5 border border-[#E2E8F0] text-[#475569] text-xs font-medium rounded-lg hover:bg-[#F8FAFC] disabled:opacity-50"
                  >
                    <Upload size={13} />
                    {uploading ? "Uploading…" : "Upload Logo"}
                  </button>
                  <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleLogoUpload} />
                </div>
                <div>
                  <label className="text-xs font-medium text-[#64748B] block mb-1">Or paste a URL</label>
                  <input
                    type="url"
                    value={branding.logo_url ?? ""}
                    onChange={(e) => update("logo_url", e.target.value || null)}
                    placeholder="https://example.com/logo.png"
                    className="w-full text-sm text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC]"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-[#64748B] block mb-1">Tagline</label>
                  <input
                    type="text"
                    value={branding.tagline ?? ""}
                    onChange={(e) => update("tagline", e.target.value)}
                    placeholder="e.g. Chartered Accountants & Advisors"
                    className="w-full text-sm text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC]"
                  />
                </div>
              </div>
            </div>

            {/* Colors */}
            <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
              <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
                <Palette size={15} className="text-[#64748B]" />
                <h2 className="text-sm font-semibold text-[#0F172A]">Brand Colors</h2>
              </div>
              <div className="px-5 py-4 grid grid-cols-1 sm:grid-cols-3 gap-4">
                <ColorInput label="Primary Color" value={branding.primary_color} onChange={(v) => update("primary_color", v)} />
                <ColorInput label="Secondary Color" value={branding.secondary_color} onChange={(v) => update("secondary_color", v)} />
                <ColorInput label="Accent Color" value={branding.accent_color} onChange={(v) => update("accent_color", v)} />
              </div>
              <div className="px-5 pb-4">
                <label className="text-xs font-medium text-[#64748B] block mb-1">Font Family</label>
                <select
                  value={branding.font_family}
                  onChange={(e) => update("font_family", e.target.value)}
                  className="w-full text-sm text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC]"
                >
                  {FONTS.map((f) => (
                    <option key={f} value={f} style={{ fontFamily: f }}>{f}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* Social Links */}
            <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
              <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
                <Globe size={15} className="text-[#64748B]" />
                <h2 className="text-sm font-semibold text-[#0F172A]">Social Links</h2>
              </div>
              <div className="px-5 py-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
                {(["linkedin", "twitter", "facebook", "instagram"] as const).map((platform) => (
                  <div key={platform}>
                    <label className="text-xs font-medium text-[#64748B] block mb-1 capitalize">{platform}</label>
                    <input
                      type="url"
                      value={(branding.social_links ?? {})[platform] ?? ""}
                      onChange={(e) =>
                        update("social_links", { ...(branding.social_links ?? {}), [platform]: e.target.value || undefined })
                      }
                      placeholder={`https://${platform}.com/yourfirm`}
                      className="w-full text-sm text-[#0F172A] border border-[#E2E8F0] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-[#F8FAFC]"
                    />
                  </div>
                ))}
              </div>
            </div>

            <div className="flex justify-end">
              <button
                onClick={handleSave}
                disabled={saving || loading}
                className="flex items-center gap-2 px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
              >
                <Save size={14} />
                {saving ? "Saving…" : "Save Branding"}
              </button>
            </div>
          </div>

          {/* ── Right: Live Preview ─────────────────────────────────────── */}
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm font-medium text-[#475569]">
              <Eye size={14} />
              Live Preview
            </div>
            <BrandingPreview branding={branding} firmName={firmName || "Your Firm"} />
            <p className="text-xs text-[#94A3B8] text-center">Preview of how your branding appears on invoices and client documents.</p>
          </div>
        </div>
      </div>
    </RoleGuard>
  );
}
