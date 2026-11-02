// Every page: path, sidebar group + label, gate, and the lazily loaded screen.
import { lazy, type ComponentType, type LazyExoticComponent } from 'react';
import type { Gate } from './gate';

export type GroupKey =
  | 'dashboard' | 'sales' | 'prescriptions' | 'controlled' | 'stock' | 'warehouse' | 'purchase' | 'transfer'
  | 'contacts' | 'reports' | 'users' | 'settings';

export const GROUPS: { key: GroupKey; icon: string }[] = [
  { key: 'dashboard', icon: '▦' },
  { key: 'sales', icon: '◎' },
  { key: 'prescriptions', icon: '℞' },
  { key: 'controlled', icon: '◆' },
  { key: 'stock', icon: '▤' },
  { key: 'warehouse', icon: '▣' },
  { key: 'purchase', icon: '⊕' },
  { key: 'transfer', icon: '⇄' },
  { key: 'contacts', icon: '☰' },
  { key: 'reports', icon: '▥' },
  { key: 'users', icon: '◐' },
  { key: 'settings', icon: '⚙' },
];

export interface PageDef {
  /** i18n key under nav:item. */
  key: string;
  path: string;
  group?: GroupKey;
  gate?: Gate;
  /** false: a route without a sidebar entry (detail pages, mobile flows). */
  nav?: boolean;
  /** Full-screen without the shell (POS). */
  bare?: boolean;
  Component: LazyExoticComponent<ComponentType>;
}

const P = (def: Omit<PageDef, 'Component'>, load: () => Promise<{ default: ComponentType }>): PageDef => ({ ...def, Component: lazy(load) });

