// Tailwind theme built from the design handoff (docs/design/tokens.json): the single source of colours, type,
// spacing, radii, shadows and breakpoints. Loaded from src/index.css with @config.
import type { Config } from 'tailwindcss';
import tokens from '../docs/design/tokens.json';

const px = (n: number) => `${n}px`;
const strip = <T extends object>(o: T) =>
  Object.fromEntries(Object.entries(o).filter(([k]) => !k.startsWith('$'))) as Record<string, never>;

/** A colour as a CSS variable with the light value as its fallback: `.dark` (src/index.css) redefines the variables,
 * so every class (bg-, text-, border-, /opacity) follows the theme with no `dark:` variants. */
const cv = (name: string, light: string) => `var(--c-${name}, ${light})`;
const scale = (name: string, o: Record<string, string>) =>
  Object.fromEntries(Object.entries(o).filter(([k]) => !k.startsWith('$')).map(([k, hex]) => [k, cv(`${name}-${k}`, hex)]));
const sem = tokens.color.semantic;
// Text, border and tint shades the design used as raw hex next to the semantic colours (now theme-aware tokens)
const semantic = (k: 'success' | 'warning' | 'danger' | 'info', extra: Record<string, string>) => ({
  DEFAULT: cv(k, sem[k]), bg: cv(`${k}-bg`, sem[`${k}-bg`]),
  ...Object.fromEntries(Object.entries(extra).map(([n, hex]) => [n, cv(`${k}-${n}`, hex)])),
});

const safety = Object.fromEntries(
  Object.entries(strip(tokens.color.safety)).map(([k, v]: [string, { bg: string; fg: string }]) => [
    k,
    { DEFAULT: v.bg, fg: v.fg },
  ]),
);
const pill = Object.fromEntries(
  Object.entries(strip(tokens.color['status-pill'])).map(
    ([k, p]: [string, { fg: string; bg: string; bd: string; dot: string }]) => [
      k,
      { DEFAULT: cv(`pill-${k}`, p.bg), fg: cv(`pill-${k}-fg`, p.fg), bd: cv(`pill-${k}-bd`, p.bd), dot: cv(`pill-${k}-dot`, p.dot) },
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
        primary: { ...scale('primary', tokens.color.primary), deep: cv('primary-deep', tokens.color.primary['700']) },
        neutral: scale('neutral', tokens.color.neutral),
        canvas: cv('canvas', tokens.color.canvas),
        focus: cv('focus', tokens.color['focus-ring']),
        surface: cv('surface', '#FFFFFF'), // cards, inputs, dialogs (was bg-white)
        scrim: cv('scrim', tokens.color.neutral['900']), // behind dialogs and drawers
        inverse: cv('inverse', tokens.color.neutral['900']), // dark bars with white text (toast, offline)
        success: semantic('success', { fg: '#164E2E', bd: '#BFE2CC' }),
        warning: semantic('warning', { fg: '#5C3B00', bd: '#F0D48E', soft: '#FFFBF0' }),
        danger: semantic('danger', { fg: '#7A1610', bd: '#F4C3BD', soft: '#FFF8F7', strong: '#9A1D14' }),
        info: semantic('info', { fg: '#173F6E', bd: '#C3D7F0' }),
        rxsoft: { DEFAULT: cv('rxsoft', '#ECEAFB'), fg: cv('rxsoft-fg', '#262A7A') },
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
