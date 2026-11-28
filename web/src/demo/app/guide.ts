/**
 * Demonstration guide: the 20 steps of the main journey (brief §10), each checked against the
 * real objects of the workspace. It is a demo aid, separate from business actions.
 */
import { list } from '@/demo/domain/engine';
import { bpVersion, fact, latestResults, shareStatus } from '@/demo/domain/selectors';
import type { AppState, Quest } from '@/demo/domain/types';

export interface GuideStep {
  n: number;
  title: string;
  where: string;
  to: string;
  done: (s: AppState) => boolean;
  hint: string;
}

const exportQuest = (s: AppState): Quest | undefined =>
  list(s, 'quest', s.session.orgId).find((q) => q.projectId === 'prj-export' && q.origin === 'decision');
const approvedDecision = (s: AppState) =>
  list(s, 'decision', s.session.orgId).find((d) => d.councilId === 'cns-export' && (d.status === 'approved' || d.status === 'replaced'));
const questDeliverables = (s: AppState) => {
  const q = exportQuest(s);
  return q ? q.deliverableIds.map((id) => s.db.deliverable[id]).filter(Boolean) : [];
};
const codeOf = (s: AppState) => questDeliverables(s).find((d) => d.type === 'code');
const isoResults = (s: AppState) => {
  const c = codeOf(s);
  return c
    ? list(s, 'result', s.session.orgId).filter((r) => r.controlId === 'ctl-isolation' && r.inputs.subject?.deliverableId === c.id)
    : [];
};

