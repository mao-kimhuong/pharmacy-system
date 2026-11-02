// The access token lives in memory only. The refresh token is an httpOnly cookie (pharmacy_refresh, path
// /api/auth/v1/refresh) that the auth service sets when the request carries X-Refresh-Cookie: 1.
type Listener = () => void;

let accessToken: string | null = null;
let expired = false;
const listeners = new Set<Listener>();
const emit = () => listeners.forEach((l) => l());

export const session = {
  token: () => accessToken,
  isExpired: () => expired,
  set(token: string | null) {
    accessToken = token;
    expired = false;
    emit();
  },
  /** The refresh failed while the app was in use: the shell shows "session expired" (16h). */
  expire() {
    accessToken = null;
    expired = true;
    emit();
  },
  clear() {
    accessToken = null;
    expired = false;
    emit();
  },
  subscribe(l: Listener) {
    listeners.add(l);
    return () => void listeners.delete(l);
  },
};

export const REFRESH_URL = '/api/auth/v1/refresh';

let inflight: Promise<boolean> | null = null;

/** One refresh at a time; every 401 waits for the same one. */
export function refreshAccessToken(): Promise<boolean> {
  inflight ??= (async () => {
    try {
      const res = await fetch(REFRESH_URL, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-Refresh-Cookie': '1' },
      });
      if (!res.ok) return false;
      const body = (await res.json()) as { access_token?: string | null };
      if (!body.access_token) return false;
      accessToken = body.access_token;
      expired = false;
      emit();
      return true;
    } catch {
      return false;
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}
