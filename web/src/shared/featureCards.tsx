/** The Arsenal's cards, shared by the demo and the project: one feature, its lead tool and three alternatives. */
import { Badge, Button, Panel } from '@/shared/ui/core';

export interface FeatureOption {
  tool: string;
  tool_title?: string;
  title: string;
  vendor: string;
  servers: number;
  enabled: boolean;
}
export interface Feature {
  id: string;
  purpose: string;
  enabled: boolean;
  options: FeatureOption[];
}

/** The registry writes purposes in English; the page shows them in French. */
const PURPOSE: Record<string, string> = {
  'Documentation portal': 'Portail de documentation',
  'Issue tracking': 'Suivi des tickets',
  'Team wiki': 'Wiki d’équipe',
  'Meetings and chat': 'Réunions et discussions',
  'Team messaging': 'Messagerie d’équipe',
  Payroll: 'Paie',
  'HR management': 'Gestion RH',
  'Time tracking': 'Suivi des temps',
  'Source control': 'Gestion du code source',
  'Container registry': 'Registre de conteneurs',
  'Package registry': 'Registre de paquets',
  'Container management': 'Gestion des conteneurs',
  'Identity and access': 'Identités et accès',
  'Development environment': 'Environnement de développement',
  'Dashboards and metrics': 'Tableaux de bord et métriques',
  'Logs and search': 'Journaux et recherche',
  'Application performance monitoring': 'Performance applicative (APM)',
  'API management': 'Gestion des API',
  'Browser debugging': 'Débogage du navigateur',
  'Large-scale data processing': 'Traitement de données à grande échelle',
};
export const purposeLabel = (purpose: string) => PURPOSE[purpose] ?? purpose;

export function FeatureCards({
  features,
  busy,
  onToggle,
}: {
  features: Feature[];
  busy?: boolean;
  onToggle: (option: FeatureOption, feature: Feature) => void;
}) {
  return (
    <div className="grid-3">
      {features.map((feature) => (
        <Panel
          key={feature.id}
          title={purposeLabel(feature.purpose)}
          tone={feature.enabled ? 'success' : undefined}
          actions={
            feature.enabled ? (
              <Badge tone="success" icon="check">
                Active
              </Badge>
            ) : undefined
          }
        >
          <ul className="plain stack tight">
            {feature.options.map((option, index) => (
              <li key={option.tool} className="feature-option">
                <span>
                  <strong lang="en">{option.title}</strong>{' '}
                  <span className="tiny muted">{index === 0 ? 'outil de référence' : 'alternative'}</span>
                  <span className="tiny muted block">
                    {option.servers ? `${option.servers} serveur(s) MCP au registre` : 'Pas de serveur MCP connu : API seulement'}
                  </span>
                </span>
                <Button
                  size="small"
                  variant={option.enabled ? 'ghost' : 'primary'}
                  busy={busy}
                  aria-label={`${option.enabled ? 'Désactiver' : 'Activer'} ${option.title}`}
                  onClick={() => onToggle(option, feature)}
                >
                  {option.enabled ? 'Désactiver' : 'Activer'}
                </Button>
              </li>
            ))}
          </ul>
        </Panel>
      ))}
    </div>
  );
}
