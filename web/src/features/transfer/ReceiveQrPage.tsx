// 11f / 11g Receive by QR (phone): scan the transfer note's QR (its number) or type it, then the quantities.
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { ApiErrorAlert, BranchTag, Button, Input, PageHeader, Scanner, StatusPill } from '@/design';
import { useBranch } from '@/app/branch';
import { toneOf } from '../shared/hooks';
import { ReceiveForm } from './ReceiveForm';

export default function ReceiveQrPage() {
  const { t } = useTranslation(['transfer', 'common', 'nav']);
  const nav = useNavigate();
  const { byId } = useBranch();
  const [number, setNumber] = useState('');
  const [camera, setCamera] = useState(true);
  const find = useMutation({ mutationFn: (n: string) => call(api.inventory.GET('/api/inventory/v1/transfers/by-number/{number}', { params: { path: { number: n.trim() } } })) });
  const tr = find.data;
  return (
    <div className="flex flex-col gap-3 p-4">
      <PageHeader crumb={t('nav:group.transfer')} title={t('tr.scanTitle')} />
      {!tr && (
        <>
          {camera && <Scanner title={t('tr.scanTitle')} formats={['qr_code', 'code_128']} onClose={() => setCamera(false)} onCode={(c) => { setCamera(false); setNumber(c); find.mutate(c); }} />}
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (number.trim()) find.mutate(number); }}>
            <Input aria-label={t('tr.scanHint')} placeholder={t('tr.scanHint')} fieldSize="lg" value={number} onChange={(e) => setNumber(e.target.value)} />
            <Button type="submit" size="lg" variant="primary" loading={find.isPending}>{t('common:action.search')}</Button>
          </form>
          <ApiErrorAlert error={find.error} />
        </>
      )}
      {tr && (
        <>
          <div className="flex flex-wrap items-center gap-2"><b>{tr.number}</b><StatusPill tone={toneOf(tr.status)}>{t(`tr.status.${tr.status}`, { defaultValue: tr.status })}</StatusPill>
            <BranchTag code={byId(tr.from_branch_id)?.code ?? '?'} /> → <BranchTag code={byId(tr.to_branch_id)?.code ?? '?'} /></div>
          {tr.status === 'dispatched' ? <ReceiveForm tr={tr} onDone={() => nav(`/transfers/${tr.id}`)} /> : <Button onClick={() => nav(`/transfers/${tr.id}`)}>{t('common:action.open')}</Button>}
        </>
      )}
    </div>
  );
}
