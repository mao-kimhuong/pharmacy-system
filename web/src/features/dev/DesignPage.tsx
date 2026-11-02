// /dev/design (development only): every component with its states, for review and visual tests.
// The labels here are component demos, not data.
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Alert, Button, Card, Checkbox, ConfirmDialog, DataTable, Drawer, EmptyState, ErrorState, Field, Input, KpiTile, OtpInput,
  PageHeader, PinPad, ReasonDialog, SafetyBadge, Segmented, Select, SkeletonRows, StatusPill, Stepper, Switch, Tabs, TextArea,
  Timeline, UploadBox, useToast, type PillTone, type SafetyKind,
} from '@/design';
import { ApiError } from '@/api/errors';
import { ERROR_TEXTS } from '@/i18n/errors';
import { Bell, LangToggle } from '@/app/shell/Header';

const SAFETY: SafetyKind[] = ['rx', 'controlled', 'expired', 'near-expiry', 'quarantine', 'allergy', 'recalled', 'hamper', 'promotion', 'duplicate-therapy'];
const PILLS: PillTone[] = ['neutral', 'info', 'primary', 'warning', 'success', 'danger', 'cancelled', 'purple'];

export default function DesignPage() {
  const { i18n } = useTranslation();
  const toast = useToast();
  const [tab, setTab] = useState('a');
  const [pin, setPin] = useState('');
  const [otp, setOtp] = useState('');
  const [sw, setSw] = useState(true);
  const [seg, setSeg] = useState<'usd' | 'khr'>('usd');
  const [dlg, setDlg] = useState<'' | 'reason' | 'confirm' | 'drawer'>('');
  const [sel, setSel] = useState(new Set<string>());
  const lang = i18n.language as 'km' | 'en';
  return (
    <div className="flex flex-col gap-6 p-7">
      <PageHeader crumb="Foundations / Design system" title="Design system" actions={<><LangToggle /><Bell /></>} />
      <Card title="Buttons">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary">Primary</Button><Button>Secondary</Button><Button variant="danger">Danger</Button>
          <Button variant="danger-outline" kbd="Esc">Cancel (reason required)</Button><Button variant="ghost">Ghost</Button><Button variant="link">Link</Button>
          <Button variant="primary" loading>Saving</Button><Button disabled>Disabled</Button>
          <Button variant="primary" size="lg" kbd="F9">Pay</Button><Button size="lg" kbd="F8">Suspend</Button><Button>Deactivate</Button>
        </div>
      </Card>
      <Card title="Inputs">
        <div className="grid gap-4 tablet:grid-cols-3">
          <Field label="Default">{(id) => <Input id={id} placeholder="Default" />}</Field>
          <Field label="Phone" error={ERROR_TEXTS.DUPLICATE_PHONE[lang]}>{(id, d, inv) => <Input id={id} aria-describedby={d} invalid={inv} prefix="+855" defaultValue="12 345 678" />}</Field>
          <Field label="Disabled">{(id) => <Input id={id} disabled defaultValue="PP1" />}</Field>
          <Field label="Money" hint="KHR rounds to ៛100">{(id) => <Input id={id} prefix="$" inputMode="decimal" className="text-right" defaultValue="10.00" />}</Field>
          <Field label="Select">{(id) => <Select id={id}><option>One</option><option>Two</option></Select>}</Field>
          <Field label="Text">{(id) => <TextArea id={id} placeholder="Details (min 10 characters)" />}</Field>
          <Checkbox label="Checkbox" defaultChecked /><Switch checked={sw} onChange={setSw} label="Switch" />
          <Segmented value={seg} onChange={setSeg} options={[{ value: 'usd', label: 'USD' }, { value: 'khr', label: 'KHR' }]} />
        </div>
      </Card>
      <Card title="Badges & status">
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap gap-2">{SAFETY.map((k) => <SafetyBadge key={k} kind={k} />)}</div>
          <div className="flex flex-wrap gap-2">{PILLS.map((p) => <StatusPill key={p} tone={p}>{p}</StatusPill>)}</div>
        </div>
      </Card>
      <div className="grid gap-4 tablet:grid-cols-3">
        <KpiTile label="Net sales" scope="ALL" value="$0.00" sub="0 invoices" deltas={[{ value: '+0%', tone: 'flat', label: 'vs yesterday' }]} />
        <Card title="PIN pad"><PinPad value={pin} onChange={setPin} autoFocus={false} /></Card>
        <Card title="Code"><OtpInput value={otp} onChange={setOtp} autoFocus={false} invalid={otp.length === 6} /></Card>
      </div>
      <Card title="Table" padded={false}>
        <DataTable rows={[{ id: '1', a: 'Row 1' }, { id: '2', a: 'Row 2' }]} rowKey={(r) => r.id} selection={{ selected: sel, onChange: setSel, actions: <Button size="sm" variant="link">Action</Button> }}
          columns={[{ key: 'a', header: 'Name', cell: (r) => r.a }, { key: 'b', header: 'Qty', align: 'right', cell: () => '0', footer: '0' }]}
          paging={{ page: 1, size: 20, total: 2, onPage: () => {}, onSize: () => {} }} />
      </Card>
      <div className="grid gap-4 tablet:grid-cols-3">
        <Card title="Empty"><EmptyState title="Nothing here yet" body="Body text" action={<Button variant="primary">Action</Button>} /></Card>
        <Card title="Skeleton"><SkeletonRows rows={4} /></Card>
        <Card title="Server error"><ErrorState error={new ApiError('TEMPORARILY_UNAVAILABLE', 'x', 503)} onRetry={() => {}} /></Card>
      </div>
      <Card title="Alerts & toasts">
        <div className="flex flex-col gap-2">
          <Alert tone="danger" title="Hard stop">{ERROR_TEXTS.OUT_OF_STOCK[lang]}</Alert>
          <Alert tone="warning" title="Warning">{ERROR_TEXTS.RX_REQUIRED[lang]}</Alert>
          <Alert tone="info">{ERROR_TEXTS.SUPPLIER_OVERPAYMENT[lang]}</Alert>
          <Alert tone="success">Saved</Alert>
          <div className="flex gap-2"><Button onClick={() => toast.success('Saved', { label: 'Undo', onClick: () => {} })}>Success toast</Button><Button onClick={() => toast.error('Failed')}>Failure toast</Button></div>
        </div>
      </Card>
      <Card title="Dialogs">
        <div className="flex gap-2"><Button onClick={() => setDlg('reason')}>Reason dialog</Button><Button onClick={() => setDlg('confirm')}>Confirm</Button><Button onClick={() => setDlg('drawer')}>Drawer</Button></div>
        <ReasonDialog open={dlg === 'reason'} onClose={() => setDlg('')} title="Cancel" body="Stays in the system as cancelled." confirmLabel="Cancel" minLength={10} onConfirm={() => {}} />
        <ConfirmDialog open={dlg === 'confirm'} onClose={() => setDlg('')} title="Confirm" body="Body" confirmLabel="OK" onConfirm={() => {}} />
        <Drawer open={dlg === 'drawer'} onClose={() => setDlg('')} title="Drawer">Side drawer · 420px · Esc closes</Drawer>
      </Card>
      <div className="grid gap-4 tablet:grid-cols-3">
        <Card title="Tabs"><Tabs value={tab} onChange={setTab} tabs={[{ value: 'a', label: 'Open', count: 3 }, { value: 'b', label: 'Closed' }]} /></Card>
        <Card title="Stepper"><Stepper current={1} steps={[{ label: 'Approved' }, { label: 'Picked' }, { label: 'Dispatched' }]} /></Card>
        <Card title="Timeline"><Timeline items={[{ title: 'Approved' }, { title: 'Picked', tone: 'current' }, { title: 'Dispatched', tone: 'todo' }]} /></Card>
      </div>
      <Card title="Upload"><UploadBox onFile={(f) => toast.success(f.name)} /></Card>
      <Card title="Error code messages" padded={false}>
        <DataTable rows={Object.entries(ERROR_TEXTS).map(([code, v]) => ({ code, ...v }))} rowKey={(r) => r.code} dense
          columns={[{ key: 'c', header: 'Code', cell: (r) => <code className="font-mono text-[12px]">{r.code}</code> }, { key: 's', header: 'Type', cell: (r) => r.severity },
            { key: 'en', header: 'English', cell: (r) => r.en }, { key: 'km', header: 'ខ្មែរ', cell: (r) => <span className="km">{r.km}</span> }]} />
      </Card>
    </div>
  );
}
