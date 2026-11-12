import { Component, type ReactNode } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { isApiError } from '@/api/errors';
import { Button, ErrorState, FullPageState } from '@/design';
import { useUser } from './auth';

export function Forbidden() {
  const { t } = useTranslation(['states', 'shell']);
  const user = useUser();
  const nav = useNavigate();
  return (
    <FullPageState icon="🔒" title={t('forbidden.title')} body={t('forbidden.body', { role: t(`shell:role.${user.role}`, { defaultValue: user.role }) })}
      actions={<Button variant="primary" onClick={() => nav('/')}>{t('forbidden.toDashboard')}</Button>} />
  );
}

export function NotFound() {
  const { t } = useTranslation(['states', 'common']);
  const nav = useNavigate();
  return (
    <FullPageState icon="404" title={t('notFound.title')} body={t('notFound.body')}
      actions={<><Button onClick={() => nav(-1)}>{t('common:action.back')}</Button><Button variant="primary" onClick={() => nav('/')}>{t('common:action.goHome')}</Button></>} />
  );
}

/** A page's query failed with 403/404: show the shared state instead of a broken page. */
export function QueryState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (isApiError(error) && (error.code === 'FORBIDDEN' || error.code === 'BRANCH_FORBIDDEN')) return <Forbidden />;
  if (isApiError(error) && error.code === 'NOT_FOUND') return <NotFound />;
  return <ErrorState error={error} onRetry={onRetry} />;
}

export class RouteErrorBoundary extends Component<{ children: ReactNode }, { error: unknown }> {
  state = { error: null as unknown };
  static getDerivedStateFromError(error: unknown) {
    return { error };
  }
  componentDidCatch(error: unknown) {
    console.error('Page failed to render', error); // the screen says "try again"; the reason must stay findable
  }
  render() {
    if (this.state.error) return <QueryState error={this.state.error} onRetry={() => this.setState({ error: null })} />;
    return this.props.children;
  }
}