export const GUIDE: GuideStep[] = [
  {
    n: 1,
    title: 'Ouvrir l’organisation SaaS B2B',
    where: 'Entrée',
    to: '/entree',
    done: (s) => s.session.orgId === 'org-nova',
    hint: 'Chargez « Atelier Nova » depuis l’écran d’entrée.',
  },
  {
    n: 2,
    title: 'Sélectionner Atlas CRM',
    where: 'Royaume',
    to: '/projets/prj-export',
    done: (s) => s.session.projectId === 'prj-export',
    hint: 'Projet « Export des données clients » du produit Atlas CRM.',
  },
  {
    n: 3,
    title: 'Lire le contexte du Blueprint',
    where: 'Blueprint',
    to: '/blueprint/structure',
    done: (s) => !!fact(bpVersion(s, s.session.orgId, s.db.project['prj-export']?.blueprintVersion), 'tenancy'),
    hint: 'Multi-clients, données personnelles, API, stockage, responsabilités.',
  },
  {
    n: 4,
    title: 'Résoudre l’inconnue de durée de disponibilité',
    where: 'Blueprint',
    to: '/blueprint/structure',
    done: (s) =>
      fact(bpVersion(s, s.session.orgId, s.db.project['prj-export']?.blueprintVersion), 'export.retention')?.provenance === 'declared',
    hint: 'Renseignez-la dans la v3, arbitrez le conflit de branches, publiez par une autre personne, puis adoptez la version sur le projet.',
  },
  {
    n: 5,
    title: 'Valider les références suggérées',
    where: 'Bibliothèque',
    to: '/bibliotheque?projet=prj-export&statut=suggestion',
    done: (s) => list(s, 'applicability', s.session.orgId).filter((a) => a.projectId === 'prj-export' && a.validated).length >= 3,
    hint: 'Une suggestion d’agent reste une proposition tant qu’un humain ne l’a pas validée.',
  },
  {
    n: 6,
    title: 'Mobiliser les expertises',
    where: 'Guilde',
    to: '/guilde',
    done: (s) => (s.db.council['cns-export']?.participantIds.length ?? 0) >= 6,
    hint: 'Produit, design, engineering, sécurité, vie privée et performance.',
  },
  {
    n: 7,
    title: 'Lancer le Conseil et comparer les options',
    where: 'Conseil',
    to: '/conseil/cns-export',
    done: (s) => (s.db.council['cns-export']?.contributions.length ?? 0) >= 6,
    hint: 'Export immédiat limité ou traitement asynchrone.',
  },
  {
    n: 8,
    title: 'Annoter les désaccords',
    where: 'Conseil',
    to: '/conseil/cns-export',
    done: (s) => (s.db.council['cns-export']?.annotations.length ?? 0) > 0,
    hint: 'Simplicité, délai, isolation, permission, conservation, traçabilité.',
  },
  {
    n: 9,
    title: 'Arbitrer et motiver la décision',
    where: 'Conseil',
    to: '/conseil/cns-export',
    done: (s) => !!approvedDecision(s),
    hint: 'Un approbateur humain distinct valide la décision.',
  },
  { n: 10, title: 'Créer la quête', where: 'Quêtes', to: '/quetes', done: (s) => !!exportQuest(s), hint: 'La conversion est idempotente.' },
  {
    n: 11,
    title: 'Préparer les livrables',
    where: 'Forge',
    to: '/forge/studio',
    done: (s) => questDeliverables(s).length >= 5,
    hint: 'Spécification, interface, API, tests, documentation.',
  },
  {
    n: 12,
    title: 'Révéler le défaut d’isolation',
    where: 'Tour de guet',
    to: '/tour/controles',
    done: (s) => isoResults(s).some((r) => r.outcome === 'failed'),
    hint: 'Lancez CTL-ISO sur la proposition de code.',
  },
  {
    n: 13,
    title: 'Rattacher une correction au constat',
    where: 'Tour de guet',
    to: '/tour/constats',
    done: (s) => list(s, 'finding', s.session.orgId).some((f) => f.projectId === 'prj-export' && !!f.questId),
    hint: 'Créez ou rattachez la quête corrective.',
  },
  {
    n: 14,
    title: 'Produire le correctif (nouvelle version)',
    where: 'Forge',
    to: '/forge/studio',
    done: (s) => (codeOf(s)?.current ?? 0) >= 2,
    hint: 'L’ancienne preuve devient « À réévaluer ».',
  },
  {
    n: 15,
    title: 'Relancer les contrôles',
    where: 'Tour de guet',
    to: '/tour/controles',
    done: (s) => latestResults(s, 'prj-export').some((r) => r.controlId === 'ctl-isolation' && r.outcome === 'passed'),
    hint: 'Nouveaux résultats et nouvelles preuves.',
  },
  {
    n: 16,
    title: 'Faire valider par un approbateur distinct',
    where: 'Tour de guet',
    to: '/tour/revues',
    done: (s) => {
      const q = exportQuest(s);
      return !!q && list(s, 'approval', s.session.orgId).some((a) => a.subject.id === q.id && a.status === 'approved');
    },
    hint: 'Changez d’acteur dans la démonstration : Inès Morel approuve.',
  },
  {
    n: 17,
    title: 'Clôturer et publier la documentation',
    where: 'Quêtes',
    to: '/quetes',
    done: (s) => exportQuest(s)?.status === 'done' && questDeliverables(s).some((d) => d.type === 'doc' && d.status === 'published'),
    hint: 'La clôture vérifie critères, livrables, contrôles et validations.',
  },
  {
    n: 18,
    title: 'Ouvrir puis révoquer un partage local',
    where: 'Documentation',
    to: '/documentation/partages',
    done: (s) =>
      list(s, 'share', s.session.orgId).some(
        (sh) => questDeliverables(s).some((d) => d.id === sh.deliverableId) && shareStatus(s, sh) === 'revoked' && sh.accessLog.length > 0,
      ),
    hint: 'Lien de démonstration local, aucun courriel envoyé.',
  },
  {
    n: 19,
    title: 'Reconstruire la chaîne dans les Chroniques',
    where: 'Chroniques',
    to: '/chroniques/trace',
    done: (s) => exportQuest(s)?.status === 'done',
    hint: 'Depuis le guide publié, remontez à la décision et au Blueprint.',
  },
  {
    n: 20,
    title: 'Faire évoluer le Blueprint et réexaminer',
    where: 'Blueprint',
    to: '/blueprint/impacts',
    done: (s) => list(s, 'review', s.session.orgId).some((r) => r.projectId === 'prj-export'),
    hint: 'Adoptez une nouvelle version : les objets concernés passent « à réexaminer ».',
  },
];
