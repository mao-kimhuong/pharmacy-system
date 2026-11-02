import { useMemo } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from 'react-router';
import { isApiError } from '@/api/errors';
import { Spinner, ToastProvider } from '@/design';
import { AuthGate } from '@/features/auth/AuthGate';
import { AuthProvider } from './auth';
import { BranchProvider } from './branch';
import { makeRouter } from './router';

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: (n, e) => !(isApiError(e) && e.status >= 400 && e.status < 500) && n < 2,
      },
      mutations: { retry: false },
    },
  });
}

function AppRoutes() {
  const router = useMemo(() => makeRouter(), []);
  return (
    <BranchProvider>
      <RouterProvider router={router} />
    </BranchProvider>
  );
}

export function Splash() {
  return (
    <div className="flex h-dvh items-center justify-center bg-neutral-50">
      <Spinner className="size-6" />
    </div>
  );
}

export function App({ client }: { client?: QueryClient }) {
  const qc = useMemo(() => client ?? makeQueryClient(), [client]);
  return (
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <AuthProvider>
          <AuthGate>
            <AppRoutes />
          </AuthGate>
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}
