/** The thirteen places, shared by the demo and the project interface. */
import type { PixelIconName } from '@/shared/pixel/icons';
import type { PlaceKey } from '@/shared/pixel/buildings';

/**
 * name: the place in the RPG style, a game word the glossary explains; proName: the same place in the Pro style,
 * one set for the demo and the project, in the glossary's terms; role: the line the RPG navigation adds.
 */
export interface Place {
  key: PlaceKey;
  name: string;
  proName: string;
  role: string;
  route: string;
  icon: PixelIconName;
  shortcut: string;
}

export const PLACES: Place[] = [
  { key: 'royaume', name: 'Royaume', proName: 'Projet', role: 'Organisation et projets', route: '/royaume', icon: 'crown', shortcut: 'r' },
  {
    key: 'blueprint',
    name: 'Blueprint',
    proName: 'Profil et règles',
    role: 'Contexte et règles',
    route: '/blueprint',
    icon: 'plan',
    shortcut: 'b',
  },
  { key: 'guilde', name: 'Guilde', proName: 'Cerveaux', role: 'Expertises IA', route: '/guilde', icon: 'guild', shortcut: 'g' },
  {
    key: 'conseil',
    name: 'Conseil',
    proName: 'Consultation',
    role: 'Avis et décisions',
    route: '/conseil',
    icon: 'council',
    shortcut: 'c',
  },
  { key: 'quetes', name: 'Quêtes', proName: 'Tâches', role: 'Missions et tâches', route: '/quetes', icon: 'quest', shortcut: 'q' },
  {
    key: 'bibliotheque',
    name: 'Bibliothèque',
    proName: 'Bibliothèque',
    role: 'Références et packs',
    route: '/bibliotheque',
    icon: 'book',
    shortcut: 'l',
  },
  { key: 'forge', name: 'Forge', proName: 'Réalisation', role: 'Outils et livrables', route: '/forge', icon: 'anvil', shortcut: 'f' },
  { key: 'tour', name: 'Tour de guet', proName: 'Contrôles', role: 'Contrôles et risques', route: '/tour', icon: 'tower', shortcut: 't' },
  {
    key: 'observatoire',
    name: 'Observatoire',
    proName: 'Marché',
    role: 'Veille et marché',
    route: '/observatoire',
    icon: 'telescope',
    shortcut: 'o',
  },
  {
    key: 'documentation',
    name: 'Documentation',
    proName: 'Documentation',
    role: 'Documents et partages',
    route: '/documentation',
    icon: 'scroll',
    shortcut: 'd',
  },
  {
    key: 'chroniques',
    name: 'Chroniques',
    proName: 'Historique',
    role: 'Historique et traces',
    route: '/chroniques',
    icon: 'hourglass',
    shortcut: 'h',
  },
  {
    key: 'intendance',
    name: 'Intendance',
    proName: 'Réglages',
    role: 'Membres et réglages',
    route: '/intendance',
    icon: 'key',
    shortcut: 'i',
  },
  {
    key: 'arsenal',
    name: 'Arsenal',
    proName: 'Fonctionnalités',
    role: 'Outils et connexions MCP',
    route: '/arsenal',
    icon: 'shield',
    shortcut: 'a',
  },
];

export const PLACE_GROUPS = [
  { name: 'Pilotage', keys: ['royaume', 'blueprint', 'conseil', 'quetes', 'forge', 'tour'] },
  { name: 'Ressources', keys: ['bibliotheque', 'guilde', 'observatoire', 'arsenal'] },
  { name: 'Organisation', keys: ['documentation', 'chroniques', 'intendance'] },
] as const satisfies readonly { name: string; keys: readonly PlaceKey[] }[];
