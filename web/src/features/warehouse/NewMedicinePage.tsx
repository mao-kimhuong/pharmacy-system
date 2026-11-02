import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { ApiErrorAlert, Button, Card, PageHeader, useToast } from '@/design';
import { MedicineFields, emptyMed, toCreate, type MedForm } from './MedicineForm';

export default function NewMedicinePage() {
  const { t } = useTranslation(['warehouse', 'common', 'nav']);
  const nav = useNavigate();
  const toast = useToast();
  const [v, setV] = useState<MedForm>(emptyMed);
  const m = useMutation({ mutationFn: () => call(api.catalog.POST('/api/catalog/v1/medicines', { body: toCreate(v) })), onSuccess: (x) => { toast.success(t('products.saved')); nav(`/products/${x.id}`); } });
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={`${t('nav:group.warehouse')} / ${t('products.title')}`} title={t('products.new')}
        actions={<Button variant="primary" loading={m.isPending} disabled={!v.sku || !v.brand_name || !v.generic_name || !v.base_unit || !v.base_price} onClick={() => m.mutate()}>{t('common:action.save')}</Button>} />
      <Card><MedicineFields v={v} set={(p) => setV({ ...v, ...p })} /></Card>
      <ApiErrorAlert error={m.error} />
    </div>
  );
}
