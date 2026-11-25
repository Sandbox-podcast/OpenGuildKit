/**
 * Arsenal: turn features on or off. A feature is a tool the team works with, or one of its three best-known
 * alternatives; turning it on adds the tool to the profile (openguildkit features enable), with who and why.
 * Its MCP server is then connected from the Forge, by tools plan and tools apply.
 */
import { useState } from 'react';
import { Notice, Panel } from '@/shared/ui/core';
import { Dialog } from '@/shared/ui/overlay';
import { FeatureCards, purposeLabel, type Feature, type FeatureOption } from '@/shared/featureCards';
import { useAction, useCli } from '../query';
import { ActionForm, Q, useRemembered } from '../parts';

export function Arsenal() {
  const features = useCli<Feature[]>(['features', 'list', '--json']);
  const [picked, setPicked] = useState<{ option: FeatureOption; feature: Feature } | null>(null);
  const [by, setBy] = useRemembered('decider');
  const { act, busy } = useAction();
  const enabling = picked ? !picked.option.enabled : true;
  return (
    <div className="page-grid">
      <Notice tone="info">
        Choisis les outils de l’équipe : chaque fonctionnalité propose un outil de référence et ses trois alternatives les plus connues.
        Activer un outil l’ajoute au profil du projet, avec qui et pourquoi. Pour brancher son serveur MCP sur l’agent, passe ensuite par la <a href="#/forge/outils">Forge, onglet Outils et MCP</a>.
      </Notice>
      <Q q={features}>{(list) => <>
        <Panel title={`${list.filter((f) => f.enabled).length} fonctionnalité(s) active(s) sur ${list.length}`}>
          <p className="small muted">Un outil partagé active toutes les fonctionnalités qui l’utilisent. Le Blueprint garde la liste des outils du profil.</p>
        </Panel>
        <FeatureCards features={list} busy={busy !== null} onToggle={(option, feature) => setPicked({ option, feature })} />
      </>}</Q>
      <Dialog open={!!picked} onClose={() => setPicked(null)} title={picked ? `${enabling ? 'Activer' : 'Désactiver'} ${picked.option.title}` : ''}>
        {picked && <>
          <p className="small">{purposeLabel(picked.feature.purpose)} : {picked.option.tool_title ?? picked.option.tool} {enabling ? 'rejoint' : 'quitte'} la liste des outils du profil. Le changement est inscrit dans l’historique du profil et dans AGENTS.md.</p>
          <ActionForm busy={busy !== null} submit={enabling ? 'Activer' : 'Désactiver'} initial={{ by }} fields={[
            { name: 'by', label: 'Personne qui décide', required: true },
            { name: 'reason', label: 'Pourquoi', required: true, placeholder: enabling ? 'L’équipe suit ses tickets dans cet outil' : 'L’équipe ne s’en sert plus' },
          ]} onSubmit={async (v) => {
            setBy(v.by);
            const done = await act(['features', enabling ? 'enable' : 'disable', picked.option.tool, '--by', v.by, '--reason', v.reason],
              { success: enabling ? 'Fonctionnalité activée' : 'Fonctionnalité désactivée' });
            if (done) setPicked(null);
          }} />
        </>}
      </Dialog>
    </div>
  );
}
