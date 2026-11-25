/** Arsenal of the demo: the features of the CLI registry, turned on and off in this browser only. */
import { useState } from 'react';
import { Notice } from '@/shared/ui/core';
import { FeatureCards, type Feature } from '@/shared/featureCards';

interface CliOption { tool: string; as?: string }
interface CliTool { id: string; title: string; vendor: string; servers: unknown[] }

const featureFile = import.meta.glob<{ features: { id: string; purpose: string; lead: CliOption; alternatives: CliOption[] }[] }>(
  '../../../../src/openguildkit/registry/features/features.json', { eager: true, import: 'default' });
const toolFiles = import.meta.glob<{ tools: CliTool[] }>('../../../../src/openguildkit/registry/tools/*.json', { eager: true, import: 'default' });
const TOOLS: Record<string, CliTool> = Object.fromEntries(Object.values(toolFiles).flatMap((f) => f.tools).map((t) => [t.id, t]));
const FEATURES = Object.values(featureFile)[0]?.features ?? [];
/** Atelier Nova already works with these tools. */
const NOVA = ['jira', 'slack', 'github'];

export function ArsenalSpace() {
  const [on, setOn] = useState<string[]>(NOVA);
  const features: Feature[] = FEATURES.map((f) => {
    const options = [f.lead, ...f.alternatives].map((o) => ({
      tool: o.tool, title: o.as ?? TOOLS[o.tool]?.title ?? o.tool, vendor: TOOLS[o.tool]?.vendor ?? '',
      servers: TOOLS[o.tool]?.servers.length ?? 0, enabled: on.includes(o.tool),
    }));
    return { id: f.id, purpose: f.purpose, enabled: options.some((o) => o.enabled), options };
  });
  return (
    <div className="page-grid">
      <Notice tone="info">Démonstration : chaque fonctionnalité propose un outil de référence et ses trois alternatives les plus connues. Dans un projet, activer un outil l’ajoute au profil (<code>openguildkit features enable</code>). Un outil partagé est actif dans toutes les fonctionnalités qui l’utilisent. Son serveur MCP se branche ensuite depuis la Forge.</Notice>
      <FeatureCards features={features} onToggle={(option) => setOn((list) => list.includes(option.tool) ? list.filter((t) => t !== option.tool) : [...list, option.tool])} />
    </div>
  );
}
