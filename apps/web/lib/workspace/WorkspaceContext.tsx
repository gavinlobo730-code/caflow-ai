"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useReducer,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  type WorkspaceId,
  DEFAULT_WORKSPACE_ROUTES,
  getWorkspaceForPathname,
} from "./workspaceConfig";

export interface WorkspaceContextValue {
  activeWorkspace: WorkspaceId;
  lastRoute: Record<WorkspaceId, string>;
  setWorkspace: (id: WorkspaceId) => void;
  updateLastRoute: (workspaceId: WorkspaceId, route: string) => void;
}

interface WorkspaceState {
  activeWorkspace: WorkspaceId;
  lastRoute: Record<WorkspaceId, string>;
}

type WorkspaceAction =
  | { type: "SET_WORKSPACE"; id: WorkspaceId }
  | { type: "UPDATE_LAST_ROUTE"; workspaceId: WorkspaceId; route: string }
  | { type: "HYDRATE"; state: WorkspaceState };

const STORAGE_KEY = "practicesync_workspace_v1";

function reducer(
  state: WorkspaceState,
  action: WorkspaceAction
): WorkspaceState {
  switch (action.type) {
    case "SET_WORKSPACE":
      return { ...state, activeWorkspace: action.id };
    case "UPDATE_LAST_ROUTE":
      return {
        ...state,
        lastRoute: {
          ...state.lastRoute,
          [action.workspaceId]: action.route,
        },
      };
    case "HYDRATE":
      return action.state;
    default:
      return state;
  }
}

function getInitialState(pathname: string): WorkspaceState {
  return {
    activeWorkspace: getWorkspaceForPathname(pathname),
    lastRoute: { ...DEFAULT_WORKSPACE_ROUTES },
  };
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  const [state, dispatch] = useReducer(reducer, pathname, getInitialState);

  // Hydrate from localStorage on mount
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as WorkspaceState;
        dispatch({
          type: "HYDRATE",
          state: {
            activeWorkspace:
              parsed.activeWorkspace ?? getWorkspaceForPathname(pathname),
            lastRoute: {
              ...DEFAULT_WORKSPACE_ROUTES,
              ...parsed.lastRoute,
            },
          },
        });
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

  // Sync active workspace and lastRoute whenever pathname changes
  useEffect(() => {
    const ws = getWorkspaceForPathname(pathname);
    dispatch({ type: "SET_WORKSPACE", id: ws });
    dispatch({ type: "UPDATE_LAST_ROUTE", workspaceId: ws, route: pathname });
  }, [pathname]);

  const setWorkspace = useCallback(
    (id: WorkspaceId) => {
      dispatch({ type: "SET_WORKSPACE", id });
      const target =
        state.lastRoute[id] ?? DEFAULT_WORKSPACE_ROUTES[id];
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
    activeWorkspace: state.activeWorkspace,
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
