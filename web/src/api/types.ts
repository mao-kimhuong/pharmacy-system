// Schema shortcuts: S.auth['MeResponse'], S.sales['InvoiceOut'], ...
import type { components as Auth } from './gen/auth';
import type { components as BranchC } from './gen/branch';
import type { components as Catalog } from './gen/catalog';
import type { components as Controlled } from './gen/controlled';
import type { components as Customers } from './gen/customers';
import type { components as Documents } from './gen/documents';
import type { components as Inventory } from './gen/inventory';
import type { components as Notifications } from './gen/notifications';
import type { components as Prescription } from './gen/prescription';
import type { components as Purchasing } from './gen/purchasing';
import type { components as Reports } from './gen/reports';
import type { components as Sales } from './gen/sales';
import type { components as Stockcount } from './gen/stockcount';

export type AuthS = Auth['schemas'];
export type BranchS = BranchC['schemas'];
export type CatalogS = Catalog['schemas'];
export type ControlledS = Controlled['schemas'];
export type CustomersS = Customers['schemas'];
export type DocumentsS = Documents['schemas'];
export type InventoryS = Inventory['schemas'];
export type NotificationsS = Notifications['schemas'];
export type PrescriptionS = Prescription['schemas'];
export type PurchasingS = Purchasing['schemas'];
export type ReportsS = Reports['schemas'];
export type SalesS = Sales['schemas'];
export type StockcountS = Stockcount['schemas'];

export type Me = AuthS['MeResponse'];
export type Branch = BranchS['BranchOut'];
