// 3d / 4c: link a prescription to an Rx-only line. Patient by name or phone → active prescriptions → the item for
// this medicine with what can be dispensed now (GET prescriptions/{id}/remaining).
import { useState } from 'react';
import { useQueries, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { PrescriptionS } from '@/api/types';
import { Button, Combobox, Drawer, Field, SafetyBadge, StatusPill, cx } from '@/design';
import { date } from '@/lib/format';
import type { CartLine, RxLink } from './cart';

type Patient = PrescriptionS['PatientSummary'];

export function LinkRxDrawer({ line, onClose, onLink, onRemove }: { line: CartLine | null; onClose: () => void; onLink: (rx: RxLink) => void; onRemove: () => void }) {
  const { t, i18n } = useTranslation(['pos', 'common']);
  const [patient, setPatient] = useState<Patient | null>(null);
  const [chosen, setChosen] = useState<{ itemId: string; number: string } | null>(null);
  const km = i18n.language === 'km';
  const detail = useQuery({
    queryKey: ['prescription', 'patient', patient?.id],
    enabled: !!patient,
    queryFn: () => call(api.prescription.GET('/api/prescription/v1/patients/{patient_id}', { params: { path: { patient_id: patient!.id } } })),
  });
  const rxs = useQuery({
    queryKey: ['prescription', 'rx-of', patient?.id],
    enabled: !!patient,
    queryFn: () => call(api.prescription.GET('/api/prescription/v1/prescriptions', { params: { query: { patient_id: patient!.id, size: 50 } } })),
  });
  const open = (rxs.data?.items ?? []).filter((r) => r.status === 'active' || r.status === 'partly_dispensed');
  const remaining = useQueries({
    queries: open.map((r) => ({
      queryKey: ['prescription', 'remaining', r.id],
      queryFn: () => call(api.prescription.GET('/api/prescription/v1/prescriptions/{rx_id}/remaining', { params: { path: { rx_id: r.id } } })),
    })),
  });
  if (!line) return null;
  const matches = remaining.flatMap((q) => (q.data ? q.data.items.filter((it) => it.medicine_id === line.medicine.id).map((it) => ({ rx: q.data!, it })) : []));
  const pname = (p: { name_en: string; name_km: string }) => (km && p.name_km ? p.name_km : p.name_en);
  return (
    <Drawer open onClose={onClose} title={t('rx.title')} subtitle={`${line.medicine.name} × ${line.qty}`}
      footer={<>
        <Button variant="danger-outline" onClick={() => { onRemove(); onClose(); }}>{t('actions.remove')}</Button>
        <Button variant="primary" disabled={!chosen || !patient} onClick={() => { onLink({ rx_item_id: chosen!.itemId, number: chosen!.number, patient: pname(patient!) }); onClose(); }}>{t('rx.link')}</Button>
      </>}>
      <div className="flex flex-col gap-3">
        <Field label={t('rx.patient')}>
          {(id) => (
            <Combobox<Patient> id={id} value={patient} onChange={(p) => { setPatient(p); setChosen(null); }} autoFocus minChars={2}
              queryKey={['prescription', 'patients']} itemKey={(p) => p.id} itemLabel={(p) => `${pname(p)} · ${p.phone}`}
              search={async (q) => (await call(api.prescription.GET('/api/prescription/v1/patients', { params: { query: { q, size: 8 } } }))).items} />
          )}
        </Field>
        {detail.data && (
          <div className="flex flex-col gap-1 rounded-lg border border-neutral-200 p-2.5">
            <b>{pname(detail.data)}</b>
            <div className="flex flex-wrap gap-1.5 text-[12px] text-neutral-700">
              {detail.data.allergies.filter((a) => a.is_active).length === 0 ? t('rx.noAllergies') :
                detail.data.allergies.filter((a) => a.is_active).map((a) => <SafetyBadge key={a.id} kind="allergy">{a.value}</SafetyBadge>)}
            </div>
          </div>
        )}
        {patient && <div className="text-[12px] font-semibold tracking-[.06em] text-neutral-500 uppercase">{t('rx.active')}</div>}
        {patient && rxs.isSuccess && remaining.every((q) => !q.isLoading) && matches.length === 0 && <div className="text-neutral-500">{t('rx.none')}</div>}
        {matches.map(({ rx, it }) => {
          const on = chosen?.itemId === it.rx_item_id;
          const disabled = !rx.dispensable || it.can_dispense_now <= 0;
          return (
            <button key={it.rx_item_id} type="button" disabled={disabled} onClick={() => setChosen({ itemId: it.rx_item_id, number: rx.number })}
              className={cx('flex flex-col gap-1.5 rounded-lg border p-2.5 text-left', on ? 'border-primary-600 bg-primary-50' : 'border-neutral-200', disabled && 'opacity-50')}>
              <span className="flex items-center justify-between gap-2"><b>{rx.number}</b><StatusPill tone={rx.status === 'active' ? 'primary' : 'warning'}>{t(`rxStatus.${rx.status}`, { ns: 'sales', defaultValue: rx.status })}</StatusPill></span>
              <span className="text-neutral-700">{it.name} · {it.dosage} {it.frequency}{it.duration_days ? ` · ${it.duration_days}d` : ''}</span>
              <span className="text-[12px] text-neutral-500">{t('rx.validTo', { date: date(rx.valid_until) })}</span>
              <span className="grid grid-cols-4 gap-1 text-center text-[12px]">
                <span><span className="block text-neutral-500">{t('rx.fill')}</span><b>{it.fill_base}</b></span>
                <span><span className="block text-neutral-500">{t('rx.remaining')}</span><b>{it.remaining_base}</b></span>
                <span><span className="block text-neutral-500">{t('rx.canNow')}</span><b>{it.can_dispense_now}</b></span>
                <span><span className="block text-neutral-500">{t('rx.repeats')}</span><b>{it.repeats_used} / {it.repeats_allowed}</b></span>
              </span>
            </button>
          );
        })}
      </div>
    </Drawer>
  );
}
