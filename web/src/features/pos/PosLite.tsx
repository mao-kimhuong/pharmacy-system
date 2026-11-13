// POS lite (4a–4e): phone and small tablet. Scan with the camera or search, cart as cards, total + Pay at the
// bottom, payment in a sheet. Same controller, findings and dialogs as the desktop POS.
import { useState } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ApiErrorAlert, BranchTag, Button, SafetyBadge, Scanner, Sheet, useToast } from '@/design';
import { LangToggle } from '@/app/shell/Header';
import { khr, usd } from '@/lib/format';
import { FindingRow } from './Findings';
import { searchMedicines, toCartMedicine } from './hooks';
import { CartFindings, PaymentView, Totals } from './Panel';
import { PosDialogs, type Dlg } from './PosPage';
import { SaleComplete } from './SaleComplete';
import { ScanBox } from './ScanBox';
import { useFindingActions } from './useFindingActions';
import { usePos } from './usePos';
import { CustomerBox } from './CustomerBox';

export function PosLite() {
  const { t, i18n } = useTranslation(['pos', 'common']);
  const pos = usePos();
  const toast = useToast();
  const [dlg, setDlg] = useState<Dlg>({ kind: '' });
  const [camera, setCamera] = useState(false);
  const fa = useFindingActions(pos, {
    linkRx: (key) => setDlg({ kind: 'rx', key }), options: (key) => setDlg({ kind: 'options', key }), pin: () => setDlg({ kind: 'pin' }),
    approval: () => setDlg({ kind: 'approval' }), customer: () => {}, handoff: () => setDlg({ kind: 'suspend' }),
  });
  const onCode = async (code: string) => {
    const hits = await searchMedicines(code);
    const h = hits.find((x) => x.matched_pack_unit_id) ?? (hits.length === 1 ? hits[0] : null);
    if (h) {
      pos.dispatch({ type: 'add', medicine: toCartMedicine(h), pack_unit_id: h.matched_pack_unit_id ?? undefined });
      toast.success(`${h.brand_name} +1`);
    } else toast.error(t('noMatch', { q: code }));
  };
  const cartFindings = pos.p ? [...pos.p.hard_stops, ...pos.p.requirements, ...pos.p.warnings].filter((f) => f.line_no == null) : [];
  return (
    <div className="relative flex h-dvh flex-col bg-neutral-50">
      <header className="flex flex-none items-center gap-2 border-b border-neutral-200 bg-white px-4 py-2.5">
        <Link to="/" aria-label={t('common:action.goHome')} className="flex size-9 items-center justify-center rounded-lg bg-primary-600 font-bold text-white no-underline pointer-coarse:size-11">+</Link>
        <b className="text-[15px]">{t('title')}</b>
        {pos.branch && <BranchTag code={pos.branch.code} />}
        <span className="ml-auto" />
        <LangToggle size="sm" />
      </header>
      <div className="flex flex-none gap-2 px-4 pt-3">
        <div className="flex-1"><ScanBox onAdd={(m, pack) => pos.dispatch({ type: 'add', medicine: m, pack_unit_id: pack })} /></div>
        <button type="button" aria-label={t('lite.scan')} onClick={() => setCamera(true)} className="flex size-[52px] items-center justify-center rounded-lg bg-primary-600 text-[18px] text-white">▦</button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-4 py-3">
        {pos.cart.lines.length === 0 && <div className="p-8 text-center text-[14px] text-neutral-500">{t('empty')}</div>}
        {pos.cart.lines.map((l, i) => {
          const pl = pos.p?.lines.find((x) => x.line_no === i + 1);
          const findings = [...(pl?.hard_stops ?? []), ...(pl?.requirements ?? []), ...(pl?.warnings ?? [])].filter((f) => f.code !== 'NEAR_EXPIRY');
          return (
            <div key={l.key} className="flex flex-col gap-2 rounded-xl border border-neutral-200 bg-white p-3">
              <div className="flex items-start justify-between gap-2">
                <div className="flex min-w-0 flex-col gap-1">
                  <b className="text-[15px]">{i18n.language === 'km' && l.medicine.name_km ? l.medicine.name_km : l.medicine.name}</b>
                  <span className="flex flex-wrap gap-1">
                    {l.medicine.controlled && <SafetyBadge kind="controlled" />}
                    {l.medicine.is_rx_only && <SafetyBadge kind="rx">{l.rx?.number}</SafetyBadge>}
                    {pl?.promotions.map((pr) => <SafetyBadge key={pr.id} kind="promotion">{pr.name_en}</SafetyBadge>)}
                  </span>
                </div>
                <span className="num text-[16px] font-semibold">{pl ? usd(pl.net) : '…'}</span>
              </div>
              <div className="flex items-center gap-2">
                <select aria-label={t('cols.unit')} value={l.pack_unit_id} onChange={(e) => pos.dispatch({ type: 'unit', key: l.key, pack_unit_id: e.target.value })} className="h-11 rounded-md border border-neutral-300 bg-white px-2 text-[14px]">
                  {l.medicine.pack_units.filter((u) => u.is_active).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
                </select>
                <span className="ml-auto flex h-11 items-center overflow-hidden rounded-md border border-neutral-300">
                  <button type="button" aria-label="−" className="h-full w-11 text-[18px]" onClick={() => pos.dispatch({ type: 'qty', key: l.key, qty: l.qty - 1 })}>−</button>
                  <span className="num w-10 text-center font-semibold">{l.qty}</span>
                  <button type="button" aria-label="+" className="h-full w-11 text-[18px]" onClick={() => pos.dispatch({ type: 'qty', key: l.key, qty: l.qty + 1 })}>+</button>
                </span>
              </div>
              {findings.map((f, j) => <FindingRow key={j} f={f} actions={f.resolved ? [] : fa.line(l, f)} />)}
            </div>
          );
        })}
        <CartFindings findings={cartFindings} actionsFor={fa.cart} />
      </div>
      <div className="flex flex-none items-center gap-3 border-t border-neutral-200 bg-white px-4 pt-3 pb-5">
        <div className="flex flex-col">
          <span className="num text-[24px] leading-7 font-bold" data-testid="pos-total">{usd(pos.p?.total ?? 0)}</span>
          <span className="num text-[13px] text-primary-700">{pos.p?.total_khr != null ? khr(pos.p.total_khr) : ''}</span>
        </div>
        <Button size="lg" onClick={() => pos.cart.lines.length && setDlg({ kind: 'suspend' })} disabled={!pos.cart.lines.length}>{t('actions.suspend')}</Button>
        <Button variant="primary" size="lg" className="flex-1" disabled={!pos.canPay} onClick={() => pos.setMode('pay')}>{t('lite.pay', { amount: usd(pos.p?.total ?? 0) })}</Button>
      </div>
      <Sheet open={pos.mode === 'pay' && !pos.done} onClose={() => pos.setMode('cart')} title={t('actions.pay')}>
        <CustomerBox customer={pos.cart.customer} onChange={(c) => pos.dispatch({ type: 'customer', customer: c })} />
        <Totals preview={pos.p} />
        <PaymentView preview={pos.p} tender={pos.tender} setTender={pos.setTender} changeIn={pos.changeIn} setChangeIn={pos.setChangeIn} rate={pos.rate}
          onMethod={(m) => { if (m === 'KHQR') setDlg({ kind: 'khqr' }); else if (m === 'PAYWAY') setDlg({ kind: 'payway' }); else if (m !== 'cash') pos.addOther(m); }}
          onBack={() => pos.setMode('cart')} completing={pos.complete.isPending} canComplete={pos.canPay && !!pos.p?.payment && pos.preview.fresh}
          onComplete={() => pos.complete.mutate()} error={<ApiErrorAlert error={pos.complete.error} />} />
      </Sheet>
      <Sheet open={camera} onClose={() => setCamera(false)} title={t('lite.scan')}>
        {camera && <Scanner onClose={() => setCamera(false)} onCode={(c) => void onCode(c)} />}
      </Sheet>
      <PosDialogs pos={pos} dlg={dlg} setDlg={setDlg} />
      {pos.done && <SaleComplete invoice={pos.done} onNew={pos.reset} />}
    </div>
  );
}
