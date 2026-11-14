// T2: fridge thermometers (feature switch fridge_sensors). Each device posts its readings with its own token (shown
// once); out of range for more than 10 minutes, back in range and silent for 30 minutes go to Telegram. Range per
// fridge (default 2–8 °C). How to set up a cheap Wi-Fi sensor: docs/sensors.md.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { NotificationsS } from '@/api/types';
import { branchName, useBranch } from '@/app/branch';
import { ApiErrorAlert, Button, Card, DataTable, Dialog, Field, Input, Select, StatusPill, Switch, type PillTone } from '@/design';
import { dateTime } from '@/lib/format';

type Sensor = NotificationsS['SensorOut'];
const TONE: Record<string, PillTone> = { ok: 'success', out: 'danger', silent: 'warning' };

export function FridgeSensors() {
  const { t, i18n } = useTranslation(['settings', 'common']);
  const qc = useQueryClient();
  const { branches, byId } = useBranch();
  const key = ['notifications', 'sensors'];
  const q = useQuery({ queryKey: key, queryFn: () => call(api.notifications.GET('/api/notifications/v1/sensors')) });
  const [form, setForm] = useState<{ branch_id: string; name: string; min_c: string; max_c: string } | null>(null);
  const [shown, setShown] = useState<Sensor | null>(null);
  const done = (s: Sensor) => { void qc.invalidateQueries({ queryKey: key }); if (s.token) setShown(s); };
  const add = useMutation({
    mutationFn: () => call(api.notifications.POST('/api/notifications/v1/sensors', { body: form! })),
    onSuccess: (s) => { setForm(null); done(s); },
  });
  const edit = useMutation({
    mutationFn: (v: { id: string; body: NotificationsS['SensorUpdate'] }) => call(api.notifications.PATCH('/api/notifications/v1/sensors/{device_id}', { params: { path: { device_id: v.id } }, body: v.body })),
    onSuccess: done,
  });
  const token = useMutation({
    mutationFn: (id: string) => call(api.notifications.POST('/api/notifications/v1/sensors/{device_id}/token', { params: { path: { device_id: id } } })),
    onSuccess: done,
  });
  const url = `${window.location.origin}/api/notifications/v1/sensors/readings`;
  return (
    <Card title={t('sensors.title')} actions={<Button size="sm" onClick={() => setForm({ branch_id: branches[0]?.id ?? '', name: '', min_c: '2', max_c: '8' })}>+ {t('sensors.add')}</Button>}>
      <div className="flex flex-col gap-2">
        <span className="text-[12px] text-neutral-500">{t('sensors.hint')}</span>
        <ApiErrorAlert error={q.error ?? edit.error ?? token.error} />
        <DataTable rows={q.data} loading={q.isLoading} rowKey={(s) => s.id} dense columns={[
          { key: 'n', header: t('common:label.name'), cell: (s) => s.name },
          { key: 'b', header: t('common:label.branch'), cell: (s) => branchName(byId(s.branch_id), i18n.language) },
          { key: 'r', header: t('sensors.range'), cell: (s) => `${Number(s.min_c)}–${Number(s.max_c)} °C` },
          { key: 'l', header: t('sensors.last'), cell: (s) => (s.last_reading_at ? `${Number(s.last_temp_c).toFixed(1)} °C · ${dateTime(s.last_reading_at)}` : '—') },
          { key: 's', header: t('common:label.status'), cell: (s) => <StatusPill tone={TONE[s.state] ?? 'neutral'}>{t(`sensors.state.${s.state}`, { defaultValue: s.state })}</StatusPill> },
          { key: 'a', header: '', align: 'right', cell: (s) => (
            <span className="flex items-center justify-end gap-2">
              <Switch label={t('telegram.active')} checked={s.is_active} onChange={(on) => edit.mutate({ id: s.id, body: { is_active: on } })} />
              <Button size="sm" onClick={() => token.mutate(s.id)}>{t('sensors.newToken')}</Button>
            </span>
          ) },
        ]} />
      </div>
      <Dialog open={!!form} onClose={() => setForm(null)} title={t('sensors.add')} width={420}
        footer={<><Button onClick={() => setForm(null)}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!form?.name.trim() || !form?.branch_id} loading={add.isPending} onClick={() => add.mutate()}>{t('common:action.save')}</Button></>}>
        {form && <div className="flex flex-col gap-3">
          <Field label={t('common:label.branch')}>{(id) => <Select id={id} value={form.branch_id} onChange={(e) => setForm({ ...form, branch_id: e.target.value })}>{branches.map((b) => <option key={b.id} value={b.id}>{b.code} · {branchName(b, i18n.language)}</option>)}</Select>}</Field>
          <Field label={t('common:label.name')} required>{(id) => <Input id={id} autoFocus maxLength={60} placeholder="Fridge A" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />}</Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('sensors.min')}>{(id) => <Input id={id} inputMode="decimal" suffix="°C" value={form.min_c} onChange={(e) => setForm({ ...form, min_c: e.target.value.replace(/[^\d.-]/g, '') })} />}</Field>
            <Field label={t('sensors.max')}>{(id) => <Input id={id} inputMode="decimal" suffix="°C" value={form.max_c} onChange={(e) => setForm({ ...form, max_c: e.target.value.replace(/[^\d.-]/g, '') })} />}</Field>
          </div>
          <ApiErrorAlert error={add.error} />
        </div>}
      </Dialog>
      <Dialog open={!!shown} onClose={() => setShown(null)} title={t('sensors.tokenTitle', { name: shown?.name })} width={520}
        footer={<Button variant="primary" onClick={() => setShown(null)}>{t('common:action.close')}</Button>}>
        {shown && <div className="flex flex-col gap-2 text-[13px]">
          <p className="m-0">{t('sensors.tokenBody')}</p>
          <code className="block break-all rounded-md bg-neutral-50 px-3 py-2" data-testid="sensor-token">{shown.token}</code>
          <p className="m-0">{t('sensors.how')}</p>
          <code className="block break-all rounded-md bg-neutral-50 px-3 py-2 text-[12px]">POST {url}<br />Authorization: Bearer {shown.token}<br />{'{"temperature_c": 5.4}'}</code>
        </div>}
      </Dialog>
    </Card>
  );
}