export const PAGES: PageDef[] = [
  P({ key: 'dashboard', path: '/', group: 'dashboard', gate: undefined }, () => import('@/features/home/HomePage')),
  P({ key: 'pos', path: '/pos', group: 'sales', gate: { menu: 'pos' }, bare: true }, () => import('@/features/pos/PosPage')),
  P({ key: 'sale_template', path: '/sales/templates', group: 'sales', gate: { menu: 'sale_template' } }, () => import('@/features/sales/TemplatesPage')),
  P({ key: 'sale_suspend', path: '/sales/suspended', group: 'sales', gate: { menu: 'sale_suspend' } }, () => import('@/features/sales/SuspendedPage')),
  P({ key: 'sale_order', path: '/sales/orders', group: 'sales', gate: { menu: 'sale_order' } }, () => import('@/features/sales/OrdersPage')),
  P({ key: 'sale_order', path: '/sales/orders/:id', nav: false, gate: { menu: 'sale_order' } }, () => import('@/features/sales/OrderDetailPage')),
  P({ key: 'list_sale', path: '/sales/invoices', group: 'sales', gate: { menu: 'list_sale' } }, () => import('@/features/sales/InvoicesPage')),
  P({ key: 'list_sale', path: '/sales/invoices/:id', nav: false, gate: { perms: ['sales.view', 'pos.sell'] } }, () => import('@/features/sales/InvoiceDetailPage')),
  P({ key: 'sale_return', path: '/sales/returns', group: 'sales', gate: { menu: 'sale_return' } }, () => import('@/features/sales/ReturnsPage')),
  P({ key: 'list_commission', path: '/sales/commission', group: 'sales', gate: { menu: 'list_commission' } }, () => import('@/features/sales/CommissionPage')),
  P({ key: 'items_promotion', path: '/sales/promotions', group: 'sales', gate: { menu: 'items_promotion' } }, () => import('@/features/sales/PromotionsPage')),
  P({ key: 'patients', path: '/rx/patients', group: 'prescriptions', gate: { menu: 'patients' } }, () => import('@/features/rx/PatientsPage')),
  P({ key: 'patients', path: '/rx/patients/:id', nav: false, gate: { perms: ['patients.view'] } }, () => import('@/features/rx/PatientDetailPage')),
  P({ key: 'doctors', path: '/rx/doctors', group: 'prescriptions', gate: { menu: 'doctors' } }, () => import('@/features/rx/DoctorsPage')),
  P({ key: 'prescriptions', path: '/rx/prescriptions', group: 'prescriptions', gate: { menu: 'prescriptions' } }, () => import('@/features/rx/PrescriptionsPage')),
  P({ key: 'prescriptions', path: '/rx/prescriptions/new', nav: false, gate: { perms: ['prescriptions.manage'] } }, () => import('@/features/rx/NewRxPage')),
  P({ key: 'prescriptions', path: '/rx/prescriptions/:id', nav: false, gate: { perms: ['prescriptions.view'] } }, () => import('@/features/rx/RxDetailPage')),
  P({ key: 'dispense', path: '/rx/dispense', group: 'prescriptions', gate: { perms: ['pos.dispense_rx'], pharmacist: true } }, () => import('@/features/rx/DispensePage')),
  P({ key: 'register', path: '/controlled/register', group: 'controlled', gate: { menu: 'register' } }, () => import('@/features/controlled/RegisterPage')),
  P({ key: 'register', path: '/controlled/entries/:id', nav: false, gate: { perms: ['controlled.view'] } }, () => import('@/features/controlled/EntryDetailPage')),
  P({ key: 'discrepancies', path: '/controlled/discrepancies', group: 'controlled', gate: { menu: 'discrepancies' } }, () => import('@/features/controlled/DiscrepanciesPage')),
  P({ key: 'chain', path: '/controlled/verify', group: 'controlled', gate: { perms: ['controlled.view'] } }, () => import('@/features/controlled/ChainPage')),
  P({ key: 'stock', path: '/stock', group: 'stock', gate: { menu: 'stock' } }, () => import('@/features/stock/StockPage')),
  P({ key: 'batches', path: '/stock/batches', group: 'stock', gate: { perms: ['inventory.view'] } }, () => import('@/features/stock/BatchesPage')),
  P({ key: 'stock_take', path: '/stock/counts', group: 'stock', gate: { menu: 'stock_take' } }, () => import('@/features/stock/CountsPage')),
  P({ key: 'stock_take', path: '/stock/counts/:id', nav: false, gate: { perms: ['stockcount.count'] } }, () => import('@/features/stock/CountPage')),
  P({ key: 'locations', path: '/stock/locations', group: 'stock', gate: { perms: ['inventory.view'] } }, () => import('@/features/stock/LocationsPage')),
  P({ key: 'movements', path: '/stock/movements', group: 'stock', gate: { perms: ['inventory.view'] } }, () => import('@/features/stock/MovementsPage')),
  P({ key: 'reorder', path: '/stock/reorder', group: 'stock', gate: { menu: 'reorder' } }, () => import('@/features/stock/ReorderPage')),
  P({ key: 'reorder_settings', path: '/stock/reorder-settings', group: 'stock', gate: { perms: ['inventory.reorder_settings'] } }, () => import('@/features/stock/ReorderSettingsPage')),
  P({ key: 'recall', path: '/stock/recalls', group: 'stock', gate: { menu: 'recall' } }, () => import('@/features/stock/RecallsPage').then((m) => ({ default: m.RecallsPage }))),
  P({ key: 'recall', path: '/stock/recalls/:id', nav: false, gate: { perms: ['inventory.recall'] } }, () => import('@/features/stock/RecallsPage').then((m) => ({ default: m.RecallDetailPage }))),
  P({ key: 'product', path: '/products', group: 'warehouse', gate: { menu: 'product' } }, () => import('@/features/warehouse/ProductsPage')),
  P({ key: 'product', path: '/products/new', nav: false, gate: { perms: ['products.manage'] } }, () => import('@/features/warehouse/NewMedicinePage')),
  P({ key: 'product', path: '/products/:id', nav: false, gate: { perms: ['products.view'] } }, () => import('@/features/warehouse/ProductDetailPage')),
  P({ key: 'categories', path: '/products/categories', group: 'warehouse', gate: { perms: ['products.view'] } }, () => import('@/features/warehouse/LookupsPage')),
  P({ key: 'hamper', path: '/hampers', group: 'warehouse', gate: { menu: 'hamper' } }, () => import('@/features/warehouse/HampersPage')),
  P({ key: 'import_product', path: '/imports', group: 'warehouse', gate: { menu: 'import_product' } }, () => import('@/features/warehouse/ImportPage')),
  P({ key: 'print_label', path: '/labels', group: 'warehouse', gate: { menu: 'print_label' } }, () => import('@/features/warehouse/LabelsPage')),
  P({ key: 'initialize', path: '/initialize', group: 'warehouse', gate: { menu: 'initialize' } }, () => import('@/features/warehouse/InitializePage')),
  P({ key: 'profile', path: '/profile', group: 'settings' }, () => import('@/features/profile/ProfilePage')),
  P({ key: 'more', path: '/more', nav: false }, () => import('@/features/home/MorePage')),
  P({ key: 'design', path: '/dev/design', gate: { dev: true }, nav: false }, () => import('@/features/dev/DesignPage')),
];
