/**
 * Brand is centralised here: name and validated logo (logo.webp, made from assets/brand/logo.png at the repository root).
 * The header shows it at 108 x 36: it gets logo-header.webp, twice that size, a quarter of the bytes.
 */
export const BRAND = {
  name: 'Open Guild Kit',
  logo: './assets/brand/logo.webp',
  logoHeader: './assets/brand/logo-header.webp',
  mark: './assets/brand/favicon.png',
} as const;

export function Brand({ size = 'header' }: { size?: 'header' | 'hero' }) {
  return (
    <img
      className={`brand brand-${size}`}
      src={size === 'hero' ? BRAND.logo : BRAND.logoHeader}
      alt={BRAND.name}
      width={size === 'hero' ? 420 : 108}
      height={size === 'hero' ? 140 : 36}
    />
  );
}
