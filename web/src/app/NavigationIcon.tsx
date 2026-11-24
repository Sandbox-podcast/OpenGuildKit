import type { PlaceKey } from '@/shared/pixel/buildings';

const OUTLINES: Record<PlaceKey, string> = {
  royaume: 'M3 8.5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z',
  blueprint: 'M6 3.5h8l4 4V20.5H6z M14 3.5v5h4 M9 12h6 M9 16h6',
  guilde: 'M8 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M2 20v-2a5 5 0 0 1 5-5h2a5 5 0 0 1 5 5v2 M16 4a3 3 0 0 1 0 6 M22 20v-2a5 5 0 0 0-4-4.9',
  conseil: 'M20 11.5a6.5 6.5 0 0 1-6.5 6.5h-5L4 21v-4a6.5 6.5 0 0 1 3.5-12h6a6.5 6.5 0 0 1 6.5 6.5z M8 11.5h8',
  quetes: 'M8 5H5v15h14V5h-3 M9 4h6v4H9z M8 13l2 2 4-4 M8 17h7',
  bibliotheque: 'M3 5h6a3 3 0 0 1 3 3v12a3 3 0 0 0-3-3H3z M21 5h-6a3 3 0 0 0-3 3v12a3 3 0 0 1 3-3h6z',
  forge: 'M3.5 8h17v11h-17z M3.5 12h17 M9 8V5h6v3 M11 12v2h2v-2',
  tour: 'M12 2.5l8 4v5c0 4.5-3.5 7.5-8 10-4.5-2.5-8-5.5-8-10v-5z M8.5 12l2.5 2.5 4.5-5',
  observatoire: 'M4 19h16 M5 16l4-5 4 3 6-8 M15 6h4v4',
  documentation: 'M8 3.5h7l4 4v10H8z M15 3.5v5h4 M5 6.5v14h11 M11 11h5 M11 14h5',
  chroniques: 'M3.5 12a8.5 8.5 0 1 1 2 5.5 M3.5 7.5V12h4.5 M12 7.5V12l3 2',
  intendance: 'M4 6h16 M4 12h16 M4 18h16 M8 4v4 M15 10v4 M10 16v4',
  arsenal: 'M9 3v5 M15 3v5 M6 8h12v4a6 6 0 0 1-12 0z M12 18v3',
};

export function NavigationIcon({ place }: { place: PlaceKey }) {
  return <svg width="19" height="19" viewBox="0 0 24 24" className="nav-line-icon" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d={OUTLINES[place]} /></svg>;
}
