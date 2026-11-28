/**
 * Arsenal: turn features on or off. A feature is a tool the team works with, or one of its three best-known
 * alternatives; turning it on adds the tool to the profile (openguildkit features enable), with who and why.
 * Its MCP server is then connected from the Forge, by tools plan and tools apply. Turning it off leaves that
 * connection: the page then names it with the command that removes it, as features disable does.
 */
import { useState } from 'react';
import { Notice, Panel } from '@/shared/ui/core';
import { Dialog } from '@/shared/ui/overlay';
import { FeatureCards, purposeLabel, type Feature, type FeatureOption } from '@/shared/featureCards';
import { terminalCommand } from '../api';
import { useProfile } from '../data';
import { useAction, useCli } from '../query';
import { ActionForm, CommandLine, Q, useRemembered } from '../parts';

/** A row of tools status --json; an unconnected request has a reason and no connection. */
interface Connection { key: string; host: string; mode: string; covers: string[]; configured: boolean; changed: boolean; reason?: string }

export function Arsenal() {
  const features = useCli<Feature[]>(['features', 'list', '--json']);
  const [picked, setPicked] = useState<{ option: FeatureOption; feature: Feature } | null>(null);
  const [by, setBy] = useRemembered('decider');
  const { act, busy } = useAction();
  const enabling = picked ? !picked.option.enabled : true;
  // The option last turned off: the connections tools apply wrote for it stay until tools remove.
  const [left, setLeft] = useState<FeatureOption | null>(null);
  const status = useCli<Connection[]>(left ? ['tools', 'status', '--json'] : null);
  const profile = useProfile();
  const still = left ? (status.data ?? []).filter((c) => !c.reason && (c.configured || c.changed) && c.covers.includes(left.tool)) : [];
  return (
    <div className="page-grid">
      <Notice tone="info">
        Choisis les outils de l’équipe : chaque fonctionnalité propose un outil de référence et ses trois alternatives les plus connues.
        Activer un outil l’ajoute au profil du projet, avec qui et pourquoi. Pour brancher son serveur MCP sur l’agent, passe ensuite par la <a href="#/forge/outils">Forge, onglet Outils et MCP</a>.
      </Notice>
      {left && still.map((c) => (
        <Notice key={`${c.host}:${c.key}`} tone="warn" title={`${left.title} reste connecté à l’agent`}>
          Le serveur MCP {c.key} ({c.host}, {c.mode === 'mock' ? 'simulation' : 'serveur réel'}) donne toujours à l’agent l’accès à {c.covers.map((tool) => (tool === left.tool ? left.title : tool)).join(', ')} : désactiver la fonctionnalité ne retire pas la connexion. Pour la retirer, lance cette commande ou « Retirer » dans la <a href="#/forge/outils">Forge, onglet Outils et MCP</a>.
          <CommandLine command={terminalCommand(['tools', 'remove', c.key, ...(c.host === profile.data?.host ? [] : ['--host', c.host])])} label="Commande qui retire la connexion" />
        </Notice>
      ))}
      <Q q={features}>{(list) => <>
        <Panel title={`${list.filter((f) => f.enabled).length} fonctionnalité(s) active(s) sur ${list.length}`}>
          <p className="small muted">Un outil partagé active toutes les fonctionnalités qui l’utilisent. Le Blueprint garde la liste des outils du profil.</p>
        </Panel>
        <FeatureCards features={list} busy={busy !== null} onToggle={(option, feature) => setPicked({ option, feature })} />
      </>}</Q>
      <Dialog open={!!picked} onClose={() => setPicked(null)} title={picked ? `${enabling ? 'Activer' : 'Désactiver'} ${picked.option.title}` : ''}>
        {picked && <>
          <p className="small">{purposeLabel(picked.feature.purpose)} : {picked.option.tool_title ?? picked.option.tool} {enabling ? 'rejoint' : 'quitte'} la liste des outils du profil. Le changement est inscrit dans l’historique du profil.</p>
          <ActionForm busy={busy !== null} submit={enabling ? 'Activer' : 'Désactiver'} initial={{ by }} fields={[
            { name: 'by', label: 'Personne qui décide', required: true },
            { name: 'reason', label: 'Pourquoi', required: true, placeholder: enabling ? 'L’équipe suit ses tickets dans cet outil' : 'L’équipe ne s’en sert plus' },
          ]} onSubmit={async (v) => {
            setBy(v.by!);
            const done = await act(['features', enabling ? 'enable' : 'disable', picked.option.tool, '--by', v.by!, '--reason', v.reason!],
              { success: enabling ? 'Fonctionnalité activée' : 'Fonctionnalité désactivée' });
            if (done) { setLeft(enabling ? null : picked.option); setPicked(null); }
          }} />
        </>}
      </Dialog>
    </div>
  );
}
