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
  P({ key: 'profile', path: '/profile', group: 'settings' }, () => import('@/features/profile/ProfilePage')),
  P({ key: 'more', path: '/more', nav: false }, () => import('@/features/home/MorePage')),
  P({ key: 'design', path: '/dev/design', gate: { dev: true }, nav: false }, () => import('@/features/dev/DesignPage')),
];
