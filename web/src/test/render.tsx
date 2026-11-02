// Renders a component with the app's providers (query client, toasts, signed-in user, router).
import type { ReactElement, ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { http, HttpResponse } from 'msw';
import { ToastProvider } from '@/design';
import type { Me } from '@/api/types';
import { session } from '@/api/session';
import { AuthProvider } from '@/app/auth';
import { BranchProvider } from '@/app/branch';
import { AuthGate } from '@/features/auth/AuthGate';
import { branch, me as meFixture } from './fixtures';
import { server } from './server';

export function signedIn(user: Me = meFixture()) {
  server.use(
    http.post('*/api/auth/v1/refresh', () => HttpResponse.json({ access_token: 'tok', token_type: 'bearer', mfa_required: false, mfa_setup_required: false })),
    http.get('*/api/auth/v1/me', () => HttpResponse.json(user)),
    http.get('*/api/branch/v1/branches', () => HttpResponse.json([branch()])),
    http.get('*/api/branch/v1/features', () => HttpResponse.json([])),
  );
}

export function renderApp(ui: ReactElement, { route = '/', user }: { route?: string; user?: Me } = {}) {
  session.clear();
  signedIn(user);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const wrap = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <AuthProvider>
          <AuthGate>
            <BranchProvider>
              <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
            </BranchProvider>
          </AuthGate>
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
  return render(ui, { wrapper: wrap });
}

/** Plain providers without auth (design components). */
export function renderPlain(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>{ui}</MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}
