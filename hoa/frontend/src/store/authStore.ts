/**
 * Auth store — Zustand
 *
 * Holds: access_token, refresh_token, decoded claims.
 * Provides: login, logout, refresh, switchPersona helpers.
 * Auto-refreshes access token 60s before expiry.
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8001';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface JwtClaims {
  sub: string;
  app_role: 'employee' | 'agent' | 'admin';
  active_dept_role: string;
  shift_exp?: number;
  exp: number;
  iat: number;
}

export interface MeInfo {
  id: string;
  email: string;
  name: string;
  app_role: 'employee' | 'agent' | 'admin';
  active_dept_role: string;
  dept_roles: string[];
}

interface AuthState {
  access_token: string | null;
  refresh_token: string | null;
  claims: JwtClaims | null;
  me: MeInfo | null;

  // Actions
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<boolean>;
  switchPersona: (dept_role: string) => Promise<void>;
  fetchMe: () => Promise<void>;
  authFetch: (path: string, options?: RequestInit) => Promise<Response>;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function parseJwt(token: string): JwtClaims {
  const b64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
  return JSON.parse(atob(b64)) as JwtClaims;
}

async function apiFetch(
  path: string,
  options: RequestInit & { token?: string } = {}
): Promise<Response> {
  const { token, ...rest } = options;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(rest.headers as Record<string, string>),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return fetch(`${API}${path}`, { ...rest, headers });
}

// ── Store ─────────────────────────────────────────────────────────────────────

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      access_token: null,
      refresh_token: null,
      claims: null,
      me: null,

      login: async (email, password) => {
        const res = await apiFetch('/auth/login', {
          method: 'POST',
          body: JSON.stringify({ email, password }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail ?? 'Login failed');
        }
        const data: { access_token: string; refresh_token: string } = await res.json();
        const claims = parseJwt(data.access_token);
        set({ access_token: data.access_token, refresh_token: data.refresh_token, claims });
        scheduleRefresh(claims.exp);
        // Fetch full me info
        await get().fetchMe();
      },

      logout: () => {
        clearRefreshTimer();
        set({ access_token: null, refresh_token: null, claims: null, me: null });
      },

      refresh: async () => {
        const { refresh_token } = get();
        if (!refresh_token) return false;
        try {
          const res = await apiFetch('/auth/refresh', {
            method: 'POST',
            body: JSON.stringify({ refresh_token }),
          });
          if (!res.ok) {
            get().logout();
            return false;
          }
          const data: { access_token: string; refresh_token: string } = await res.json();
          const claims = parseJwt(data.access_token);
          set({ access_token: data.access_token, refresh_token: data.refresh_token, claims });
          scheduleRefresh(claims.exp);
          return true;
        } catch {
          get().logout();
          return false;
        }
      },

      switchPersona: async (dept_role) => {
        const { access_token } = get();
        if (!access_token) throw new Error('Not authenticated');
        const res = await apiFetch('/auth/persona', {
          method: 'POST',
          token: access_token,
          body: JSON.stringify({ dept_role }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail ?? 'Persona switch failed');
        }
        const data: { access_token: string; refresh_token: string } = await res.json();
        const claims = parseJwt(data.access_token);
        set({ access_token: data.access_token, refresh_token: data.refresh_token, claims });
        scheduleRefresh(claims.exp);
        await get().fetchMe();
      },

      fetchMe: async () => {
        const { access_token } = get();
        if (!access_token) return;
        const res = await apiFetch('/auth/me', { token: access_token });
        if (!res.ok) return;
        const me: MeInfo = await res.json();
        set({ me });
      },

      authFetch: async (path: string, options: RequestInit = {}) => {
        const { access_token } = get();
        if (!access_token) throw new Error('Not authenticated');
        return apiFetch(path, { ...options, token: access_token });
      },
    }),
    {
      name: 'hoa-auth',
      storage: createJSONStorage(() => localStorage),
      // Don't persist the timer-related state
      partialize: (s) => ({
        access_token: s.access_token,
        refresh_token: s.refresh_token,
        claims: s.claims,
        me: s.me,
      }),
    }
  )
);

// ── Auto-refresh timer ────────────────────────────────────────────────────────

let _refreshTimer: ReturnType<typeof setTimeout> | null = null;

function clearRefreshTimer() {
  if (_refreshTimer !== null) {
    clearTimeout(_refreshTimer);
    _refreshTimer = null;
  }
}

function scheduleRefresh(exp: number) {
  clearRefreshTimer();
  const msUntilRefresh = (exp * 1000) - Date.now() - 60_000; // 60s before expiry
  if (msUntilRefresh <= 0) {
    useAuthStore.getState().refresh();
    return;
  }
  _refreshTimer = setTimeout(() => {
    useAuthStore.getState().refresh();
  }, msUntilRefresh);
}

// Kick off auto-refresh on store hydration (if token already exists)
const { access_token, claims } = useAuthStore.getState();
if (access_token && claims) {
  scheduleRefresh(claims.exp);
}

// ── Permission helpers (client-side gating, server always re-checks) ──────────

const PERM_MAP: Record<string, string[]> = {
  'chat:use':        ['employee', 'agent', 'admin'],
  'feedback:write':  ['employee', 'agent', 'admin'],
  'tickets:read':    ['agent', 'admin'],
  'tickets:update':  ['agent', 'admin'],
  'analytics:read':  ['admin'],
  'audit:read':      ['admin'],
  'audit:verify':    ['admin'],
  'knowledge:read':  ['admin'],
  'knowledge:write': ['admin'],
  'users:manage':    ['admin'],
  'system:manage':   ['admin'],
};

export function hasPerm(claims: JwtClaims | null, perm: string): boolean {
  if (!claims) return false;
  return (PERM_MAP[perm] ?? []).includes(claims.app_role);
}

export function canAccessAdmin(claims: JwtClaims | null): boolean {
  return claims?.app_role === 'agent' || claims?.app_role === 'admin';
}
