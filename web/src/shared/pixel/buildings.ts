/**
 * Buildings of the kingdom, one recognisable silhouette per place (brief §3.1).
 * Drawn with the painter primitives on a 1-px grid, then outlined. All original artwork.
 */
import { Grid, WORLD_COLORS, toDataUrl, type Ramp } from './painter';

export type PlaceKey = 'royaume' | 'blueprint' | 'guilde' | 'conseil' | 'quetes' | 'bibliotheque' | 'forge' | 'tour' | 'observatoire' | 'documentation' | 'chroniques' | 'intendance';

const STONE: Ramp = ['#c7dcd4', '#839e95', '#55736b', '#263e38'];
const BASALT: Ramp = ['#89a79c', '#56736a', '#354f48', '#1b312c'];
const TIMBER: Ramp = ['#849d94', '#546f64', '#344f45', '#182e27'];
const PAPER: Ramp = ['#eff8f3', '#c5d9d1', '#9ab6aa', '#607e73'];
const SLATE: Ramp = ['#81b3a1', '#48776a', '#2d5148', '#192e2e'];
const ENAMEL: Ramp = ['#9bdec5', '#4b927b', '#2c6554', '#183b31'];
const VERDIGRIS: Ramp = ['#a7dec9', '#5a9b86', '#326e5e', '#174337'];
const GLASS: Ramp = ['#cff9e7', '#8ccdb7', '#4d9c83', '#24594e'];
const DOME: Ramp = ['#a6cbbd', '#668f81', '#416a5f', '#25483e'];
const LANTERN: Ramp = [WORLD_COLORS.white, WORLD_COLORS.mint, '#47a98b', '#255f4f'];
const BRONZE: Ramp = ['#a2bdb3', '#718d80', '#405c52', '#233b31'];
const STEEL: Ramp = ['#b2c9bf', '#6c8c80', '#45655c', '#263f36'];

const battlements = (g: Grid, x: number, y: number, w: number, r: Ramp) => {
  g.rect(x, y + 3, w, 2, r[1]);
  for (let i = 0; i < w; i += 4) g.block(x + i, y, Math.min(3, w - i), 4, r);
};
const slit = (g: Grid, x: number, y: number, lit = false) => g.rect(x, y, 1, 3, lit ? WORLD_COLORS.mint : WORLD_COLORS.ink).set(x, y - 1, WORLD_COLORS.ink);

function plinth(g: Grid, x: number, y: number, width: number) {
  g.hline(x + 1, y, width - 2, STONE[0])
    .hline(x, y + 1, width, STONE[2])
    .hline(x, y + 2, width, STONE[3]);
}

function standard(g: Grid, x: number, y: number, material: Ramp) {
  g.hline(x - 1, y, 6, STONE[2])
    .rect(x, y + 1, 4, 10, material[2])
    .vline(x, y + 2, 8, material[1])
    .hline(x + 1, y + 4, 2, WORLD_COLORS.white)
    .vline(x + 1, y + 9, 3, material[1]);
}

