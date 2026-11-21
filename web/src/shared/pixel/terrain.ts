/** Top-down map on the same grid as the interactive HTML buildings. */
import { Grid, WORLD_COLORS, rng, toDataUrl, type Ramp } from './painter';
import type { PlaceKey } from './buildings';

export const MAP_W = 560;
const TOWN_END = 280;
const TERRACE_HEIGHT = 59;
const TERRACES_PER_ROW = 4;

export const PLACE_POS: Record<PlaceKey, { x: number; y: number; door: [number, number] }> = {
  royaume: { x: 228, y: 13, door: [267, 84] },
  blueprint: { x: 123, y: 26, door: [155, 87] },
  observatoire: { x: 352, y: 15, door: [387, 88] },
  tour: { x: 486, y: 9, door: [509, 105] },
  bibliotheque: { x: 25, y: 42, door: [58, 120] },
  guilde: { x: 111, y: 114, door: [152, 178] },
  conseil: { x: 226, y: 107, door: [267, 180] },
  quetes: { x: 366, y: 120, door: [390, 180] },
  forge: { x: 468, y: 132, door: [492, 189] },
  documentation: { x: 38, y: 161, door: [69, 219] },
  chroniques: { x: 166, y: 181, door: [193, 259] },
  intendance: { x: 303, y: 191, door: [341, 247] },
};

export const mapHeight = (count: number) => TOWN_END + TERRACE_HEIGHT * Math.max(1, Math.ceil(count / TERRACES_PER_ROW)) + 10;

export function territoryRect(i: number, count: number) {
  const row = Math.floor(i / TERRACES_PER_ROW);
  const column = i % TERRACES_PER_ROW;
  const items = Math.min(TERRACES_PER_ROW, count - row * TERRACES_PER_ROW);
  const width = 128;
  const step = width + 8;
  return { x: Math.round((MAP_W - items * step + 8) / 2) + column * step, y: TOWN_END + row * TERRACE_HEIGHT + 5, w: width, h: 47 };
}

type Point = [number, number];
type Territory = { color: string; archived: boolean };

const GROUND = ['#102522', '#19332d', '#203e35', '#34594d'] as const;
const STONE: Ramp = ['#6c8a80', '#45635b', '#2c4842', '#142a27'];
const WALL: Ramp = ['#77998b', '#4c6a61', '#324d47', '#0d211e'];
const PATH: Ramp = ['#849e93', '#536a62', '#3a5249', '#293f38'];
const WATER: Ramp = ['#60bb9f', '#378977', '#205648', '#12342c'];
const PINE: Ramp = ['#5e9480', '#386a57', '#264d40', '#102d27'];

const RIVER: Point[] = [
  [334, -3], [333, 32], [326, 65], [330, 93], [349, 113],
  [361, 146], [384, 180], [420, 214], [467, 238], [516, 251], [566, 257],
];
const PLAZA: Point = [267, 222];
const FOOTPRINTS: Record<PlaceKey, number> = {
  royaume: 35, blueprint: 27, guilde: 38, conseil: 37, quetes: 24, bibliotheque: 30,
  forge: 34, tour: 15, observatoire: 30, documentation: 28, chroniques: 22, intendance: 38,
};

export function terrainUrl(territories: Territory[]): string {
  const signature = territories.map((t) => t.color + t.archived).join('|');
  return toDataUrl('mint-realm:' + signature, () => drawTown(territories));
}

function landPatch(g: Grid, points: Point[], color: string) {
  const ys = points.map((point) => point[1]);
  for (let y = Math.min(...ys); y < Math.max(...ys); y++) {
    const intersections: number[] = [];
    for (let i = 0; i < points.length; i++) {
      const [x1, y1] = points[i];
      const [x2, y2] = points[(i + 1) % points.length];
      if (y >= Math.min(y1, y2) && y < Math.max(y1, y2)) {
        intersections.push(Math.round(x1 + (x2 - x1) * (y - y1) / (y2 - y1)));
      }
    }
    intersections.sort((a, b) => a - b);
    for (let i = 0; i + 1 < intersections.length; i += 2) {
      g.hline(intersections[i], y, intersections[i + 1] - intersections[i], color);
    }
  }
}

