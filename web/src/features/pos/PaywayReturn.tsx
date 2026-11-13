// PayWay sends the checkout window back here (continue_success_url / cancel_url). Nothing is decided here: the till
// already follows the payment itself (check-transaction). This page only tells the customer to go back and closes.
import { useEffect } from 'react';
import { useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';

export default function PaywayReturn() {
  const { t } = useTranslation('pos');
  const [params] = useSearchParams();
  const done = params.get('result') === 'done';
  useEffect(() => {
    const timer = window.setTimeout(() => window.close(), 2500); // closes when the POS opened it
    return () => window.clearTimeout(timer);
  }, []);
  return (
    <main className="grid min-h-dvh place-items-center bg-white p-6 text-center">
      <div className="flex max-w-[360px] flex-col gap-2">
        <h1 className="m-0 text-[20px] font-semibold">{done ? t('payway.returnDone') : t('payway.returnCancel')}</h1>
        <p className="m-0 text-[14px] text-neutral-600">{t('payway.returnBody')}</p>
      </div>
    </main>
  );
}
