/** Asset lookup and small room sprites for the shared OGK cast. */
import miniatures from './character-miniatures.json';
import { Grid } from './painter';

type CharacterKey = keyof typeof miniatures.rows;

function characterKey(key: string): CharacterKey {
  return Object.hasOwn(miniatures.rows, key) ? key as CharacterKey : 'human-1';
}

export function portraitUrl(key: string, size = 96): string {
  const variant = size <= 32 ? 'avatar' : 'portrait';
  return `./assets/characters/${characterKey(key)}-${variant}.webp`;
}

export function characterUrl(key: string): string {
  return './assets/characters/' + characterKey(key) + '-figure.webp';
}

/** Compact version of the same individual used within 224×88 room illustrations. */
export function characterGrid(key: string): Grid {
  return new Grid(16, 24).stamp(miniatures.rows[characterKey(key)], miniatures.palette);
}

export const CLASS_COLORS: Readonly<Record<string, string>> = {
  product: '#aefade',
  engineering: '#bcbdbd',
  architecture: '#6ef7c4',
  design: '#90f8d2',
  security: '#59c9a0',
  privacy: '#d0d0d1',
  quality: '#3e8b70',
  performance: '#cbfbe9',
  data: '#a8a9aa',
  platform: '#4baa88',
  market: '#32715c',
  marketing: '#aefade',
  commerce: '#949596',
  documentation: '#e3fcf3',
};