function ridge(g: Grid, heights: Point[]) {
  const offset = (amount: number): Point[] => heights.map(([x, y]) => [x, y + amount]);
  g.stroke(offset(6), 11, GROUND[0]);
  g.stroke(offset(3), 8, WALL[3]).stroke(offset(1), 6, WALL[2]);
  g.stroke(offset(-2), 4, WALL[1]).stroke(offset(-5), 2, WALL[0]);
  for (const [x, y] of heights.slice(1, -1)) {
    g.vline(x + 2, y, 10, WALL[3]).vline(x + 3, y - 2, 6, WALL[1]);
    g.hline(x - 5, y + 5, 7, WALL[2]);
  }
}

function conifer(w: number, h: number, variant: number) {
  const g = new Grid(w, h);
  const center = Math.floor(w / 2);
  g.rect(center - 1, h - 7, 3, 6, STONE[2]).vline(center - 1, h - 7, 5, STONE[1]);
  for (let tier = 3; tier >= 0; tier--) {
    const top = Math.round(tier * (h - 11) / 4);
    const bottom = top + Math.round(h * 0.4) + tier;
    const left = center - Math.min(center - 1, 2 + tier * 2 + variant);
    const right = center + Math.min(center - 1, 2 + tier * 2);
    landPatch(g, [[center, top], [left, bottom], [center - 1, bottom + 1], [right, bottom]], PINE[3]);
    landPatch(g, [[center, top + 2], [left + 1, bottom - 1], [center, bottom - 3]], PINE[1]);
    landPatch(g, [[center + 1, top + 3], [center + 1, bottom - 2], [right - 1, bottom - 1]], PINE[2]);
    g.hline(left + 1, bottom - 1, Math.max(1, center - left - 2), PINE[0]);
  }
  return g;
}

function paintRiver(g: Grid, random: ReturnType<typeof rng>) {
  g.stroke(RIVER, 18, GROUND[0]).stroke(RIVER, 15, STONE[3]);
  g.stroke(RIVER.map(([x, y]) => [x + 2, y + 2]), 12, STONE[2]);
  g.stroke(RIVER, 11, WATER[3]).stroke(RIVER, 8, WATER[2]);
  g.stroke(RIVER.map(([x, y]) => [x - 3, y + 1]), 4, WATER[1]);
  for (let i = 0; i < 1400; i++) {
    const x = 308 + Math.floor(random() * 253);
    const y = Math.floor(random() * 272);
    const water = g.get(x, y);
    if (water === WATER[1] || water === WATER[2]) {
      g.hline(x, y, 1 + Math.floor(random() * 4), random() > 0.76 ? WATER[0] : WATER[3]);
    }
  }
  for (let y = 5; y < 21; y += 3) g.hline(328 + Math.floor(y / 3) % 3, y, 8, WATER[0]);
  g.hline(327, 23, 15, WATER[3]).hline(331, 24, 13, WORLD_COLORS.paleMint);
  g.hline(322, 27, 12, WATER[1]).hline(334, 28, 6, WATER[0]);
}

function approach(g: Grid, x: number, y: number, width: number) {
  g.ellipse(x + 3, y + 3, width, 9, WORLD_COLORS.ink);
  g.ellipse(x, y, width - 1, 7, STONE[2]);
  g.ellipse(x, y - 1, width - 3, 5, GROUND[2]);
}

function paintPaths(g: Grid, random: ReturnType<typeof rng>) {
  const doors = PLACE_POS;
  const lanes: Point[][] = [
    [doors.royaume.door, [265, 101], [269, 159], PLAZA],
    [doors.blueprint.door, [162, 107], [175, 151], [217, 197], PLAZA],
    [doors.observatoire.door, [383, 100], [346, 116], [312, 156], PLAZA],
    [doors.tour.door, [493, 119], [453, 123], [430, 146], [410, 166], doors.quetes.door],
    [doors.bibliotheque.door, [82, 127], [107, 148], doors.guilde.door, [204, 199], PLAZA],
    [doors.documentation.door, [106, 225], [143, 214], [184, 210], [219, 219], PLAZA],
    [doors.quetes.door, [388, 202], [351, 220], PLAZA],
    [doors.forge.door, [471, 203], [430, 201], [397, 193], doors.quetes.door],
    [doors.chroniques.door, [216, 257], [232, 242], PLAZA],
    [doors.intendance.door, [309, 257], [282, 251], PLAZA],
    [PLAZA, [267, 275]], [[14, 275], [545, 275]],
  ];
  for (const road of lanes) g.stroke(road.map(([x, y]) => [x, y + 2]), 6, WORLD_COLORS.ink);
  for (const road of lanes) g.stroke(road, 5, PATH[2]).stroke(road, 3, PATH[1]);
  for (let i = 0; i < 7200; i++) {
    const x = Math.floor(random() * MAP_W);
    const y = Math.floor(random() * TOWN_END);
    if (g.get(x, y) !== PATH[1]) continue;
    g.set(x, y, random() > 0.54 ? PATH[0] : PATH[2]);
    if (g.get(x + 1, y) === PATH[1]) g.set(x + 1, y, PATH[2]);
  }
}

