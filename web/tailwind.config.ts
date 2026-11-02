// Tailwind theme built from the design handoff (docs/design/tokens.json): the single source of colours, type,
// spacing, radii, shadows and breakpoints. Loaded from src/index.css with @config.
import type { Config } from 'tailwindcss';
import tokens from '../docs/design/tokens.json';

const px = (n: number) => `${n}px`;
const strip = <T extends object>(o: T) =>
  Object.fromEntries(Object.entries(o).filter(([k]) => !k.startsWith('$'))) as Record<string, never>;

const safety = Object.fromEntries(
  Object.entries(strip(tokens.color.safety)).map(([k, v]: [string, { bg: string; fg: string }]) => [
    k,
    { DEFAULT: v.bg, fg: v.fg },
  ]),
);
const pill = Object.fromEntries(
  Object.entries(strip(tokens.color['status-pill'])).map(
    ([k, v]: [string, { fg: string; bg: string; bd: string; dot: string }]) => [
      k,
      { DEFAULT: v.bg, fg: v.fg, bd: v.bd, dot: v.dot },
    ],
  ),
);
const type = Object.fromEntries(
  Object.entries(tokens.type).map(([k, v]) => [
    k,
    [px(v.size), { lineHeight: px(v.lh), fontWeight: String(v.weight) }],
  ]),
);
const typeKm = Object.fromEntries(
  Object.entries(tokens.type).map(([k, v]) => [`${k}-km`, [px(v.size), { lineHeight: px(v.lhKm) }]]),
);

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    screens: {
      phone: px(tokens.breakpoints.phone),
      'phone-lg': px(tokens.breakpoints['phone-lg']),
      tablet: px(tokens.breakpoints.tablet),
      desktop: px(tokens.breakpoints.desktop),
      'desktop-lg': px(tokens.breakpoints['desktop-lg']),
    },
    extend: {
      colors: {
        primary: tokens.color.primary,
        neutral: tokens.color.neutral,
        canvas: tokens.color.canvas,
        focus: tokens.color['focus-ring'],
        success: { DEFAULT: tokens.color.semantic.success, bg: tokens.color.semantic['success-bg'] },
        warning: { DEFAULT: tokens.color.semantic.warning, bg: tokens.color.semantic['warning-bg'] },
        danger: { DEFAULT: tokens.color.semantic.danger, bg: tokens.color.semantic['danger-bg'] },
        info: { DEFAULT: tokens.color.semantic.info, bg: tokens.color.semantic['info-bg'] },
        safety,
        pill,
        posdark: strip(tokens.color['pos-dark']),
      },
      fontFamily: {
        sans: tokens.font.sans,
        khmer: tokens.font.khmer,
        mono: tokens.font.mono,
      },
      fontSize: { ...type, ...typeKm },
      spacing: Object.fromEntries(Object.entries(tokens.space).map(([k, v]) => [k, px(v)])),
      borderRadius: Object.fromEntries(Object.entries(tokens.radius).map(([k, v]) => [k, px(v)])),
      boxShadow: tokens.shadow,
      height: {
        header: px(tokens.size['header-height']),
        control: px(tokens.size['control-height']),
        'control-lg': px(tokens.size['control-height-lg']),
        touch: px(tokens.size['touch-target-min']),
        tabbar: px(tokens.size['mobile-tabbar']),
      },
      minHeight: { touch: px(tokens.size['touch-target-min']) },
      minWidth: { touch: px(tokens.size['touch-target-min']) },
      width: {
        sidebar: px(tokens.size.sidebar),
        'sidebar-collapsed': px(tokens.size['sidebar-collapsed']),
      },
    },
  },
} satisfies Config;
