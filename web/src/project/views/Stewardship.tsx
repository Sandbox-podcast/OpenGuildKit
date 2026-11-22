/** Intendance: host settings and agent files, catalog upgrades, and how the interface itself works. */
import { Badge, Button, Notice, Panel, Tabs } from '@/shared/ui/core';
import { currentSession, terminalCommand } from '../api';
import { onlyTasksFail, useCheck, useHost, useProfile, useTasks, useUpdate } from '../data';
import { useAction } from '../query';
import { hostControl } from '../labels';
import { CheckNotice, CommandLine, JsonDetails, Pre, Q, TaskLink } from '../parts';
import { setPrefs, usePrefs } from '../prefs';
import { setSingleKeyShortcuts, useSingleKeyShortcuts } from '@/shared/shortcuts';

export function Stewardship({ tab = 'hote' }: { tab?: string }) {
  return (
    <div className="page-grid">
      <Tabs label="Intendance" value={tab} onChange={(t) => { window.location.hash = `#/intendance/${t}`; }} tabs={[
        { id: 'hote', label: 'Hôte de l’agent', icon: 'key' },
        { id: 'catalogue', label: 'Catalogue', icon: 'download' },
        { id: 'interface', label: 'Interface', icon: 'settings' },
      ]} />
      {tab === 'catalogue' ? <CatalogUpdate /> : tab === 'interface' ? <Interface /> : <Host />}
    </div>
  );
}

function Host() {
  const host = useHost();
  const tasks = useTasks();
  const check = useCheck();
  const profile = useProfile();
  const { act, busy } = useAction();
  return (
    <div className="page-grid">
      <Panel title="Règles que l’hôte fait respecter" actions={<Button variant="primary" size="small" busy={busy !== null} onClick={() => void act(['host', 'apply'], { success: 'Réglages de l’hôte écrits' })}>Écrire les réglages de l’hôte</Button>}>
        <p className="small muted"><code>host apply</code> écrit les réglages de {profile.data?.host ?? 'Claude Code ou Codex'} : la politique de recherche, et l’agent tenu à l’écart de la commande de validation. <code>host check</code> dit quelles règles restent de simples consignes.</p>
        <Q q={host}>{(list) => <ul className="plain stack tight">{list.map((c) => { const l = hostControl(c.status); return <li key={c.id} className="card"><span className="row between"><strong>{c.title}</strong><Badge tone={l.tone} icon={l.icon}>{l.label}</Badge></span><span className="small muted">{c.detail}</span></li>; })}</ul>}</Q>
      </Panel>
      <div className="grid-2">
        <Panel title="Fichiers de l’agent">
          <p className="small">Installe le skill OpenGuildKit et le sous-agent de revue de cette version dans le projet.</p>
          <div className="row">
            <Button busy={busy !== null} onClick={() => void act(['integrations', '--host', 'claude-code'], { success: 'Fichiers Claude Code installés' })}>Claude Code</Button>
            <Button busy={busy !== null} onClick={() => void act(['integrations', '--host', 'codex'], { success: 'Fichiers Codex installés' })}>Codex</Button>
            <Button variant="ghost" busy={busy !== null} onClick={() => void act(['integrations', '--host', 'claude-code', '--force'], { success: 'Fichiers remplacés, copies .previous gardées' })}>Remplacer les fichiers modifiés</Button>
          </div>
          <p className="tiny muted">Pour tous vos projets, installez-les dans votre dossier personnel depuis un terminal :</p>
          <CommandLine command="openguildkit integrations --host claude-code --user" />
        </Panel>
        <Panel title="Cohérence des instructions" actions={check.data && check.data.code !== 0 && onlyTasksFail(check.data) ? undefined : <Button size="small" busy={busy !== null} onClick={() => void act(['sync'], { success: 'Instructions synchronisées' })}>Synchroniser</Button>}>
          <Q q={check}>{(r) => <CheckNotice result={r} tasks={tasks.data ?? []} />}</Q>
        </Panel>
      </div>
    </div>
  );
}