function bridge(g: Grid, x: number, y: number) {
  g.rect(x - 14, y - 6, 29, 13, WORLD_COLORS.ink);
  g.block(x - 13, y - 4, 27, 9, WALL);
  for (let i = -11; i <= 11; i += 4) g.vline(x + i, y - 3, 7, WALL[2]);
  g.hline(x - 13, y - 5, 27, WALL[0]).hline(x - 13, y + 4, 27, WALL[2]);
  for (const footing of [-14, 12]) {
    g.block(x + footing, y - 6, 3, 4, STONE).block(x + footing, y + 3, 3, 4, STONE);
  }
}

function fountain(g: Grid) {
  const [x, y] = PLAZA;
  g.ellipse(x + 3, y + 3, 26, 17, WORLD_COLORS.ink);
  g.ellipse(x, y, 25, 16, STONE[2]).ellipse(x, y - 1, 23, 14, STONE[0]);
  g.ellipse(x, y - 1, 21, 13, STONE[1]).ellipse(x, y - 2, 14, 9, STONE[3]);
  g.ellipse(x, y - 2, 12, 7, WATER[2]).ellipse(x, y - 4, 8, 4, WATER[1]);
  g.hline(x - 7, y - 1, 12, WATER[0]).hline(x - 5, y + 2, 10, WATER[3]);
  g.vline(x, y - 12, 9, WORLD_COLORS.paleMint).set(x, y - 13, WORLD_COLORS.white);
  g.set(x - 3, y - 7, WORLD_COLORS.mint).set(x + 3, y - 7, WORLD_COLORS.mint);
}

function paintWoodland(g: Grid, random: ReturnType<typeof rng>) {
  const trees = [conifer(19, 29, 1), conifer(15, 25, 0), conifer(11, 18, 1)];
  const ground = new Set<string | null>(GROUND);
  const buildings = Object.values(PLACE_POS);
  for (let y = 2; y < TOWN_END - 10; y += 7) {
    for (let x = 0; x < g.w; x += 7) {
      const tx = x + Math.floor(random() * 8);
      const ty = y + Math.floor(random() * 8);
      const edge = tx < 26 || tx > 535 || ty < 28 || g.get(tx, ty) === GROUND[0];
      const density = edge ? 0.64 : 0.07;
      if (random() > density || !ground.has(g.get(tx, ty))) continue;
      if (buildings.some(p => Math.abs(tx - p.door[0]) < 32 && ty >= p.y - 3 && ty <= p.door[1] + 11)) continue;
      const tree = trees[Math.floor(random() * trees.length)];
      g.ellipse(tx + 2, ty + 1, Math.floor(tree.w / 2), 4, WORLD_COLORS.ink);
      g.blit(tree, tx - Math.floor(tree.w / 2), ty - tree.h + 1);
    }
  }
}

function lantern(g: Grid, x: number, y: number) {
  g.ellipse(x, y + 4, 7, 4, '#344d40').ellipse(x, y + 4, 5, 2, '#486e58');
  g.vline(x, y, 8, STONE[3]).set(x, y + 6, STONE[0]);
  g.rect(x - 2, y - 4, 5, 5, WORLD_COLORS.ink);
  g.rect(x - 1, y - 3, 3, 3, WORLD_COLORS.paleMint).set(x, y - 2, WORLD_COLORS.white);
  g.hline(x - 2, y - 4, 5, STONE[0]);
}

function garden(g: Grid, x: number, y: number) {
  g.ellipse(x + 2, y + 1, 8, 4, GROUND[0]).ellipse(x, y, 6, 3, STONE[1]);
  g.ellipse(x, y - 1, 5, 3, PINE[2]).hline(x - 3, y - 3, 4, PINE[0]);
  g.set(x - 2, y - 2, PINE[0]).set(x, y - 3, WORLD_COLORS.paleMint).set(x + 3, y, WORLD_COLORS.seaGlass);
}

