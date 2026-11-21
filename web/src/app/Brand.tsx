/** Brand is centralised here: name and validated logo (logo.webp, made from assets/brand/logo.png at the repository root). */
export const BRAND = { name: 'Open Guild Kit', logo: './assets/brand/logo.webp', mark: './assets/brand/favicon.png' } as const;

export function Brand({ size = 'header' }: { size?: 'header' | 'hero' }) {
  return <img className={`brand brand-${size}`} src={BRAND.logo} alt={BRAND.name} width={size === 'hero' ? 420 : 108} height={size === 'hero' ? 140 : 36} />;
}
