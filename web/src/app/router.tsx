import { createBrowserRouter, Navigate } from 'react-router';
import { useUser } from './auth';
import { useHiddenMenuKeys } from './features';
import { allowed } from './gate';
import { PAGES, type PageDef } from './pages';
import { Forbidden, NotFound } from './RouteError';
import { Shell } from './shell/Shell';

function Guard({ page }: { page: PageDef }) {
  const user = useUser();
  const hidden = useHiddenMenuKeys();
  if (!allowed(page.gate, user, hidden)) return <Forbidden />;
  return <page.Component />;
}

export function makeRouter() {
  return createBrowserRouter([
    ...PAGES.filter((p) => p.bare).map((p) => ({ path: p.path, element: <Guard page={p} /> })),
    {
      element: <Shell />,
      children: [
        ...PAGES.filter((p) => !p.bare).map((p) => ({ path: p.path, element: <Guard page={p} /> })),
        { path: '/login', element: <Navigate to="/" replace /> },
        { path: '*', element: <NotFound /> },
      ],
    },
  ]);
}