function paintTerrace(g: Grid, territory: Territory, index: number, count: number) {
  const { x, y, w, h } = territoryRect(index, count);
  const gate = x + 12;
  g.rect(gate - 5, y - 10, 11, 10, PATH[2]);
  g.hline(gate - 4, y - 7, 9, PATH[0]).hline(gate - 4, y - 4, 9, PATH[1]);
  g.rect(x + 2, y + 2, w, h, WORLD_COLORS.ink);
  g.rect(x, y, w, h, STONE[3]).rect(x + 2, y + 3, w - 4, h - 7, territory.archived ? GROUND[1] : GROUND[2]);
  g.hline(x + 2, y + 2, w - 4, territory.color);
  g.rect(gate - 4, y, 9, 7, PATH[2]).hline(gate - 3, y + 1, 7, PATH[0]);
  g.block(gate - 6, y, 2, 5, STONE).block(gate + 5, y, 2, 5, STONE);
  g.bricks(x, y + h - 7, w, 7, STONE, 3);
  g.vline(x + 1, y + 4, h - 12, STONE[1]).vline(x + w - 2, y + 4, h - 12, STONE[2]);
  for (let dx = 7; dx < w - 5; dx += 9) {
    g.set(x + dx, y + 29, GROUND[3]).hline(x + dx - 1, y + 31, 3, GROUND[1]);
  }
  g.hline(x + 3, y + 36, w - 6, PATH[2]).hline(x + 4, y + 37, w - 8, PATH[1]);
  g.block(x + 3, y + h - 10, 4, 5, STONE).block(x + w - 7, y + h - 10, 4, 5, STONE);
}

function drawTown(territories: Territory[]): Grid {
  const g = new Grid(MAP_W, mapHeight(territories.length));
  const random = rng(248);
  g.rect(0, 0, g.w, g.h, GROUND[0]);
  landPatch(g, [[0, 104], [86, 68], [155, 57], [236, 70], [280, 54], [323, 85], [354, 157], [321, 206], [246, 268], [0, 272]], GROUND[2]);
  landPatch(g, [[0, 38], [79, 7], [198, 0], [291, 10], [323, 39], [318, 82], [245, 111], [174, 82], [87, 111], [0, 142]], GROUND[1]);
  landPatch(g, [[375, 26], [470, 0], [560, 0], [560, 242], [512, 235], [465, 214], [417, 181], [386, 114]], GROUND[2]);
  landPatch(g, [[0, 261], [74, 267], [117, 243], [192, 274], [319, 257], [453, 273], [560, 261], [560, g.h], [0, g.h]], GROUND[1]);
  ridge(g, [[-7, 112], [18, 89], [32, 67], [65, 47], [82, 26], [118, 12], [151, 4], [186, -10]]);
  ridge(g, [[394, 5], [426, 9], [455, 1], [488, 8], [532, -5], [566, 10]]);
  ridge(g, [[31, 246], [71, 254], [111, 241], [135, 243]]);
  for (let i = 0; i < 4600; i++) {
    const x = Math.floor(random() * g.w);
    const y = Math.floor(random() * g.h);
    const base = g.get(x, y);
    if (base === GROUND[0] || base === GROUND[1] || base === GROUND[2]) {
      g.hline(x, y, random() > 0.88 ? 3 : 1, random() > 0.68 ? GROUND[3] : GROUND[0]);
    }
  }
  paintRiver(g, random);
  for (const key of Object.keys(PLACE_POS) as PlaceKey[]) {
    const [x, y] = PLACE_POS[key].door;
    approach(g, x, y, FOOTPRINTS[key]);
  }
  paintPaths(g, random);
  bridge(g, 349, 115);
  bridge(g, 394, 192);
  fountain(g);
  paintWoodland(g, random);
  for (const [x, y] of [[89, 133], [205, 196], [292, 248], [447, 217], [523, 222], [143, 265]]) garden(g, x, y);
  for (const [x, y] of [[106, 92], [208, 102], [281, 199], [317, 208], [445, 149], [535, 205], [115, 254], [367, 264], [462, 264]]) lantern(g, x, y);
  territories.forEach((territory, index) => paintTerrace(g, territory, index, territories.length));
  return g;
}
