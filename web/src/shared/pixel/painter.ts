/**
 * Tiny pixel-art painter. Sprites are drawn with primitives on a fixed grid, then
 * outlined and rendered once to a data URL (cached). Displayed with
 * `image-rendering: pixelated` at integer scales: no blurry interpolation.
 */
export type Ramp = readonly [hi: string, base: string, lo: string, dark: string];

/** The map's light and materials are built from the mint, graphite and white of the OGK mark. */
export const WORLD_COLORS = {
  ink: '#080f0e',
  graphite: '#101b1a',
  pine: '#1b3832',
  moss: '#295548',
  seaGlass: '#428874',
  mint: '#6ef7c4',
  paleMint: '#a1dccb',
  white: '#f3f9f7',
} as const;

export const PAL = {
  outline: '#16131f',
  stone: ['#d4cedf', '#a39cb6', '#756e8d', '#4d4764'],
  darkStone: ['#8d86a3', '#665f7d', '#4a445e', '#312c43'],
  wood: ['#dda266', '#b0763f', '#7f4e2b', '#52311d'],
  plaster: ['#f6ecd6', '#ddcdaa', '#b7a37f', '#8a7656'],
  red: ['#ef8a66', '#c9573f', '#93392d', '#5f2420'],
  blue: ['#8bbcf0', '#5487c8', '#385f9a', '#243e68'],
  teal: ['#94e6d6', '#52b8aa', '#30837a', '#1d5351'],
  violet: ['#cdb4ff', '#a083ee', '#7058bd', '#493c82'],
  gold: ['#ffe5a8', '#e8b86d', '#b8853f', '#7c5627'],
  green: ['#afe590', '#73b85c', '#4c8842', '#305c2c'],
  copper: ['#f4b48a', '#d7855a', '#a25a3a', '#6b3825'],
  slate: ['#9fb0c8', '#6f819e', '#4f5f7a', '#334056'],
  grass: ['#6fb158', '#5a9e4b', '#4a8a3f', '#3a7033'],
  path: ['#dcbc84', '#c9a46b', '#a98650', '#83663b'],
  water: ['#8cc8ff', '#5598e0', '#3a77c2', '#2a5a99'],
  leaf: ['#78c262', '#4f9a48', '#357539', '#21502a'],
  glass: '#ffd77e',
  glassDark: '#2c3b5e',
  ink: '#1b1830',
  white: '#fbf7ef',
} as const;

