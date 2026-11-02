// One typed client per service (openapi-fetch over the generated types). Pages use only these.
// The middleware adds the bearer token, an Idempotency-Key where the API takes one (unless the caller passed
// its own to retry the same action), and one refresh + retry on 401.
import createClient, { type Client, type Middleware } from 'openapi-fetch';
import type { paths as AuthPaths } from './gen/auth';
import type { paths as BranchPaths } from './gen/branch';
import type { paths as CatalogPaths } from './gen/catalog';
import type { paths as ControlledPaths } from './gen/controlled';
import type { paths as CustomersPaths } from './gen/customers';
import type { paths as DocumentsPaths } from './gen/documents';
import type { paths as InventoryPaths } from './gen/inventory';
import type { paths as NotificationsPaths } from './gen/notifications';
import type { paths as PrescriptionPaths } from './gen/prescription';
import type { paths as PurchasingPaths } from './gen/purchasing';
import type { paths as ReportsPaths } from './gen/reports';
import type { paths as SalesPaths } from './gen/sales';
import type { paths as StockcountPaths } from './gen/stockcount';
import { IDEMPOTENT } from './gen/idempotent';
import { ApiError } from './errors';
import { refreshAccessToken, session } from './session';

const NO_REFRESH = ['/api/auth/v1/login', '/api/auth/v1/refresh', '/api/auth/v1/logout'];
const retries = new Map<string, Request>();

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

export const middleware: Middleware = {
  onRequest({ request, schemaPath, id }) {
    const token = session.token();
    if (token && !request.headers.has('Authorization')) request.headers.set('Authorization', `Bearer ${token}`);
    if (IDEMPOTENT.has(`${request.method} ${schemaPath}`) && !request.headers.has('Idempotency-Key')) {
      request.headers.set('Idempotency-Key', newIdempotencyKey());
    }
    if (!NO_REFRESH.some((p) => request.url.includes(p))) retries.set(id, request.clone());
    return request;
  },
  async onResponse({ response, id }) {
    const copy = retries.get(id);
    retries.delete(id);
    if (response.status !== 401 || !copy) return response;
    if (await refreshAccessToken()) {
      copy.headers.set('Authorization', `Bearer ${session.token()}`);
      return fetch(copy);
    }
    session.expire();
    return response;
  },
  onError({ id }) {
    retries.delete(id);
  },
};

const baseUrl = typeof window !== 'undefined' ? window.location.origin : 'http://localhost';

function make<P extends object>(): Client<P> {
  // Resolve fetch at call time (tests replace it).
  const c = createClient<P>({ baseUrl, credentials: 'same-origin', fetch: (r: Request) => globalThis.fetch(r) });
  c.use(middleware);
  return c;
}

export const api = {
  auth: make<AuthPaths>(),
  branch: make<BranchPaths>(),
  catalog: make<CatalogPaths>(),
  inventory: make<InventoryPaths>(),
  stockcount: make<StockcountPaths>(),
  prescription: make<PrescriptionPaths>(),
  controlled: make<ControlledPaths>(),
  sales: make<SalesPaths>(),
  customers: make<CustomersPaths>(),
  purchasing: make<PurchasingPaths>(),
  reports: make<ReportsPaths>(),
  notifications: make<NotificationsPaths>(),
  documents: make<DocumentsPaths>(),
};

interface FetchResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/** Awaits an openapi-fetch call and returns its data, or throws ApiError (NETWORK_ERROR when offline). */
export async function call<T>(p: Promise<FetchResult<T>>): Promise<T> {
  let r: FetchResult<T>;
  try {
    r = await p;
  } catch (e) {
    throw new ApiError('NETWORK_ERROR', e instanceof Error ? e.message : 'Network error');
  }
  if (r.error !== undefined || !r.response.ok) throw ApiError.from(r.error, r.response);
  return r.data as T;
}

/** For binary answers (PDF, XLSX, CSV) requested with parseAs: 'blob'. */
export async function callBlob(p: Promise<FetchResult<unknown>>): Promise<{ blob: Blob; filename: string | null }> {
  const blob = (await call(p)) as Blob;
  return { blob, filename: null };
}

/** Passes a caller-owned Idempotency-Key, so a retry of the same action replays instead of repeating it. */
export const withKey = (key: string) => ({ headers: { 'Idempotency-Key': key } });