const DRAW: Record<PlaceKey, () => Grid> = {
  royaume: () => {
    const g = new Grid(78, 72);
    g.bricks(19, 26, 40, 42, STONE);
    battlements(g, 19, 21, 40, STONE);
    for (const x of [6, 56]) {
      g.bricks(x, 18, 16, 50, BASALT);
      g.gable(x + 7, 2, 9, 15, SLATE, 1);
      slit(g, x + 7, 28, true); slit(g, x + 7, 42); slit(g, x + 7, 54, true);
    }
    g.rect(31, 46, 16, 22, TIMBER[3]).hline(32, 45, 14, TIMBER[3]).hline(33, 44, 12, TIMBER[3]);
    for (let i = 33; i < 46; i += 3) g.vline(i, 46, 21, STEEL[2]);
    for (let j = 49; j < 66; j += 4) g.hline(32, j, 14, STEEL[2]);
    g.window(24, 32, 5, 7).window(49, 32, 5, 7);
    g.vline(38, 4, 18, TIMBER[2]).rect(39, 4, 9, 6, LANTERN[1]).hline(39, 4, 9, LANTERN[0]).rect(41, 6, 3, 2, GLASS[2]);
    g.hline(20, 29, 37, STONE[0]).hline(20, 31, 37, STONE[2]);
    g.hline(34, 42, 10, STONE[0]).hline(32, 43, 14, STONE[1]);
    for (const x of [28, 48]) g.vline(x, 45, 21, STONE[0]).vline(x + 1, 45, 21, STONE[2]);
    g.stamp(['..m..', '.mmm.', 'mmmmm', '.mmm.', '..m..'], { m: WORLD_COLORS.paleMint }, 36, 36);
    plinth(g, 19, 68, 40);
    return g.outline(WORLD_COLORS.ink);
  },
  blueprint: () => {
    const g = new Grid(64, 62);
    g.rect(8, 26, 48, 33, PAPER[1]).dither(8, 26, 48, 33, PAPER[0], 5);
    for (const x of [8, 20, 43, 55]) g.vline(x, 26, 33, TIMBER[2]);
    g.hline(8, 26, 48, TIMBER[2]).hline(8, 42, 48, TIMBER[2]);
    g.gable(31, 5, 28, 22, ENAMEL, 2);
    g.window(27, 12, 9, 7, true);
    g.rect(13, 29, 38, 10, ENAMEL[2]).frame(13, 29, 38, 10, ENAMEL[3]);
    for (let i = 16; i < 50; i += 4) g.vline(i, 30, 8, ENAMEL[1]);
    for (let j = 31; j < 38; j += 3) g.hline(14, j, 36, ENAMEL[1]);
    g.hline(18, 33, 12, WORLD_COLORS.white).vline(18, 31, 5, WORLD_COLORS.white).hline(33, 35, 12, WORLD_COLORS.white).vline(44, 31, 5, WORLD_COLORS.white).set(31, 33, WORLD_COLORS.white).set(32, 34, WORLD_COLORS.white);
    g.rect(11, 29, 2, 10, PAPER[2]).rect(51, 29, 2, 10, PAPER[2]);
    g.door(28, 45, 8, 14, TIMBER).window(12, 45, 6, 8).window(46, 45, 6, 8);
    g.hline(8, 27, 48, STONE[3]).hline(10, 28, 44, STONE[2]);
    g.rect(21, 48, 3, 7, ENAMEL[2]).rect(22, 49, 1, 3, LANTERN[0]);
    g.rect(39, 48, 3, 7, ENAMEL[2]).rect(40, 49, 1, 3, LANTERN[0]);
    plinth(g, 8, 59, 48);
    return g.outline(WORLD_COLORS.ink);
  },
  guilde: () => {
    const g = new Grid(82, 66);
    g.rect(6, 30, 70, 33, PAPER[1]).dither(6, 30, 70, 33, PAPER[0], 6);
    for (let x = 6; x <= 75; x += 10) g.vline(x, 30, 33, TIMBER[2]);
    g.hline(6, 30, 70, TIMBER[2]).hline(6, 44, 70, TIMBER[2]).hline(6, 62, 70, TIMBER[3]);
    for (let i = 0; i < 9; i++) { g.set(7 + i, 43 - i, TIMBER[2]); g.set(74 - i, 43 - i, TIMBER[2]); }
    g.gable(40, 3, 38, 28, SLATE, 2);
    for (const x of [22, 52]) { g.rect(x, 18, 8, 8, PAPER[1]).gable(x + 3, 13, 5, 5, SLATE, 1).window(x + 2, 20, 4, 5); }
    g.rect(33, 46, 15, 17, TIMBER[3]).hline(34, 45, 13, TIMBER[3]);
    g.vline(40, 46, 17, TIMBER[2]);
    for (let j = 48; j < 62; j += 4) { g.hline(34, j, 6, TIMBER[2]); g.hline(41, j, 6, TIMBER[2]); }
    g.window(14, 48, 7, 9).window(61, 48, 7, 9).window(14, 33, 7, 8).window(61, 33, 7, 8);
    standard(g, 26, 31, VERDIGRIS);
    standard(g, 52, 31, VERDIGRIS);
    g.hline(6, 31, 70, STONE[3]).hline(7, 32, 68, TIMBER[1]);
    plinth(g, 5, 63, 72);
    return g.outline(WORLD_COLORS.ink);
  },
  conseil: () => {
    const g = new Grid(82, 74);
    for (let i = 0; i < 3; i++) g.rect(4 + i * 2, 66 + i * 2, 74 - i * 4, 2, i === 0 ? STONE[0] : STONE[1]).hline(4 + i * 2, 67 + i * 2, 74 - i * 4, STONE[2]);
    g.rect(8, 39, 66, 27, BASALT[3]);
    g.ellipse(41, 61, 14, 3, TIMBER[1]).ellipse(41, 60, 13, 2, TIMBER[0]);
    for (const x of [24, 33, 49, 58]) g.rect(x, 54, 3, 5, GLASS[1]);
    g.rect(38, 55, 6, 3, LANTERN[1]);
    for (let x = 9; x <= 69; x += 15) { g.rect(x, 38, 5, 28, PAPER[1]).vline(x, 38, 28, PAPER[0]).vline(x + 4, 38, 28, PAPER[2]).rect(x - 1, 37, 7, 2, STONE[0]).rect(x - 1, 64, 7, 2, STONE[1]); }
    g.block(5, 32, 72, 6, STONE);
    g.gable(41, 19, 36, 13, STONE, 0);
    g.disc(41, 26, 3, LANTERN[1]).set(41, 26, LANTERN[0]);
    g.dome(41, 18, 13, GLASS);
    g.rect(28, 17, 27, 2, STONE[1]);
    g.vline(41, 1, 5, LANTERN[2]).disc(41, 3, 1, LANTERN[0]);
    for (const x of [34, 41, 48]) g.window(x - 1, 9, 3, 5, true, GLASS[3]);
    for (const x of [9, 24, 39, 54, 69]) g.vline(x + 2, 40, 24, PAPER[2]);
    g.hline(7, 34, 68, STONE[0]).hline(5, 36, 72, STONE[3]);
    return g.outline(WORLD_COLORS.ink);
  },
  quetes: () => {
    const g = new Grid(74, 62);
    g.planks(4, 26, 44, 33, TIMBER);
    g.gable(25, 6, 24, 21, VERDIGRIS, 2);
    g.window(10, 34, 8, 8).window(34, 34, 8, 8).door(21, 43, 9, 16, TIMBER);
    g.rect(22, 30, 7, 4, TIMBER[3]).rect(23, 31, 5, 2, LANTERN[1]);
    g.rect(52, 30, 3, 29, TIMBER[2]).rect(68, 30, 3, 29, TIMBER[2]);
    g.block(49, 26, 25, 4, TIMBER);
    g.rect(51, 31, 21, 17, TIMBER[1]).frame(51, 31, 21, 17, TIMBER[3]);
    for (const [x, y, w, h] of [[53, 33, 6, 7], [61, 33, 8, 5], [62, 40, 7, 6], [53, 42, 7, 5]]) { g.rect(x, y, w, h, PAPER[0]).hline(x + 1, y + 2, w - 2, PAPER[2]).set(x + Math.floor(w / 2), y, SLATE[1]); }
    g.hline(51, 48, 21, TIMBER[3]);
    plinth(g, 4, 59, 44);
    return g.outline(WORLD_COLORS.ink);
  },
  bibliotheque: () => {
    const g = new Grid(66, 80);
    g.bricks(7, 28, 52, 49, STONE, 5);
    g.hip(3, 13, 60, 16, VERDIGRIS, 6);
    g.gable(33, 4, 14, 12, VERDIGRIS, 1);
    g.window(29, 8, 8, 7, true, VERDIGRIS[3]);
    for (const x of [12, 46]) g.window(x, 36, 8, 18, true, STONE[3]).window(x, 58, 8, 12, true, STONE[3]);
    g.rect(25, 32, 16, 9, PAPER[0]).vline(33, 32, 9, PAPER[2]).frame(25, 32, 16, 9, VERDIGRIS[3]);
    for (let j = 34; j < 40; j += 2) { g.hline(27, j, 5, WORLD_COLORS.ink); g.hline(35, j, 4, WORLD_COLORS.ink); }
    g.rect(27, 52, 12, 25, TIMBER[2]).hline(28, 51, 10, TIMBER[2]).hline(29, 50, 8, TIMBER[2]);
    g.vline(33, 52, 25, TIMBER[3]).set(31, 64, LANTERN[0]).set(35, 64, LANTERN[0]);
    g.hline(8, 29, 50, STONE[2]).hline(8, 30, 50, STONE[0]);
    for (const x of [9, 56]) g.vline(x, 32, 44, STONE[0]);
    plinth(g, 7, 77, 52);
    return g.outline(WORLD_COLORS.ink);
  },
  forge: () => {
    const g = new Grid(74, 64);
    g.bricks(4, 28, 52, 33, BASALT);
    g.hip(1, 15, 58, 14, BRONZE, 4);
    g.bricks(44, 2, 9, 18, STONE, 3).rect(43, 1, 11, 3, BASALT[2]).rect(45, 0, 7, 2, BASALT[3]);
    g.rect(11, 40, 26, 21, BASALT[3]).hline(12, 39, 24, BASALT[3]).hline(14, 38, 20, BASALT[3]);
    g.ellipse(18, 55, 5, 4, BRONZE[1]).ellipse(18, 56, 3, 3, LANTERN[1]).ellipse(18, 57, 1, 2, LANTERN[0]);
    g.rect(25, 52, 10, 3, STEEL[1]).rect(27, 55, 6, 2, STEEL[2]).rect(28, 57, 4, 4, STEEL[2]).hline(25, 52, 10, STEEL[0]);
    g.window(42, 38, 7, 8);
    g.planks(57, 38, 14, 23, TIMBER).hip(55, 32, 18, 6, TIMBER, 2);
    g.rect(60, 44, 2, 10, STEEL[1]).rect(58, 43, 6, 2, STEEL[2]).rect(66, 46, 2, 9, TIMBER[3]);
    for (const [x, y] of [[14, 53], [19, 49], [21, 46], [17, 43]]) g.set(x, y, WORLD_COLORS.paleMint);
    g.hline(7, 37, 49, BASALT[0]);
    plinth(g, 4, 61, 68);
    return g.outline(WORLD_COLORS.ink);
  },
  tour: () => {
    const g = new Grid(46, 98);
    g.bricks(13, 30, 20, 65, STONE, 5);
    g.rect(7, 22, 32, 8, TIMBER[2]).hline(7, 22, 32, TIMBER[0]).hline(7, 29, 32, TIMBER[3]);
    for (let x = 8; x < 39; x += 4) g.vline(x, 17, 5, TIMBER[2]);
    g.hline(7, 17, 32, TIMBER[1]);
    g.gable(22, 1, 17, 18, SLATE, 1);
    g.vline(22, 0, 3, TIMBER[3]);
    g.window(19, 34, 7, 8, true);
    slit(g, 22, 52); slit(g, 22, 66, true); slit(g, 22, 79);
    g.door(18, 85, 9, 10, TIMBER);
    g.vline(14, 43, 51, STONE[0]).vline(30, 42, 52, STONE[2]);
    g.hline(14, 44, 17, STONE[2]).hline(14, 78, 17, STONE[2]);
    standard(g, 8, 29, VERDIGRIS);
    plinth(g, 12, 95, 22);
    return g.outline(WORLD_COLORS.ink);
  },
  observatoire: () => {
    const g = new Grid(70, 74);
    g.bricks(8, 38, 54, 33, STONE, 4);
    g.dome(35, 38, 25, DOME);
    g.hline(27, 17, 5, WORLD_COLORS.paleMint).hline(22, 20, 4, DOME[0]);
    g.rect(31, 15, 7, 23, GLASS[3]).hline(32, 14, 5, GLASS[3]);
    for (let i = 0; i < 14; i++) { g.rect(36 + i, 22 - i, 3, 3, STEEL[i % 4 === 0 ? 0 : 1]); }
    g.rect(49, 6, 5, 5, STEEL[2]).set(52, 7, WORLD_COLORS.mint);
    for (const [x, y] of [[18, 26], [24, 19], [46, 30], [53, 36], [14, 34]]) g.set(x, y, LANTERN[0]);
    g.window(15, 46, 6, 9).window(49, 46, 6, 9).door(29, 54, 12, 17, TIMBER);
    g.hline(11, 38, 50, GLASS[3]).hline(12, 39, 47, STONE[0]);
    for (const x of [12, 57]) g.vline(x, 42, 28, STONE[2]);
    plinth(g, 8, 71, 54);
    return g.outline(WORLD_COLORS.ink);
  },
  documentation: () => {
    const g = new Grid(62, 60);
    g.rect(6, 24, 50, 33, PAPER[1]).dither(6, 24, 50, 33, PAPER[0], 5);
    g.hline(6, 24, 50, TIMBER[2]).vline(6, 24, 33, TIMBER[2]).vline(55, 24, 33, TIMBER[2]);
    g.gable(30, 4, 27, 21, LANTERN, 2);
    g.disc(30, 15, 4, TIMBER[3]).disc(30, 15, 3, WORLD_COLORS.mint).vline(30, 12, 7, TIMBER[3]).hline(27, 15, 7, TIMBER[3]);
    g.rect(16, 28, 30, 9, PAPER[0]).rect(14, 27, 3, 11, PAPER[2]).rect(45, 27, 3, 11, PAPER[2]);
    for (let j = 30; j < 36; j += 2) g.hline(19, j, 18 - (j % 4) * 2, WORLD_COLORS.ink);
    for (let i = 0; i < 7; i++) g.set(40 + i, 35 - i, WORLD_COLORS.white).set(41 + i, 35 - i, STEEL[1]);
    g.door(26, 42, 9, 15, TIMBER).window(11, 42, 7, 9).window(43, 42, 7, 9);
    g.hline(7, 40, 48, PAPER[2]).hline(8, 41, 46, PAPER[0]);
    plinth(g, 6, 57, 50);
    return g.outline(WORLD_COLORS.ink);
  },
  chroniques: () => {
    const g = new Grid(54, 82);
    g.bricks(10, 26, 34, 53, BASALT, 5);
    g.gable(27, 2, 21, 23, STEEL, 2);
    g.disc(27, 37, 8, LANTERN[2]).disc(27, 37, 7, PAPER[0]);
    for (const [dx, dy] of [[0, -6], [6, 0], [0, 6], [-6, 0]]) g.set(27 + dx, 37 + dy, WORLD_COLORS.ink);
    g.vline(27, 32, 6, WORLD_COLORS.ink).hline(27, 37, 4, WORLD_COLORS.ink).set(27, 37, SLATE[1]);
    g.window(15, 50, 6, 10).window(33, 50, 6, 10);
    g.rect(20, 63, 14, 16, TIMBER[2]).hline(21, 62, 12, TIMBER[2]).hline(22, 61, 10, TIMBER[2]);
    for (const j of [66, 72]) g.hline(20, j, 14, STEEL[2]);
    g.vline(27, 62, 17, TIMBER[3]);
    g.hline(11, 28, 32, STONE[1]).hline(12, 46, 30, BASALT[2]);
    g.vline(11, 29, 49, BASALT[0]).vline(42, 29, 49, BASALT[2]);
    plinth(g, 10, 79, 34);
    return g.outline(WORLD_COLORS.ink);
  },
  intendance: () => {
    const g = new Grid(76, 58);
    g.planks(4, 24, 58, 31, TIMBER);
    g.hip(1, 9, 64, 16, STEEL, 5);
    g.rect(25, 33, 16, 22, TIMBER[2]).frame(25, 33, 16, 22, TIMBER[3]);
    for (let i = 0; i < 16; i++) { g.set(25 + i, 33 + Math.round(i * 21 / 15), TIMBER[3]); g.set(40 - i, 33 + Math.round(i * 21 / 15), TIMBER[3]); }
    g.window(9, 31, 8, 8).window(48, 31, 8, 8);
    g.disc(49, 45, 3, LANTERN[1]).disc(49, 45, 1, TIMBER[1]).rect(52, 44, 8, 2, LANTERN[1]).rect(57, 46, 2, 2, LANTERN[1]).rect(54, 46, 1, 2, LANTERN[1]);
    g.block(62, 45, 9, 9, TIMBER).block(64, 38, 7, 7, TIMBER).block(66, 50, 9, 5, TIMBER);
    g.hline(63, 49, 7, TIMBER[3]).vline(66, 45, 9, TIMBER[3]);
    g.hline(4, 25, 58, TIMBER[3]).hline(5, 26, 56, TIMBER[1]);
    g.frame(65, 40, 4, 3, PAPER[2]).set(67, 41, WORLD_COLORS.mint);
    plinth(g, 4, 55, 70);
    return g.outline(WORLD_COLORS.ink);
  },
};

