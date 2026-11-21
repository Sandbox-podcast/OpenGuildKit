/** The twelve places, shared by the demo and the project interface. */
import type { PixelIconName } from '@/shared/pixel/icons';
import type { PlaceKey } from '@/shared/pixel/buildings';

export interface Place { key: PlaceKey; name: string; standardName: string; role: string; route: string; icon: PixelIconName; shortcut: string }

export const PLACES: Place[] = [
  { key: 'royaume', name: 'Royaume', standardName: 'Projets', role: 'Organisation et projets', route: '/royaume', icon: 'crown', shortcut: 'r' },
  { key: 'blueprint', name: 'Blueprint', standardName: 'Contexte et règles', role: 'Contexte et règles', route: '/blueprint', icon: 'plan', shortcut: 'b' },
  { key: 'guilde', name: 'Guilde', standardName: 'Expertises IA', role: 'Expertises IA', route: '/guilde', icon: 'guild', shortcut: 'g' },
  { key: 'conseil', name: 'Conseil', standardName: 'Avis et décisions', role: 'Avis et décisions', route: '/conseil', icon: 'council', shortcut: 'c' },
  { key: 'quetes', name: 'Quêtes', standardName: 'Missions', role: 'Missions et tâches', route: '/quetes', icon: 'quest', shortcut: 'q' },
  { key: 'bibliotheque', name: 'Bibliothèque', standardName: 'Références', role: 'Références et packs', route: '/bibliotheque', icon: 'book', shortcut: 'l' },
  { key: 'forge', name: 'Forge', standardName: 'Livrables et outils', role: 'Outils et livrables', route: '/forge', icon: 'anvil', shortcut: 'f' },
  { key: 'tour', name: 'Tour de guet', standardName: 'Contrôles', role: 'Contrôles et risques', route: '/tour', icon: 'tower', shortcut: 't' },
  { key: 'observatoire', name: 'Observatoire', standardName: 'Veille', role: 'Veille et marché', route: '/observatoire', icon: 'telescope', shortcut: 'o' },
  { key: 'documentation', name: 'Documentation', standardName: 'Documents', role: 'Documents et partages', route: '/documentation', icon: 'scroll', shortcut: 'd' },
  { key: 'chroniques', name: 'Chroniques', standardName: 'Historique', role: 'Historique et traces', route: '/chroniques', icon: 'hourglass', shortcut: 'h' },
  { key: 'intendance', name: 'Intendance', standardName: 'Paramètres', role: 'Membres et réglages', route: '/intendance', icon: 'key', shortcut: 'i' },
];


export const PLACE_GROUPS = [
  { name: 'Pilotage', keys: ['royaume', 'blueprint', 'conseil', 'quetes', 'forge', 'tour'] },
  { name: 'Ressources', keys: ['bibliotheque', 'guilde', 'observatoire'] },
  { name: 'Organisation', keys: ['documentation', 'chroniques', 'intendance'] },
] as const satisfies readonly { name: string; keys: readonly PlaceKey[] }[];
