"use client";

import { Monitor } from "lucide-react";
import type { LiveDevice } from "@/lib/api/index";
import { formatDateTime } from "@/lib/dates/format";

/**
 * The devices a login is signed in on now (POST-A-486), one row each: the browser in words, the address our own proxy saw, when the
 * server last heard from it. Everything is the server's: the browser's name is made there, and "this device" is its answer, not a
 * comparison made here. Nothing is shown for a place: an address is not turned into a town (that would send the address to a
 * third party), and the screen does not pretend to.
 */
export function DeviceList({ devices }: { devices: LiveDevice[] }) {
  return (
    <ul className="divide-y divide-ps-border" data-device-list="">
      {devices.map((d) => (
        <li key={d.id} className="flex items-center justify-between gap-3 py-2 text-sm">
          <span className="flex min-w-0 items-center gap-2 text-ps-body">
            <Monitor size={14} className="shrink-0 text-ps-label" aria-hidden />
            <span className="truncate">
              {d.browser}
              {d.address ? <span className="text-ps-label"> · address {d.address}</span> : <span className="text-ps-label"> · no address recorded</span>}
            </span>
            {d.is_current === true ? (
              <span className="shrink-0 rounded-full bg-state-ready-surface px-2 py-0.5 text-xs font-medium text-state-ready">This device</span>
            ) : null}
          </span>
          <span className="shrink-0 text-xs text-ps-label">
            {d.last_seen_at ? `last active ${formatDateTime(d.last_seen_at, "")}` : "last active time unknown"}
          </span>
        </li>
      ))}
    </ul>
  );
}