export const PLACE_SPRITES = Object.keys(DRAW) as PlaceKey[];
const grids: Partial<Record<string, Grid>> = {};
const sprite = (key: string, draw: () => Grid) => {
  const g = (grids[key] ??= draw());
  return { url: toDataUrl(key, () => g), w: g.w, h: g.h };
};
export const buildingSprite = (key: PlaceKey) => sprite(`building:${key}`, DRAW[key]);

/** A product keeps its identity on the map through graphites and tones of the brand mint. */
export function territoryAccent(color: string) {
  if (!/^#[\da-f]{6}$/i.test(color)) return WORLD_COLORS.mint;
  const value = Number.parseInt(color.slice(1), 16);
  const red = value >> 16;
  const green = (value >> 8) & 255;
  const blue = value & 255;
  if (green >= red && green >= blue) return WORLD_COLORS.mint;
  if (red >= blue) return '#cedcd6';
  return red > green ? '#73a99b' : WORLD_COLORS.paleMint;
}

/** Cottage used on project territories, tinted with the product's map colour. */
export function cottageSprite(color: string, archived = false) {
  const draw = () => {
    const g = new Grid(22, 20);
    const roof: Ramp = archived ? BASALT : [lighten(color, 0.35), color, darken(color, 0.3), darken(color, 0.55)];
    g.rect(3, 9, 16, 10, archived ? STONE[2] : PAPER[1]).gable(11, 1, 10, 9, roof, 1).door(9, 12, 4, 7, TIMBER).window(4, 11, 3, 4, !archived).window(15, 11, 3, 4, !archived);
    return g.outline(WORLD_COLORS.ink);
  };
  return sprite(`cottage:${color}:${archived}`, draw);
}

function mix(hex: string, target: number, amount: number) {
  const n = parseInt(hex.slice(1), 16);
  const ch = [n >> 16, (n >> 8) & 255, n & 255].map((c) => Math.round(c + (target - c) * amount));
  return `#${ch.map((c) => c.toString(16).padStart(2, '0')).join('')}`;
}
export const lighten = (hex: string, a: number) => mix(hex, 255, a);
export const darken = (hex: string, a: number) => mix(hex, 0, a);
