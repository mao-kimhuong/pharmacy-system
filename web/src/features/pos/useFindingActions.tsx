// What each finding asks the user to do (3e–3o): link an Rx, enter a PIN, ask for approval, give the patient ID,
// override an allergy (pharmacist), acknowledge duplicate therapy, choose a customer, or remove the line.
import { useTranslation } from 'react-i18next';
import type { CartLine } from './cart';
import type { FindingAction } from './Findings';
import type { Finding } from './hooks';
import type { Pos } from './usePos';

export interface FindingUi {
  linkRx: (key: string) => void;
  options: (key: string) => void;
  pin: () => void;
  approval: () => void;
  customer: () => void;
  handoff: () => void;
}

export function useFindingActions(pos: Pos, ui: FindingUi) {
  const { t } = useTranslation('pos');
  const canDispense = pos.user.is_pharmacist && pos.user.has('pos.dispense_rx');
  const canOverride = pos.user.is_pharmacist && pos.user.has('prescriptions.override_warning');
  const remove = (l: CartLine): FindingAction => ({ label: t('actions.remove'), onClick: () => pos.dispatch({ type: 'remove', key: l.key }) });
  const cart = (f: Finding): FindingAction[] => {
    switch (f.code) {
      case 'PIN_REQUIRED': return [{ label: t('find.pin'), onClick: ui.pin }];
      case 'DISCOUNT_APPROVAL_REQUIRED': return [{ label: t('find.approval'), onClick: ui.approval }];
      case 'CUSTOMER_REQUIRED': return [{ label: t('find.customer'), onClick: ui.customer }];
      default: return [];
    }
  };
  const line = (l: CartLine, f: Finding): FindingAction[] => {
    switch (f.code) {
      case 'RX_REQUIRED': return canDispense ? [{ label: t('find.linkRx'), onClick: () => ui.linkRx(l.key) }] : [{ label: t('handoff'), onClick: ui.handoff }, remove(l)];
      case 'PHARMACIST_REQUIRED': return [{ label: t('handoff'), onClick: ui.handoff }, remove(l)];
      case 'ALLERGY_WARNING':
      case 'DUPLICATE_THERAPY_WARNING': {
        // one code for the whole cart; each finding's details.warnings say what this line needs
        const kinds = new Set(((f.details?.warnings as { kind?: string }[] | undefined) ?? []).map((w) => w.kind));
        if (kinds.size === 0) kinds.add(f.code === 'ALLERGY_WARNING' ? 'allergy' : 'duplicate_therapy');
        const out: FindingAction[] = [];
        if (kinds.has('allergy') && canOverride) out.push({ label: t('find.override'), onClick: () => ui.options(l.key) });
        if (kinds.has('duplicate_therapy')) out.push({ label: t('find.ack'), onClick: () => pos.dispatch({ type: 'update', key: l.key, patch: { acknowledge_warnings: true } }) });
        return [...out, remove(l)];
      }
      case 'VALIDATION_ERROR': return [{ label: t('find.fix'), onClick: () => ui.options(l.key) }];
      case 'PIN_REQUIRED': return [{ label: t('find.pin'), onClick: ui.pin }];
      case 'DISCOUNT_APPROVAL_REQUIRED': return [{ label: t('find.approval'), onClick: ui.approval }];
      default: return f.severity === 'hard_stop' ? [remove(l)] : [];
    }
  };
  return { cart, line };
}
