// 6e New Rx (6h on phones: camera capture): patient, doctor, dates, items (medicine, qty per fill in the base
// unit, dose, frequency, days, repeats), photos; saved as draft, then activated.
import { useEffect, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { PrescriptionS } from '@/api/types';
import { useBranch } from '@/app/branch';
import { ApiErrorAlert, Button, Card, Combobox, Field, Input, PageHeader, UploadBox, useToast } from '@/design';
import { todayIso } from '@/lib/format';
import { MedicinePicker, medName, type Medicine } from '../shared/MedicinePicker';
import { uploadAttachment } from './attachments';

type Patient = PrescriptionS['PatientSummary'];
type Doctor = PrescriptionS['DoctorOut'];
interface Item { key: number; medicine: Medicine; qty_base: string; dosage: string; frequency: string; duration_days: string; repeats_allowed: string; units_per_dose: string; doses_per_day: string }
const decimal = (s: string) => s.replace(/[^\d.]/g, '').replace(/(\..*)\./g, '$1');

export default function NewRxPage() {
  const { t, i18n } = useTranslation(['rx', 'common', 'nav']);
  const [params] = useSearchParams();
  const { oneBranch } = useBranch();
  const nav = useNavigate();
  const toast = useToast();
  const [patient, setPatient] = useState<Patient | null>(null);
  const [doctor, setDoctor] = useState<Doctor | null>(null);
  const [rxNo, setRxNo] = useState('');
  const [issued, setIssued] = useState(todayIso());
  const [valid, setValid] = useState('');
  const [items, setItems] = useState<Item[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const km = i18n.language === 'km';
  const pre = useQuery({
    queryKey: ['prescription', 'patient', params.get('patient')],
    enabled: !!params.get('patient'),
    queryFn: () => call(api.prescription.GET('/api/prescription/v1/patients/{patient_id}', { params: { path: { patient_id: params.get('patient')! } } })),
  });
  useEffect(() => {
    if (pre.data && !patient) setPatient(pre.data);
  }, [pre.data, patient]);
  const save = useMutation({
    mutationFn: async (activate: boolean) => {
      const rx = await call(api.prescription.POST('/api/prescription/v1/prescriptions', { body: {
        branch_id: oneBranch!.id, patient_id: patient!.id, doctor_id: doctor!.id, rx_no: rxNo, issued_on: issued, valid_until: valid || null,
        items: items.map((i) => ({ medicine_id: i.medicine.id, qty_base: Number(i.qty_base), dosage: i.dosage, frequency: i.frequency, duration_days: Number(i.duration_days) || null, repeats_allowed: Number(i.repeats_allowed) || 0,
          units_per_dose: Number(i.units_per_dose) > 0 ? i.units_per_dose : null, doses_per_day: Number(i.doses_per_day) > 0 ? i.doses_per_day : null })),
      } }));
      for (const f of files) await uploadAttachment(rx.id, f);
      if (activate) await call(api.prescription.POST('/api/prescription/v1/prescriptions/{rx_id}/activate', { params: { path: { rx_id: rx.id } } }));
      return rx;
    },
    onSuccess: (rx, activate) => { toast.success(activate ? t('rx.activated') : t('rx.saved')); nav(`/rx/prescriptions/${rx.id}`); },
  });
  const set = (k: number, p: Partial<Item>) => setItems(items.map((i) => (i.key === k ? { ...i, ...p } : i)));
  const ok = patient && doctor && items.length > 0 && items.every((i) => Number(i.qty_base) > 0);
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={`${t('nav:group.prescriptions')} / ${t('rx.title')}`} title={t('rx.new')}
        actions={<><Button disabled={!ok} loading={save.isPending && !save.variables} onClick={() => save.mutate(false)}>{t('common:action.save')}</Button>
          <Button variant="primary" disabled={!ok} loading={save.isPending && !!save.variables} onClick={() => save.mutate(true)}>{t('rx.activate')}</Button></>} />
      <Card>
        <div className="grid gap-3 tablet:grid-cols-2 desktop:grid-cols-3">
          <Field label={t('rx.patient')} required>{(id) => (
            <Combobox<Patient> id={id} value={patient} onChange={setPatient} minChars={2} queryKey={['prescription', 'patients']} itemKey={(p) => p.id}
              itemLabel={(p) => `${km ? p.name_km || p.name_en : p.name_en || p.name_km} · ${p.phone}`}
              search={async (q) => (await call(api.prescription.GET('/api/prescription/v1/patients', { params: { query: { q, size: 10 } } }))).items} />
          )}</Field>
          <Field label={t('rx.doctor')} required>{(id) => (
            <Combobox<Doctor> id={id} value={doctor} onChange={setDoctor} minChars={1} queryKey={['prescription', 'doctors-pick']} itemKey={(d) => d.id} itemLabel={(d) => `${d.name} · ${d.licence_no}`}
              search={async (q) => (await call(api.prescription.GET('/api/prescription/v1/doctors', { params: { query: { q, size: 10 } } }))).items} />
          )}</Field>
          <Field label={t('rx.rxNo')}>{(id) => <Input id={id} value={rxNo} onChange={(e) => setRxNo(e.target.value)} />}</Field>
          <Field label={t('rx.issued')} required>{(id) => <Input id={id} type="date" value={issued} onChange={(e) => setIssued(e.target.value)} />}</Field>
          <Field label={t('rx.validUntil')}>{(id) => <Input id={id} type="date" value={valid} onChange={(e) => setValid(e.target.value)} />}</Field>
        </div>
      </Card>
      <Card title={t('rx.items')}>
        <div className="flex flex-col gap-2">
          {items.map((i) => (
            <div key={i.key} className="grid grid-cols-2 items-end gap-2 tablet:grid-cols-[2fr_1fr_1fr_1fr_80px_80px_80px_80px_auto]">
              <div className="col-span-2 flex flex-col tablet:col-span-1"><span className="text-[13px] font-medium">{medName(i.medicine)}</span><span className="text-[12px] text-neutral-500">{i.medicine.sku} · {i.medicine.base_unit}</span></div>
              <Field label={`${t('rx.qtyBase')}`}>{(id) => <Input id={id} inputMode="numeric" value={i.qty_base} onChange={(e) => set(i.key, { qty_base: e.target.value.replace(/\D/g, '') })} />}</Field>
              <Field label={t('rx.dosage')}>{(id) => <Input id={id} value={i.dosage} onChange={(e) => set(i.key, { dosage: e.target.value })} />}</Field>
              <Field label={t('rx.frequency')}>{(id) => <Input id={id} value={i.frequency} onChange={(e) => set(i.key, { frequency: e.target.value })} />}</Field>
              <Field label={t('rx.perDose')}>{(id) => <Input id={id} inputMode="decimal" value={i.units_per_dose} onChange={(e) => set(i.key, { units_per_dose: decimal(e.target.value) })} />}</Field>
              <Field label={t('rx.perDay')}>{(id) => <Input id={id} inputMode="decimal" value={i.doses_per_day} onChange={(e) => set(i.key, { doses_per_day: decimal(e.target.value) })} />}</Field>
              <Field label={t('rx.duration')}>{(id) => <Input id={id} inputMode="numeric" value={i.duration_days} onChange={(e) => set(i.key, { duration_days: e.target.value.replace(/\D/g, '') })} />}</Field>
              <Field label={t('rx.repeats')}>{(id) => <Input id={id} inputMode="numeric" value={i.repeats_allowed} onChange={(e) => set(i.key, { repeats_allowed: e.target.value.replace(/\D/g, '') })} />}</Field>
              <Button variant="ghost" aria-label={t('common:action.remove')} onClick={() => setItems(items.filter((x) => x.key !== i.key))}>✕</Button>
            </div>
          ))}
          <MedicinePicker value={null} clearOnPick placeholder={t('rx.addItem')} filter={(m) => m.kind !== 'hamper'}
            onChange={(m) => m && setItems([...items, { key: Date.now(), medicine: m, qty_base: '', dosage: '', frequency: '', duration_days: '', repeats_allowed: '0', units_per_dose: '', doses_per_day: '' }])} />
          {items.length > 0 && <span className="text-[12px] text-neutral-500">{t('rx.doseHint')}</span>}
        </div>
      </Card>
      <Card title={t('rx.attachments')}>
        <div className="flex flex-col gap-2">
          <UploadBox capture onFile={(f) => setFiles([...files, f])} label={t('rx.upload')} />
          {files.map((f, i) => <div key={i} className="flex items-center justify-between text-[13px]"><span>{f.name} · {Math.round(f.size / 1024)} KB</span><Button size="sm" variant="ghost" onClick={() => setFiles(files.filter((_, j) => j !== i))}>✕</Button></div>)}
        </div>
      </Card>
      <ApiErrorAlert error={save.error} />
    </div>
  );
}
