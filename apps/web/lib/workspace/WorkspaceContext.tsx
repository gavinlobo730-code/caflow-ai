"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  type WorkspaceId,
  DEFAULT_WORKSPACE_ROUTES,
  WORKSPACE_CONFIGS,
  getActiveWorkspaceForPathname,
} from "./workspaceConfig";
import { matchesKnownRoute } from "./routeManifest";
import { KNOWN_ROUTE_SHAPES } from "./knownRoutes.generated";

export interface WorkspaceContextValue {
  /**
   * The workspace whose rail icon should be lit right now — derived fresh
   * from the current pathname on every render, never stored. null on routes
   * no workspace owns (/settings, /platform, /search, or anything
   * unmapped). Consumers that need to render *something* regardless (e.g.
   * ContextPanel choosing a panel) apply their own "home" fallback; this
   * value itself must never be coerced to "home".
   */
  activeWorkspace: WorkspaceId | null;
  lastRoute: Record<WorkspaceId, string>;
  setWorkspace: (id: WorkspaceId) => void;
  updateLastRoute: (workspaceId: WorkspaceId, route: string) => void;
}

interface WorkspaceState {
  lastRoute: Record<WorkspaceId, string>;
}

type WorkspaceAction =
  | { type: "UPDATE_LAST_ROUTE"; workspaceId: WorkspaceId; route: string }
  | { type: "HYDRATE"; state: WorkspaceState };

// v2 — v1 could hold routes to pages deleted since it was written (e.g. the
// retired /accounting/chart-of-accounts), which sanitizeLastRoute below now
// guards against going forward, but existing v1 values were never validated
// on write. A version bump is the clean one-time fix for whatever's already
// in a returning user's browser; v2 is validated on every hydrate from here on.
const STORAGE_KEY = "practicesync_workspace_v2";

const KNOWN_WORKSPACE_IDS = new Set(WORKSPACE_CONFIGS.map((w) => w.id));

/**
 * A persisted route is only trusted if BOTH:
 *  - it still maps back to the SAME workspace under the current routing
 *    rules (catches a route reassigned to a different workspace), and
 *  - it's still a real page (catches a route deleted from WITHIN a
 *    workspace whose other pages are still live — e.g.
 *    /accounting/chart-of-accounts still starts with "/accounting", a
 *    workspace that's very much still alive, even though that exact page
 *    was retired; the same-workspace check alone would let it through).
 * Anything that fails either check (also: unknown workspace id, malformed
 * value) falls back to that workspace's own DEFAULT_WORKSPACE_ROUTES entry,
 * so the app can never navigate a user to a dead page because of stale
 * localStorage.
 */
function sanitizeLastRoute(raw: unknown): Record<WorkspaceId, string> {
  const out: Record<WorkspaceId, string> = { ...DEFAULT_WORKSPACE_ROUTES };
  if (!raw || typeof raw !== "object") return out;
  for (const [key, route] of Object.entries(raw as Record<string, unknown>)) {
    if (!KNOWN_WORKSPACE_IDS.has(key as WorkspaceId)) continue;
    if (typeof route !== "string" || !route.startsWith("/")) continue;
    if (getActiveWorkspaceForPathname(route) !== key) continue;
    if (!matchesKnownRoute(route, KNOWN_ROUTE_SHAPES)) continue;
    out[key as WorkspaceId] = route;
  }
  return out;
}

function getInitialState(): WorkspaceState {
  return { lastRoute: { ...DEFAULT_WORKSPACE_ROUTES } };
}

function reducer(state: WorkspaceState, action: WorkspaceAction): WorkspaceState {
  switch (action.type) {
    case "UPDATE_LAST_ROUTE":
      return {
        ...state,
        lastRoute: { ...state.lastRoute, [action.workspaceId]: action.route },
      };
    case "HYDRATE":
      return action.state;
    default:
      return state;
  }
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  const [state, dispatch] = useReducer(reducer, undefined, getInitialState);

  // Hydrate from localStorage on mount, validating every persisted route.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as { lastRoute?: unknown };
        dispatch({ type: "HYDRATE", state: { lastRoute: sanitizeLastRoute(parsed.lastRoute) } });
      }
    } catch {
      // ignore malformed storage
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist to localStorage on state change
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      // ignore storage errors
    }
  }, [state]);

  // Record lastRoute whenever pathname changes — only for routes a workspace
  // actually owns. getActiveWorkspaceForPathname returning null (/settings,
  // /platform, /search, unmapped) must never pollute any workspace's
  // lastRoute; previously this fell through to "home", so visiting e.g.
  // /copilot before it was mapped would silently overwrite Home's
  // remembered route.
  useEffect(() => {
    const ws = getActiveWorkspaceForPathname(pathname);
    if (ws) dispatch({ type: "UPDATE_LAST_ROUTE", workspaceId: ws, route: pathname });
  }, [pathname]);

  // The rail highlight is derived fresh from the pathname on every render —
  // never stored — so it can never go stale independently of the URL. This
  // is what fixes Settings (and every other unmapped route) incorrectly
  // keeping Home lit: there is no persisted "previous" workspace to fall
  // back to anymore.
  const activeWorkspace = useMemo(() => getActiveWorkspaceForPathname(pathname), [pathname]);

  const setWorkspace = useCallback(
    (id: WorkspaceId) => {
      // Clicking "Clients" always opens the client list.
      const target =
        id === "clients"
          ? DEFAULT_WORKSPACE_ROUTES.clients
          : state.lastRoute[id] ?? DEFAULT_WORKSPACE_ROUTES[id];
      router.push(target);
    },
    [state.lastRoute, router]
  );

  const updateLastRoute = useCallback(
    (workspaceId: WorkspaceId, route: string) => {
      dispatch({ type: "UPDATE_LAST_ROUTE", workspaceId, route });
    },
    []
  );

  const value: WorkspaceContextValue = {
    activeWorkspace,
    lastRoute: state.lastRoute,
    setWorkspace,
    updateLastRoute,
  };

  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) {
    throw new Error("useWorkspace must be used within WorkspaceProvider");
  }
  return ctx;
}