function CatalogUpdate() {
  const update = useUpdate();
  const { act, busy } = useAction();
  return (
    <Panel title="Mises à jour du catalogue" actions={<Button variant="primary" size="small" busy={busy !== null} disabled={!update.data?.changes.length} onClick={() => void act(['update', '--apply'], { success: 'Catalogue adopté' })}>Adopter</Button>}>
      <p className="small muted">Les règles du projet sont verrouillées dans <code>catalog.lock.json</code> : installer une version plus récente d’OpenGuildKit ne les change pas. <code>update</code> liste, règle par règle, ce que le catalogue installé ajouterait, retirerait ou modifierait ; <code>update --apply</code> l’adopte, réécrit les instructions et nomme les quêtes consultées sous les règles précédentes.</p>
      <Q q={update}>{(u) => <>
        {u.changes.length === 0 ? <Notice tone="success">Le projet suit le catalogue installé.</Notice> : <JsonDetails data={u.changes} label={`${u.changes.length} évolution(s)`} />}
        {u.conflicts.length > 0 && <Notice tone="danger" title="Conflits :"><Pre text={JSON.stringify(u.conflicts, null, 2)} /></Notice>}
        {u.stale_tasks.length > 0 && <Notice tone="warn" title={u.applied ? 'Quêtes consultées sous les règles précédentes :' : 'Adopter ces règles laisserait ces quêtes consultées sous les précédentes :'}>
          <ul>{u.stale_tasks.map((t) => <li key={t.id}><TaskLink id={t.id} /> ({t.status}) : {t.step}</li>)}</ul>
          Une quête terminée garde son enregistrement comme historique.</Notice>}
      </>}</Q>
    </Panel>
  );
}

function Interface() {
  const session = currentSession();
  const prefs = usePrefs();
  const single = useSingleKeyShortcuts();
  return (
    <div className="grid-2">
      <Panel title="Ce que fait cette interface">
        <ul className="small">
          <li>Elle tourne sur votre poste, sur 127.0.0.1, et lance les mêmes commandes que vous tapez, une à la fois, dans le projet <code>{session?.project.root}</code>.</li>
          <li>Elle n’enregistre jamais ce qui demande une personne devant un terminal : {session?.human_only.join(', ')}. Elle affiche la commande à taper.</li>
          <li>Les chemins restent dans le projet. Elle ne lit pas <code>.git</code>, les fichiers <code>.env</code> ni ce qui ressemble à un secret.</li>
          <li>Elle n’ouvre aucune connexion vers l’extérieur et n’appelle aucune IA : votre agent reste celui qui rédige les avis.</li>
        </ul>
        <p className="small">Relancer : <code>{terminalCommand(['ui'])}</code></p>
      </Panel>
      <Panel title="Affichage">
        <div className="row"><Button variant={prefs.mode === 'explorer' ? 'primary' : undefined} onClick={() => setPrefs({ mode: 'explorer' })}>RPG</Button><Button variant={prefs.mode === 'focus' ? 'primary' : undefined} onClick={() => setPrefs({ mode: 'focus' })}>Pro</Button></div>
        <label className="row small pref-check"><input type="checkbox" checked={prefs.motion === 'reduced'} onChange={(e) => setPrefs({ motion: e.target.checked ? 'reduced' : 'system' })} /> Mouvement réduit</label>
        <label className="row small pref-check"><input type="checkbox" checked={single} onChange={(e) => setSingleKeyShortcuts(e.target.checked)} /> Raccourcis à une touche : <kbd>/</kbd> recherche, <kbd>g</kbd> puis une lettre change de lieu, <kbd>m</kbd> change de style</label>
        <p className="tiny muted"><kbd>Ctrl</kbd> + <kbd>K</kbd> ouvre la recherche dans tous les cas. Le choix est gardé dans ce navigateur.</p>
        <p className="small">OpenGuildKit {session?.version}.</p>
      </Panel>
    </div>
  );
}
