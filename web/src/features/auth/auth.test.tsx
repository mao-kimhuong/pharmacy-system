import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { axe } from 'vitest-axe';
import { session } from '@/api/session';
import { AuthProvider } from '@/app/auth';
import { setLang } from '@/i18n';
import { me } from '@/test/fixtures';
import { server } from '@/test/server';
import { AuthGate } from './AuthGate';

function renderGate() {
  session.clear();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <AuthGate><div>APP</div></AuthGate>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

const anonymous = () => server.use(http.post('*/api/auth/v1/refresh', () => HttpResponse.json({ code: 'NOT_AUTHENTICATED', message: '' }, { status: 401 })));

describe('sign in', () => {
  beforeEach(() => setLang('en'));

  it('logs in with phone + password and asks the cookie for the refresh token', async () => {
    anonymous();
    let sent: Record<string, unknown> = {};
    let cookieHeader: string | null = null;
    server.use(
      http.post('*/api/auth/v1/login', async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        cookieHeader = request.headers.get('x-refresh-cookie');
        return HttpResponse.json({ access_token: 'a', token_type: 'bearer', mfa_required: false, mfa_setup_required: false });
      }),
      http.get('*/api/auth/v1/me', () => HttpResponse.json(me())),
    );
    renderGate();
    await userEvent.type(await screen.findByLabelText('Phone number'), '12 334 551');
    await userEvent.type(screen.getByLabelText('Password'), 'secret-pass');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText('APP')).toBeInTheDocument();
    expect(sent).toEqual({ phone: '012334551', password: 'secret-pass' });
    expect(cookieHeader).toBe('1');
    expect(session.token()).toBe('a');
  });

  it('does not say which field was wrong', async () => {
    anonymous();
    server.use(http.post('*/api/auth/v1/login', () => HttpResponse.json({ code: 'INVALID_CREDENTIALS', message: 'x' }, { status: 401 })));
    renderGate();
    await userEvent.type(await screen.findByLabelText('Phone number'), '012334551');
    await userEvent.type(screen.getByLabelText('Password'), 'wrong');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText('Phone number or password is wrong.')).toBeInTheDocument();
  });

  it('shows the unlock time of a locked account in Phnom Penh time', async () => {
    anonymous();
    server.use(http.post('*/api/auth/v1/login', () => HttpResponse.json(
      { code: 'ACCOUNT_LOCKED', message: 'x', details: { locked_until: '2026-10-31T07:35:00Z' } }, { status: 423 })));
    renderGate();
    await userEvent.type(await screen.findByLabelText('Phone number'), '012334551');
    await userEvent.type(screen.getByLabelText('Password'), 'x');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText('Account locked')).toBeInTheDocument();
    expect(screen.getByText('14:35')).toBeInTheDocument();
  });

  it('asks for the 2FA code, and accepts a backup code instead', async () => {
    anonymous();
    let body: Record<string, unknown> = {};
    server.use(
      http.post('*/api/auth/v1/login', () => HttpResponse.json({ token_type: 'bearer', mfa_required: true, mfa_token: 'm1', mfa_setup_required: false })),
      http.post('*/api/auth/v1/login/2fa', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ access_token: 'a', token_type: 'bearer', mfa_required: false, mfa_setup_required: false });
      }),
      http.get('*/api/auth/v1/me', () => HttpResponse.json(me({ role: 'owner', totp_enabled: true }))),
    );
    renderGate();
    await userEvent.type(await screen.findByLabelText('Phone number'), '012334551');
    await userEvent.type(screen.getByLabelText('Password'), 'x');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Use a backup code instead' }));
    await userEvent.type(screen.getByLabelText('Backup code'), 'abcd-efgh-ij');
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }));
    expect(await screen.findByText('APP')).toBeInTheDocument();
    expect(body).toEqual({ mfa_token: 'm1', backup_code: 'abcd-efgh-ij' });
  });

  it('sends an owner without 2FA to the forced setup (no skip)', async () => {
    server.use(
      http.post('*/api/auth/v1/refresh', () => HttpResponse.json({ access_token: 'a', token_type: 'bearer', mfa_required: false, mfa_setup_required: true })),
      http.get('*/api/auth/v1/me', () => HttpResponse.json(me({ role: 'owner', mfa_setup_required: true }))),
    );
    renderGate();
    expect(await screen.findByText('Two-factor is required for your role')).toBeInTheDocument();
    expect(screen.queryByText('APP')).not.toBeInTheDocument();
  });

  it('login page has no axe violations (km)', async () => {
    setLang('km');
    anonymous();
    const { container } = renderGate();
    await screen.findByLabelText('លេខទូរស័ព្ទ');
    await waitFor(async () => expect(await axe(container)).toHaveNoViolations());
  });
});