export class Grid {
  readonly px: (string | null)[];
  constructor(readonly w: number, readonly h: number) { this.px = new Array(w * h).fill(null); }
  set(x: number, y: number, c: string | null) { if (x >= 0 && y >= 0 && x < this.w && y < this.h) this.px[y * this.w + x] = c; return this; }
  get(x: number, y: number) { return x >= 0 && y >= 0 && x < this.w && y < this.h ? this.px[y * this.w + x] : null; }
  rect(x: number, y: number, w: number, h: number, c: string) { for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) this.set(x + i, y + j, c); return this; }
  hline(x: number, y: number, len: number, c: string) { return this.rect(x, y, len, 1, c); }
  vline(x: number, y: number, len: number, c: string) { return this.rect(x, y, 1, len, c); }
  frame(x: number, y: number, w: number, h: number, c: string) { this.hline(x, y, w, c); this.hline(x, y + h - 1, w, c); this.vline(x, y, h, c); this.vline(x + w - 1, y, h, c); return this; }
  /** Lit block: highlight on top/left, shadow on bottom/right. */
  block(x: number, y: number, w: number, h: number, r: Ramp) {
    this.rect(x, y, w, h, r[1]);
    this.hline(x, y, w, r[0]); this.vline(x, y, h, r[0]);
    this.hline(x, y + h - 1, w, r[2]); this.vline(x + w - 1, y + 1, h - 1, r[2]);
    return this;
  }
  /** Stone courses: staggered mortar lines. */
  bricks(x: number, y: number, w: number, h: number, r: Ramp, course = 4) {
    this.rect(x, y, w, h, r[1]);
    for (let j = 0; j < h; j++) {
      if (j % course === course - 1) this.hline(x, y + j, w, r[2]);
      else { const off = Math.floor(j / course) % 2 ? 3 : 0; for (let i = off; i < w; i += 7) this.set(x + i, y + j, r[2]); }
      if (j % course === 0) for (let i = 1; i < w; i += 7) this.set(x + i + (Math.floor(j / course) % 2 ? 3 : 0), y + j, r[0]);
    }
    this.vline(x + w - 1, y, h, r[2]);
    return this;
  }
  planks(x: number, y: number, w: number, h: number, r: Ramp, step = 3) {
    this.rect(x, y, w, h, r[1]);
    for (let i = 0; i < w; i += step) this.vline(x + i, y, h, r[2]);
    for (let i = 1; i < w; i += step) this.vline(x + i, y, 1, r[0]);
    return this;
  }
  /** Staggered shingle courses on a gable, with the right pitch in shadow. */
  gable(cx: number, top: number, half: number, height: number, r: Ramp, eave = 1) {
    for (let j = 0; j < height; j++) {
      const span = Math.round(((j + 1) / height) * half) + (j === height - 1 ? eave : 0);
      const course = Math.floor(j / 4);
      for (let i = -span; i <= span; i++) {
        const seam = (Math.abs(i) + (course % 2) * 3) % 6 === 0;
        const edge = i === -span || i === span;
        let shade = i < 0 ? r[1] : r[2];
        if (j === height - 1) shade = r[3];
        else if (i === -span || (j % 4 === 0 && i < 0 && !seam)) shade = r[0];
        else if (edge || seam || j % 4 === 3) shade = i < 0 ? r[2] : r[3];
        this.set(cx + i, top + j, shade);
      }
    }
    this.vline(cx, top, height - 1, r[0]);
    this.vline(cx + 1, top + 1, height - 2, r[2]);
    return this;
  }
  /** Hip roof: broad lit face, smaller shaded face and alternating tile joints. */
  hip(x: number, y: number, w: number, h: number, r: Ramp, inset = 3) {
    for (let j = 0; j < h; j++) {
      const s = Math.round(((h - 1 - j) / h) * inset);
      const course = Math.floor(j / 4);
      const fold = w - s - Math.max(4, Math.round(w / 5));
      for (let i = s; i < w - s; i++) {
        const seam = (i + 3 * (course % 2)) % 6 === 0;
        let shade = i < fold ? r[1] : r[2];
        if (j === h - 1) shade = r[3];
        else if (j === 0 || i === s || (j % 4 === 0 && i < fold && !seam)) shade = r[0];
        else if (j % 4 === 3 || seam) shade = i < fold ? r[2] : r[3];
        this.set(x + i, y + j, shade);
      }
    }
    return this;
  }
  disc(cx: number, cy: number, rad: number, c: string) {
    for (let j = -rad; j <= rad; j++) for (let i = -rad; i <= rad; i++) if (i * i + j * j <= rad * rad + rad * 0.6) this.set(cx + i, cy + j, c);
    return this;
  }
  /** Dome: half disc with light on the left. */
  dome(cx: number, base: number, rad: number, r: Ramp) {
    for (let j = -rad; j <= 0; j++) for (let i = -rad; i <= rad; i++) {
      if (i * i + j * j > rad * rad + rad * 0.6) continue;
      const lit = i < -rad / 3 && j < -1;
      this.set(cx + i, base + j, lit ? r[0] : i > rad / 3 ? r[2] : r[1]);
    }
    return this;
  }
  ellipse(cx: number, cy: number, rx: number, ry: number, c: string) {
    for (let j = -ry; j <= ry; j++) for (let i = -rx; i <= rx; i++) if ((i * i) / (rx * rx + 0.3) + (j * j) / (ry * ry + 0.3) <= 1) this.set(cx + i, cy + j, c);
    return this;
  }
  /** Checkerboard dithering of an area with a second colour. */
  dither(x: number, y: number, w: number, h: number, c: string, density = 2) {
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) if ((i + j) % density === 0 && this.get(x + i, y + j)) this.set(x + i, y + j, c);
    return this;
  }
  /** Arched window with a lit pane. */
  window(x: number, y: number, w: number, h: number, lit = true, frame: string = WORLD_COLORS.graphite) {
    const glass = lit ? WORLD_COLORS.mint : WORLD_COLORS.pine;
    this.rect(x, y + 1, w, h - 1, glass);
    this.hline(x + 1, y, w - 2, glass);
    if (lit) this.hline(x + 1, y + h - 1, w - 2, WORLD_COLORS.seaGlass);
    if (w >= 4) this.vline(x + Math.floor(w / 2), y + 1, h - 1, frame);
    if (h >= 5) this.hline(x, y + Math.floor(h / 2), w, frame);
    if (lit) this.set(x, y + 1, WORLD_COLORS.white);
    return this;
  }
  door(x: number, y: number, w: number, h: number, r: Ramp = PAL.wood as Ramp) {
    this.rect(x, y + 1, w, h - 1, r[2]);
    this.hline(x + 1, y, w - 2, r[2]);
    for (let i = 1; i < w; i += 2) this.vline(x + i, y + 1, h - 1, r[3]);
    this.set(x + w - 2, y + Math.floor(h / 2), WORLD_COLORS.paleMint);
    return this;
  }
  /** Stamps a text bitmap; '.' is transparent, other characters map through the palette. */
  stamp(rows: string[], palette: Record<string, string>, x = 0, y = 0) {
    rows.forEach((row, j) => [...row].forEach((ch, i) => { if (ch !== '.' && ch !== ' ' && palette[ch]) this.set(x + i, y + j, palette[ch]); }));
    return this;
  }
  /** Copies another grid (transparent pixels skipped). */
  blit(src: Grid, x: number, y: number) {
    for (let j = 0; j < src.h; j++) for (let i = 0; i < src.w; i++) { const c = src.px[j * src.w + i]; if (c) this.set(x + i, y + j, c); }
    return this;
  }
  /** Thick line made of discs (roads, rivers). */
  stroke(points: [number, number][], radius: number, c: string) {
    for (let k = 0; k < points.length - 1; k++) {
      const [x0, y0] = points[k]; const [x1, y1] = points[k + 1];
      const steps = Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0));
      for (let t = 0; t <= steps; t++) this.disc(Math.round(x0 + ((x1 - x0) * t) / steps), Math.round(y0 + ((y1 - y0) * t) / steps), radius, c);
    }
    return this;
  }
  /** 1-px outline around every filled pixel (classic sprite look). */
  outline(c: string = PAL.outline) {
    const add: [number, number][] = [];
    for (let y = 0; y < this.h; y++) for (let x = 0; x < this.w; x++) {
      if (this.get(x, y)) continue;
      if (this.get(x - 1, y) || this.get(x + 1, y) || this.get(x, y - 1) || this.get(x, y + 1)) add.push([x, y]);
    }
    add.forEach(([x, y]) => this.set(x, y, c));
    return this;
  }
  /** Soft drop shadow under the sprite, drawn before the outline. */
  shadow(cx: number, y: number, rx: number) {
    for (let i = -rx; i <= rx; i++) if (!this.get(cx + i, y)) this.set(cx + i, y, 'rgba(10,8,20,0.35)');
    return this;
  }
}

const cache = new Map<string, string>();
/** Renders a grid to a PNG data URL (1 grid pixel = 1 image pixel), cached by key. */
export function toDataUrl(key: string, draw: () => Grid): string {
  const hit = cache.get(key);
  if (hit) return hit;
  const g = draw();
  if (typeof document === 'undefined') return '';
  const canvas = document.createElement('canvas');
  canvas.width = g.w;
  canvas.height = g.h;
  const c = canvas.getContext('2d');
  if (!c) return '';
  let fill: string | null = null;
  for (let y = 0; y < g.h; y++) {
    const row = y * g.w;
    for (let x = 0; x < g.w;) {
      const color = g.px[row + x];
      let end = x + 1;
      while (end < g.w && g.px[row + end] === color) end++;
      if (color) {
        if (fill !== color) { c.fillStyle = color; fill = color; }
        c.fillRect(x, y, end - x, 1);
      }
      x = end;
    }
  }
  const url = canvas.toDataURL('image/png');
  cache.set(key, url);
  return url;
}

/** Deterministic pseudo-random generator (map decoration must not change between renders). */
export function rng(seed: number) {
  let s = seed >>> 0;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
}
