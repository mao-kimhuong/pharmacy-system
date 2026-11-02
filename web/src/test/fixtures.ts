// Fixtures typed from the generated API types. Used only by tests.
import type { Branch, Me } from '@/api/types';

export function me(over: Partial<Me> = {}): Me {
  return {
    id: '00000000-0000-4000-8000-000000000001',
    name: 'Test User',
    phone: '012000001',
    role: 'cashier',
    is_pharmacist: false,
    locale: 'km',
    branch_ids: ['10000000-0000-4000-8000-000000000001'],
    totp_enabled: false,
    backup_codes_left: null,
    has_pin: false,
    permissions: ['dashboard.view', 'pos.sell', 'sales.view'],
    menu: [
      { group: 'dashboard', key: 'dashboard', label: 'Dashboard' },
      { group: 'sales', key: 'pos', label: 'POS' },
      { group: 'sales', key: 'list_sale', label: 'List Sale' },
    ],
    mfa_setup_required: false,
    ...over,
  };
}

export function branch(over: Partial<Branch> = {}): Branch {
  return {
    id: '10000000-0000-4000-8000-000000000001',
    code: 'PP1',
    name_km: 'ទួលគោក',
    name_en: 'Toul Kork',
    address: '',
    phone: '',
    license_no: '',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    ...over,
  };
}
