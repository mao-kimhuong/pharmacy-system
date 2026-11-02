// Test data on the e2e branch, created through the public API (once; ids kept in seed.extra).
import { Http, idem, waitFor } from './api';

const today = () => new Date(Date.now() + 7 * 3600_000).toISOString().slice(0, 10);
const inDays = (d: number) => new Date(Date.now() + 7 * 3600_000 + d * 86_400_000).toISOString().slice(0, 10);

export interface Med { id: string; sku: string; name: string; base: string; packs: Record<string, { id: string; barcode: string | null }> }
export interface SalesData {
  suffix: string;
  meds: Record<'para' | 'amox' | 'diaz' | 'cheap', Med>;
  customerId: string;
  customerName: string;
  patientId: string;
  patientPhone: string;
  doctorId: string;
}

interface MedOut { id: string; sku: string; brand_name: string; strength: string; pack_units: { id: string; name: string; barcode: string | null }[] }

async function med(h: Http, body: Record<string, unknown>): Promise<Med> {
  const r = await h.post<MedOut>('/api/catalog/v1/medicines', body);
  if (r.status >= 300) throw new Error(`medicine ${body.sku}: ${JSON.stringify(r.data)}`);
  const m = r.data;
  return { id: m.id, sku: m.sku, name: [m.brand_name, m.strength].filter(Boolean).join(' '), base: String(body.base_unit), packs: Object.fromEntries(m.pack_units.map((p) => [p.name, { id: p.id, barcode: p.barcode }])) };
}

export async function ensureSalesData(owner: Http, branchId: string, existing?: SalesData): Promise<SalesData> {
  if (existing) return existing;
  const s = String(Date.now()).slice(-6);
  const meds = {
    para: await med(owner, { sku: `E2EPARA${s}`, brand_name: `E2E Paracetamol ${s}`, generic_name: 'Paracetamol', strength: '500 mg', base_unit: 'tab', base_price: '0.10', base_barcode: `880${s}001`,
      active_ingredients: ['paracetamol'], pack_units: [{ name: 'strip', qty_in_base: 10, sell_price: '1.00', barcode: `880${s}010` }, { name: 'box', qty_in_base: 100, sell_price: '9.00', barcode: `880${s}100` }] }),
    amox: await med(owner, { sku: `E2EAMOX${s}`, brand_name: `E2E Amoxicillin ${s}`, generic_name: 'Amoxicillin', strength: '500 mg', base_unit: 'cap', base_price: '0.20', is_rx_only: true,
      active_ingredients: ['amoxicillin'], drug_classes: ['penicillins'], pack_units: [{ name: 'strip', qty_in_base: 10, sell_price: '1.80', barcode: `880${s}210` }] }),
    diaz: await med(owner, { sku: `E2EDIAZ${s}`, brand_name: `E2E Diazepam ${s}`, generic_name: 'Diazepam', strength: '5 mg', base_unit: 'tab', base_price: '0.15', is_rx_only: true, controlled_schedule: 'IV',
      active_ingredients: ['diazepam'], drug_classes: ['benzodiazepines'], pack_units: [{ name: 'strip', qty_in_base: 10, sell_price: '1.50' }] }),
    cheap: await med(owner, { sku: `E2ECHEAP${s}`, brand_name: `E2E Cheap ${s}`, generic_name: 'Cheapamol', strength: '1 mg', base_unit: 'tab', base_price: '0.05', pack_units: [] }),
  };
  // stock (inventory learns about the medicines over RabbitMQ: retry while UNKNOWN_MEDICINE / UNKNOWN_BRANCH)
  const line = (m: Med, pack: string, lot: string, days: number, qty: number, cost: string) => ({ medicine_id: m.id, pack_unit_id: m.packs[pack].id, lot_no: lot, expiry_date: inDays(days), qty, unit_cost: cost });
  await waitFor(async () => {
    const r = await owner.post<{ code?: string }>('/api/inventory/v1/stock-in', { branch_id: branchId, reason: 'e2e opening stock', lines: [
      line(meds.para, 'tab', `P1-${s}`, 200, 300, '0.04'), line(meds.para, 'box', `P2-${s}`, 500, 5, '4.00'),
      line(meds.amox, 'cap', `A1-${s}`, 400, 200, '0.08'), line(meds.diaz, 'tab', `D1-${s}`, 400, 100, '0.05'), line(meds.cheap, 'tab', `C1-${s}`, 400, 100, '0.10'),
    ] }, idem());
    if (r.data.code === 'UNKNOWN_MEDICINE' || r.data.code === 'UNKNOWN_BRANCH') return null;
    if (r.status >= 300) throw new Error(`stock-in: ${JSON.stringify(r.data)}`);
    return r;
  }, 60);
  const rate = await owner.put(`/api/sales/v1/exchange-rates/${branchId}`, { khr_per_usd: 4100 });
  if (rate.status >= 300) throw new Error(`rate: ${JSON.stringify(rate.data)}`);
  const cust = await owner.post<{ id: string }>('/api/customers/v1/customers', { phone: `0965${s.slice(-5)}`, name: `E2E Customer ${s}`, credit_limit: '5.00' });
  if (cust.status >= 300) throw new Error(`customer: ${JSON.stringify(cust.data)}`);
  const doc = await owner.post<{ id: string }>('/api/prescription/v1/doctors', { name: `Dr E2E ${s}`, licence_no: `E2E-${s}` });
  if (doc.status >= 300) throw new Error(`doctor: ${JSON.stringify(doc.data)}`);
  const patientPhone = `0955${s.slice(-5)}`;
  const pat = await waitFor(async () => {
    const r = await owner.post<{ id: string; code?: string }>('/api/prescription/v1/patients', { branch_id: branchId, name_en: `E2E Patient ${s}`, sex: 'female', phone: patientPhone,
      allergies: [{ kind: 'class', value: 'penicillins', note: 'rash' }] });
    if (r.data.code === 'UNKNOWN_BRANCH') return null;
    if (r.status >= 300) throw new Error(`patient: ${JSON.stringify(r.data)}`);
    return r.data;
  });
  return { suffix: s, meds, customerId: cust.data.id, customerName: `E2E Customer ${s}`, patientId: pat.id, patientPhone, doctorId: doc.data.id };
}

/** An active prescription for the e2e patient (each test that dispenses makes its own). */
export async function newRx(owner: Http, branchId: string, d: SalesData, medicineId: string, qtyBase: number): Promise<{ id: string; number: string }> {
  return waitFor(async () => {
    const r = await owner.post<{ id: string; number: string; code?: string }>('/api/prescription/v1/prescriptions', {
      branch_id: branchId, patient_id: d.patientId, doctor_id: d.doctorId, issued_on: today(), items: [{ medicine_id: medicineId, qty_base: qtyBase, dosage: '1', frequency: '3/day', duration_days: 7 }] });
    if (r.data.code === 'UNKNOWN_MEDICINE') return null;
    if (r.status >= 300) throw new Error(`rx: ${JSON.stringify(r.data)}`);
    const a = await owner.post<{ status: string }>(`/api/prescription/v1/prescriptions/${r.data.id}/activate`);
    if (a.status >= 300) throw new Error(`rx activate: ${JSON.stringify(a.data)}`);
    return r.data;
  });
}
