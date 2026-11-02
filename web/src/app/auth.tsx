// Who is signed in. Boot: refresh from the httpOnly cookie, then GET /me. Login: password → (2FA code | forced 2FA
// setup) → app. The access token stays in memory (src/api/session.ts).
import { createContext, useCallback, useContext, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api, call } from '@/api/client';
import { refreshAccessToken, session } from '@/api/session';
import type { AuthS, Me } from '@/api/types';

type TokenResponse = AuthS['TokenResponse'];

export type AuthStatus = 'booting' | 'anonymous' | 'mfa' | 'setup' | 'ready';

interface AuthState {
  status: AuthStatus;
  me: Me | null;
  mfaToken: string | null;
  /** Backup codes shown once after 2FA is enabled (15d step 3 / 15k). */
  backupCodes: string[] | null;
  sessionExpired: boolean;
  login: (phone: string, password: string) => Promise<void>;
  verify2fa: (input: { code?: string; backup_code?: string }) => Promise<void>;
  completeSetup: (codes: string[] | null) => void;
  acknowledgeBackupCodes: () => void;
  logout: () => Promise<void>;
  reloadMe: () => Promise<Me | null>;
  cancelMfa: () => void;
}

const Ctx = createContext<AuthState | null>(null);
const COOKIE = { headers: { 'X-Refresh-Cookie': '1' } };

async function fetchMe(): Promise<Me> {
  return call(api.auth.GET('/api/auth/v1/me'));
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>('booting');
  const [me, setMe] = useState<Me | null>(null);
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const sessionExpired = useSyncExternalStore(session.subscribe, session.isExpired, () => false);

  const enter = useCallback(async (res?: TokenResponse) => {
    if (res?.access_token) session.set(res.access_token);
    const m = await fetchMe();
    setMe(m);
    setMfaToken(null);
    setStatus(m.mfa_setup_required ? 'setup' : 'ready');
    return m;
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      const ok = await refreshAccessToken();
      if (!alive) return;
      if (!ok) return setStatus('anonymous');
      try {
        await enter();
      } catch {
        session.clear();
        setStatus('anonymous');
      }
    })();
    return () => {
      alive = false;
    };
  }, [enter]);

  const login = useCallback(async (phone: string, password: string) => {
    const res = await call(api.auth.POST('/api/auth/v1/login', { body: { phone, password }, ...COOKIE }));
    if (res.mfa_required && res.mfa_token) {
      setMfaToken(res.mfa_token);
      setStatus('mfa');
      return;
    }
    await enter(res);
  }, [enter]);

  const verify2fa = useCallback(async (input: { code?: string; backup_code?: string }) => {
    if (!mfaToken) throw new Error('no mfa token');
    const res = await call(api.auth.POST('/api/auth/v1/login/2fa', { body: { mfa_token: mfaToken, ...input }, ...COOKIE }));
    await enter(res);
  }, [enter, mfaToken]);

  const completeSetup = useCallback((codes: string[] | null) => {
    setBackupCodes(codes);
    void enter();
  }, [enter]);

  const logout = useCallback(async () => {
    try {
      await call(api.auth.POST('/api/auth/v1/logout', COOKIE));
    } catch {
      /* the session ends anyway */
    }
    session.clear();
    qc.clear();
    setMe(null);
    setMfaToken(null);
    setStatus('anonymous');
  }, [qc]);

  const reloadMe = useCallback(async () => {
    try {
      const m = await fetchMe();
      setMe(m);
      return m;
    } catch {
      return null;
    }
  }, []);

  const value = useMemo<AuthState>(() => ({
    status, me, mfaToken, backupCodes, sessionExpired, login, verify2fa, completeSetup, logout, reloadMe,
    acknowledgeBackupCodes: () => setBackupCodes(null),
    cancelMfa: () => { setMfaToken(null); setStatus('anonymous'); },
  }), [status, me, mfaToken, backupCodes, sessionExpired, login, verify2fa, completeSetup, logout, reloadMe]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const c = useContext(Ctx);
  if (!c) throw new Error('useAuth outside AuthProvider');
  return c;
}

export interface CurrentUser extends Me {
  has: (...anyOf: string[]) => boolean;
  isOwner: boolean;
  menuKeys: Set<string>;
}

export function toCurrentUser(me: Me): CurrentUser {
  const perms = new Set(me.permissions ?? []);
  const all = perms.has('*');
  return {
    ...me,
    isOwner: me.role === 'owner',
    has: (...anyOf: string[]) => all || anyOf.some((p) => perms.has(p)),
    menuKeys: new Set((me.menu ?? []).map((m) => m.key)),
  };
}

/** The signed-in user (only inside the app shell). */
export function useUser(): CurrentUser {
  const { me } = useAuth();
  if (!me) throw new Error('useUser without a user');
  return useMemo(() => toCurrentUser(me), [me]);
}
