import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { api, call, withKey } from './client';
import { ApiError } from './errors';
import { session } from './session';

const ME = '*/api/auth/v1/me';

describe('api client', () => {
  afterEach(() => session.clear());

  it('sends the in-memory access token as a bearer token', async () => {
    session.set('tok-1');
    let auth: string | null = null;
    server.use(http.get(ME, ({ request }) => { auth = request.headers.get('authorization'); return HttpResponse.json({}); }));
    await call(api.auth.GET('/api/auth/v1/me'));
    expect(auth).toBe('Bearer tok-1');
  });

  it('refreshes once on 401 (cookie, X-Refresh-Cookie) and retries the request with the new token', async () => {
    session.set('old');
    const seen: string[] = [];
    let refreshHeader: string | null = null;
    let refreshBody = 'x';
    server.use(
      http.get(ME, ({ request }) => {
        const a = request.headers.get('authorization') ?? '';
        seen.push(a);
        return a === 'Bearer new' ? HttpResponse.json({ id: 'u' }) : HttpResponse.json({ code: 'NOT_AUTHENTICATED', message: 'x' }, { status: 401 });
      }),
      http.post('*/api/auth/v1/refresh', async ({ request }) => {
        refreshHeader = request.headers.get('x-refresh-cookie');
        refreshBody = await request.text();
        return HttpResponse.json({ access_token: 'new', token_type: 'bearer', mfa_required: false, mfa_setup_required: false });
      }),
    );
    const out = await call(api.auth.GET('/api/auth/v1/me'));
    expect(out).toEqual({ id: 'u' });
    expect(seen).toEqual(['Bearer old', 'Bearer new']);
    expect(refreshHeader).toBe('1');
    expect(refreshBody).toBe(''); // the refresh token never travels in JS: it is the httpOnly cookie
    expect(session.token()).toBe('new');
  });

  it('marks the session expired when the refresh fails', async () => {
    session.set('old');
    server.use(
      http.get(ME, () => HttpResponse.json({ code: 'NOT_AUTHENTICATED', message: 'x' }, { status: 401 })),
      http.post('*/api/auth/v1/refresh', () => HttpResponse.json({ code: 'NOT_AUTHENTICATED', message: 'x' }, { status: 401 })),
    );
    await expect(call(api.auth.GET('/api/auth/v1/me'))).rejects.toMatchObject({ code: 'NOT_AUTHENTICATED', status: 401 });
    expect(session.isExpired()).toBe(true);
  });

  it('adds an Idempotency-Key to operations that take one, and keeps a caller key for retries', async () => {
    const keys: (string | null)[] = [];
    server.use(http.post('*/api/sales/v1/invoices', ({ request }) => { keys.push(request.headers.get('idempotency-key')); return HttpResponse.json({}); }));
    const body = { branch_id: 'b', lines: [], payments: [] } as never;
    await call(api.sales.POST('/api/sales/v1/invoices', { body }));
    await call(api.sales.POST('/api/sales/v1/invoices', { body, ...withKey('same-key') }));
    await call(api.sales.POST('/api/sales/v1/invoices', { body, ...withKey('same-key') }));
    expect(keys[0]).toMatch(/^[0-9a-f-]{36}$/);
    expect(keys.slice(1)).toEqual(['same-key', 'same-key']);
  });

  it('does not add an Idempotency-Key where the API takes none', async () => {
    let key: string | null = 'x';
    server.use(http.post('*/api/auth/v1/pin/verify', ({ request }) => { key = request.headers.get('idempotency-key'); return HttpResponse.json({}); }));
    await call(api.auth.POST('/api/auth/v1/pin/verify', { body: { pin: '1234', action: 'a' } }));
    expect(key).toBeNull();
  });

  it('turns ErrorOut into an ApiError with code, status, details and field errors', async () => {
    server.use(http.post('*/api/auth/v1/login', () => HttpResponse.json(
      { code: 'VALIDATION_ERROR', message: 'bad', details: { errors: [{ loc: ['body', 'phone'], msg: 'Field required' }] } },
      { status: 422, headers: { 'X-Request-ID': 'req-1' } },
    )));
    const e = await call(api.auth.POST('/api/auth/v1/login', { body: { phone: '', password: '' } })).catch((x) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect(e).toMatchObject({ code: 'VALIDATION_ERROR', status: 422, requestId: 'req-1' });
    expect((e as ApiError).fieldErrors()).toEqual({ phone: 'Field required' });
  });

  it('reports a network failure as NETWORK_ERROR', async () => {
    server.use(http.get(ME, () => HttpResponse.error()));
    await expect(call(api.auth.GET('/api/auth/v1/me'))).rejects.toMatchObject({ code: 'NETWORK_ERROR' });
  });
});
