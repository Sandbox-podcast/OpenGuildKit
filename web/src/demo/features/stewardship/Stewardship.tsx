/** Intendance: members, roles matrix, integrations, models, budgets, notifications, retention, language, preferences, data and demo controls (brief §5.12). */
import { useRef, useState } from 'react';
import { dispatch, replaceState, useAppState } from '@/demo/app/store';
import { navigate } from '@/shared/router';
import { cmd } from '@/demo/domain/commands';
import { list, nowOf } from '@/demo/domain/engine';
import { AGENT_CAPABILITIES, CAPABILITIES, ROLE_CAPABILITIES, ROLES, type Capability, type RoleId } from '@/demo/domain/permissions';
import { effectiveExceptionStatus, fmtDate, shareStatus } from '@/demo/domain/selectors';
import { emptyState } from '@/demo/domain/state';
import type { Preferences } from '@/demo/domain/types';
import { applyBackup, backupOf, clearWorkspace, previewBackup, type BackupPreview } from '@/demo/adapters/storage';
import { download } from '@/demo/adapters/export';
import { Icon } from '@/shared/pixel/icons';
import { Badge, Button, Checkbox, Notice, Panel, Progress, Select, Tabs, TextField } from '@/shared/ui/core';
import { ConfirmDialog } from '@/shared/ui/overlay';
import { CmdButton, Person, Portrait, StatusBadge } from '@/demo/ui/domain';
import './members.css';

const TABS = [
  ['membres', 'Membres', 'user'], ['roles', 'Rôles et capacités', 'lock'], ['integrations', 'Intégrations', 'link'], ['modeles', 'Modèles et budgets', 'ai'],
  ['notifications', 'Notifications', 'bell'], ['conservation', 'Conservation et langue', 'archive'], ['preferences', 'Préférences et accessibilité', 'settings'],
  ['donnees', 'Import, export, réinitialisation', 'download'], ['demo', 'Démonstration', 'dice'],
] as const;

export function StewardshipSpace({ tab = 'membres' }: { tab?: string }) {
  return (
    <div className="stack">
      <Tabs label="Intendance" value={tab} onChange={(t) => navigate(`/intendance/${t}`)} tabs={TABS.map(([id, label, icon]) => ({ id, label, icon: icon as never }))} />
      {tab === 'membres' && <Members />}
      {tab === 'roles' && <RolesMatrix />}
      {tab === 'integrations' && <Integrations />}
      {tab === 'modeles' && <ModelsBudgets />}
      {tab === 'notifications' && <Notifications />}
      {tab === 'conservation' && <Retention />}
      {tab === 'preferences' && <Prefs />}
      {tab === 'donnees' && <Data />}
      {tab === 'demo' && <DemoControls />}
    </div>
  );
}

function Members() {
  const s = useAppState();
  const members = list(s, 'member', s.session.orgId);
  const [v, setV] = useState({ name: '', title: '', role: 'contributor' as RoleId });
  return (
    <div className="grid-2">
      <Panel title={`Membres fictifs (${new Set(members.map((m) => m.userId)).size})`}>
        <table className="data responsive"><thead><tr><th>Personne</th><th>Rôle</th><th>Périmètre</th><th>Actions</th></tr></thead>
          <tbody>{members.map((m) => (
            <tr key={m.id}>
              <td data-label="Personne"><Person id={m.userId} /><span className="tiny muted" style={{ display: 'block' }}>{s.users[m.userId]?.title}</span></td>
              <td data-label="Rôle">
                <select className="member-role-select" aria-label={`Rôle de ${s.users[m.userId]?.name}`} value={m.role} onChange={(e) => dispatch(cmd.changeRole, { memberId: m.id, role: e.target.value as RoleId }, { success: 'Rôle modifié' })}>
                  {Object.entries(ROLES).map(([k, r]) => <option key={k} value={k}>{r.label}</option>)}
                </select>
              </td>
              <td data-label="Périmètre">{m.projectId ? s.db.project[m.projectId]?.name : 'Toute l’organisation'}</td>
              <td data-label="Actions"><CmdButton def={cmd.removeMember} payload={{ memberId: m.id, reason: '' }} size="small" variant="ghost" icon="trash" showReason={false} success="Membre retiré" confirm={{ title: `Retirer ${s.users[m.userId]?.name}`, needsReason: true, danger: true, label: 'Retirer' }}>Retirer</CmdButton></td>
            </tr>
          ))}</tbody></table>
        <p className="tiny muted">Les identités sont fictives. Aucune invitation n’est envoyée. La sélection de l’acteur courant est une fonction de démonstration (onglet Démonstration).</p>
      </Panel>
      <Panel title="Ajouter un membre fictif">
        <TextField label="Nom" value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />
        <TextField label="Fonction" value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} />
        <Select label="Rôle" value={v.role} onChange={(e) => setV({ ...v, role: e.target.value as RoleId })} options={Object.entries(ROLES).map(([k, r]) => ({ value: k, label: r.label }))} />
        <CmdButton def={cmd.addMember} payload={v} variant="primary" icon="plus" success="Membre ajouté (aucune invitation envoyée)" onDone={() => setV({ name: '', title: '', role: 'contributor' })}>Ajouter</CmdButton>
      </Panel>
    </div>
  );
}

export function RolesMatrix() {
  const caps = Object.keys(CAPABILITIES) as Capability[];
  return (
    <Panel title="Matrice des rôles et capacités">
      <p className="small muted">Les commandes, boutons, raccourcis et transitions utilisent la même décision d’autorisation. Un rôle ne contourne jamais une règle métier non dérogeable ni la séparation auteur-approbateur. Ces rôles sont appliqués dans le domaine simulé ; ce n’est pas une isolation serveur.</p>
      <div className="table-wrap">
        <table className="data">
          <thead><tr><th>Capacité</th>{Object.values(ROLES).map((r) => <th key={r.short}>{r.short}</th>)}<th>Agent IA</th></tr></thead>
          <tbody>{caps.map((c) => (
            <tr key={c}><td>{CAPABILITIES[c]}</td>{(Object.keys(ROLES) as RoleId[]).map((r) => <td key={r}>{ROLE_CAPABILITIES[r].includes(c) ? <span style={{ color: 'var(--success)' }}><Icon name="check" size={12} label="autorisé" /></span> : <span style={{ color: 'var(--muted)' }}><Icon name="cross" size={12} label="refusé" /></span>}</td>)}<td>{AGENT_CAPABILITIES.includes(c) ? <span style={{ color: 'var(--success)' }}><Icon name="check" size={12} label="autorisé" /></span> : <span style={{ color: 'var(--muted)' }}><Icon name="cross" size={12} label="refusé" /></span>}</td></tr>
          ))}</tbody>
        </table>
      </div>
      <p className="small" style={{ marginTop: 8 }}>Règles supplémentaires : la publication d’une version du Blueprint (sauf la première) et toute approbation exigent une personne distincte de l’auteur ; un agent ne peut ni approuver, ni publier, ni modifier ses propres outils.</p>
    </Panel>
  );
}

function Integrations() {
  const s = useAppState();
  const ints = list(s, 'integration', s.session.orgId);
  const [acc, setAcc] = useState<Record<string, string>>({});
  return (
    <Panel title="Intégrations de démonstration">
      <Notice tone="warn">Aucune connexion réelle : les identifiants saisis sont fictifs et ne quittent pas ce navigateur. Les états reproduisent le parcours attendu.</Notice>
      <div className="grid-auto">{ints.map((i) => (
        <div key={i.id} className="card">
          <div className="row between"><strong>{i.name}</strong><StatusBadge kind="integration" state={i.status} /></div>
          <p className="small muted" style={{ margin: '4px 0' }}>{i.category} — {i.detail}</p>
          {i.account && <p className="tiny">Compte de démonstration : <code>{i.account}</code></p>}
          <p className="tiny muted">Dernier changement : {fmtDate(i.changedAt, true)}</p>
          <div className="row">
            {['not_configured', 'disconnected'].includes(i.status) && <><TextField label="Identifiant fictif" value={acc[i.id] ?? ''} onChange={(e) => setAcc({ ...acc, [i.id]: e.target.value })} /><CmdButton def={cmd.setIntegration} payload={{ id: i.id, action: 'connect', account: acc[i.id] ?? '' }} size="small" variant="primary" success="Connexion de démonstration en cours">Connecter</CmdButton></>}
            {['error', 'expired'].includes(i.status) && <CmdButton def={cmd.setIntegration} payload={{ id: i.id, action: 'retry' }} size="small" success="Nouvelle tentative de connexion">Réessayer</CmdButton>}
            {['available', 'error', 'expired'].includes(i.status) && <CmdButton def={cmd.setIntegration} payload={{ id: i.id, action: 'disconnect' }} size="small" variant="ghost" success="Intégration déconnectée">Déconnecter</CmdButton>}
          </div>
          {i.status === 'available' && <div className="row tiny" style={{ marginTop: 6 }}><span className="muted">Démonstration :</span><button className="linklike" onClick={() => dispatch(cmd.setIntegration, { id: i.id, action: 'simulate-error' }, {})}>simuler une erreur</button><button className="linklike" onClick={() => dispatch(cmd.setIntegration, { id: i.id, action: 'simulate-expiry' }, {})}>simuler une expiration d’accès</button></div>}
        </div>
      ))}</div>
    </Panel>
  );
}

function ModelsBudgets() {
  const s = useAppState();
  const org = s.orgs[s.session.orgId!];
  const [units, setUnits] = useState(org.settings.budget.monthlyUnits);
  const experts = list(s, 'expert', s.session.orgId);
  return (
    <div className="grid-2">
      <Panel title="Modèles de démonstration">
        <p>{org.settings.demoModel}</p>
        <p className="small muted">Les expertises n’appellent aucun fournisseur d’IA : leurs contributions sont des scénarios préparés et explicitement signalés « Simulation ». Le remplacement par une API réelle est décrit dans <code>web/docs/adaptateurs.md</code>.</p>
      </Panel>
      <Panel title="Budget de simulation">
        <p className="small">Consommé : {org.settings.budget.used} / {org.settings.budget.monthlyUnits} unités</p>
        <Progress value={Math.min(100, Math.round((org.settings.budget.used / Math.max(1, org.settings.budget.monthlyUnits)) * 100))} label="Budget consommé" />
        <div className="row" style={{ marginTop: 8 }}><TextField label="Budget mensuel (unités)" type="number" value={units} onChange={(e) => setUnits(Number(e.target.value))} hint="Un budget atteint interrompt les exécutions avec un motif." /><CmdButton def={cmd.updateSettings} payload={{ patch: { monthlyUnits: units } }} size="small" success="Budget mis à jour">Appliquer</CmdButton></div>
        <h3 style={{ marginTop: 10 }}>Budgets des expertises</h3>
        <ul className="plain stack tight">{experts.map((e) => <li key={e.id} className="row small"><Portrait k={e.key} size={20} />{e.name}<span className="muted">{e.budget.used}/{e.budget.units}</span>{e.budget.used >= e.budget.units && <Badge tone="danger" icon="warn">atteint</Badge>}</li>)}</ul>
      </Panel>
    </div>
  );
}

function Notifications() {
  const s = useAppState();
  const n = s.orgs[s.session.orgId!].settings.notifications;
  const labels: Record<keyof typeof n, string> = { approvals: 'Approbations attendues', controls: 'Contrôles échoués, non concluants et erreurs', exceptions: 'Exceptions expirées et réexamens', watch: 'Signaux de veille à évaluer' };
  return (
    <Panel title="Notifications locales">
      <p className="small muted">Les notifications sont calculées à partir des objets et affichées dans l’application. Aucun courriel ni message n’est envoyé.</p>
      {(Object.keys(labels) as (keyof typeof n)[]).map((k) => <Checkbox key={k} label={labels[k]} checked={n[k]} onChange={(e) => dispatch(cmd.updateSettings, { patch: { notifications: { ...n, [k]: e.target.checked } } }, { success: 'Préférence enregistrée' })} />)}
    </Panel>
  );
}

function Retention() {
  const s = useAppState();
  const [days, setDays] = useState(s.orgs[s.session.orgId!].settings.retentionDays);
  return (
    <div className="grid-2">
      <Panel title="Conservation">
        <TextField label="Durée de conservation des événements (jours)" type="number" value={days} onChange={(e) => setDays(Number(e.target.value))} hint="Paramètre de démonstration : aucune purge automatique n’est appliquée au journal local." />
        <CmdButton def={cmd.updateSettings} payload={{ patch: { retentionDays: days } }} size="small" success="Durée enregistrée">Enregistrer</CmdButton>
      </Panel>
      <Panel title="Langue">
        <Select label="Langue de l’interface" value="fr" onChange={() => undefined} options={[{ value: 'fr', label: 'Français' }]} hint="Cette démonstration est disponible en français uniquement ; le code et le catalogue CLI restent en anglais." />
      </Panel>
    </div>
  );
}

function Prefs() {
  const s = useAppState();
  const set = (p: Partial<Preferences>) => dispatch(cmd.setPreference, p, { success: 'Préférence enregistrée' });
  return (
    <div className="grid-2">
      <Panel title="Préférences visuelles">
        <Select
          label="Style de l'interface"
          value={s.prefs.mode}
          onChange={(e) => set({ mode: e.target.value as Preferences['mode'] })}
          options={[{ value: 'explorer', label: 'RPG : espaces illustrés' }, { value: 'focus', label: 'Pro : espace de travail épuré' }]}
        />
        <Select label="Taille du texte" value={String(s.prefs.textScale)} onChange={(e) => set({ textScale: Number(e.target.value) as Preferences['textScale'] })} options={[{ value: '1', label: 'Standard (16 px)' }, { value: '1.125', label: 'Grande (18 px)' }, { value: '1.25', label: 'Très grande (20 px)' }]} />
        <Checkbox label="Afficher le parcours de démonstration" checked={s.prefs.guideOpen} onChange={(e) => set({ guideOpen: e.target.checked })} />
      </Panel>
      <Panel title="Accessibilité et mouvement">
        <Select label="Animations" value={s.prefs.motion} onChange={(e) => set({ motion: e.target.value as Preferences['motion'] })} options={[{ value: 'system', label: 'Suivre le réglage du système' }, { value: 'reduced', label: 'Réduire les mouvements' }, { value: 'full', label: 'Animations discrètes activées' }]} hint="Aucun flash rapide. Les animations de travail ne jouent que pendant une opération." />
        <Checkbox label="Sons sobres (désactivés par défaut, jamais automatiques)" checked={s.prefs.sound} onChange={(e) => set({ sound: e.target.checked })} />
        <p className="small"><kbd>Ctrl</kbd>+<kbd>K</kbd> ouvre la recherche. <kbd>g</kbd> suivi d'une lettre change de lieu. <kbd>m</kbd> bascule entre RPG et Pro. <kbd>?</kbd> affiche l'aide.</p>
      </Panel>
    </div>
  );
}

function Data() {
  const s = useAppState();
  const fileRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<BackupPreview | null>(null);
  const [mode, setMode] = useState<'merge' | 'replace'>('merge');
  const [confirmReset, setConfirmReset] = useState(false);
  const exportBackup = () => {
    const out = dispatch(cmd.recordExport, { what: 'Sauvegarde complète de l’espace de démonstration', format: 'JSON', count: Object.keys(s.orgs).length }, {});
    if (out.ok) download(`open-guild-kit-sauvegarde-${new Date().toISOString().slice(0, 10)}.json`, 'application/json', backupOf(s));
  };
  return (
    <div className="grid-2">
      <Panel title="Exporter">
        <p className="small muted">Sauvegarde JSON versionnée (<code>ogk-sauvegarde/1</code>) de toutes les organisations de ce navigateur. Aucun secret n’y figure : la démonstration n’en stocke pas.</p>
        <CmdButton def={cmd.recordExport} payload={{ what: 'sauvegarde', format: 'JSON', count: 1 }} variant="primary" icon="download" onRun={exportBackup}>Exporter une sauvegarde</CmdButton>
      </Panel>
      <Panel title="Importer">
        <p className="small muted">Le fichier est validé (format, schéma, relations) et prévisualisé ; un import invalide ne modifie rien.</p>
        <input ref={fileRef} type="file" className="sr-only" id="backup-in" accept=".json,application/json" onChange={async (e) => { const f = e.target.files?.[0]; if (f) setPreview(previewBackup(await f.text(), s)); e.target.value = ''; }} />
        <Button icon="upload" onClick={() => fileRef.current?.click()}>Choisir un fichier…</Button>
        {preview && !preview.ok && <Notice tone="danger" title="Import refusé, rien n’a été modifié :">{preview.errors.map((e) => <span key={e} style={{ display: 'block' }}>{e}</span>)}</Notice>}
        {preview?.ok && (
          <div className="stack tight" style={{ marginTop: 8 }}>
            <ul className="bullets small">{preview.orgs.map((o) => <li key={o.id}>{o.name} — {o.counts.project} projet(s), {o.counts.quest} quête(s){o.conflict ? ' — existe déjà' : ''}</li>)}</ul>
            <Select label="Mode" value={mode} onChange={(e) => setMode(e.target.value as 'merge')} options={[{ value: 'merge', label: 'Fusionner (les organisations en conflit sont remplacées)' }, { value: 'replace', label: 'Remplacer tout l’espace' }]} />
            <div className="row"><Button onClick={() => setPreview(null)}>Annuler</Button><Button variant="primary" onClick={() => { replaceState(applyBackup(s, preview.state!, mode, preview.orgs.filter((o) => o.conflict).map((o) => o.id))); setPreview(null); }}>Appliquer l’import</Button></div>
          </div>
        )}
      </Panel>
      <Panel title="Réinitialiser" tone="danger">
        <p className="small">Supprime toutes les données de démonstration de ce navigateur (organisations, brouillons, préférences). Exportez d’abord une sauvegarde si nécessaire.</p>
        <div className="row"><Button icon="download" onClick={exportBackup}>Exporter avant de réinitialiser</Button><Button variant="danger" icon="trash" onClick={() => setConfirmReset(true)}>Réinitialiser la démonstration</Button></div>
        <ConfirmDialog open={confirmReset} title="Réinitialiser toutes les données de démonstration ?" danger confirmLabel="Réinitialiser" message={<p>Cette action est limitée aux données de cette démonstration et ne peut pas être annulée, sauf en réimportant une sauvegarde.</p>} onClose={() => setConfirmReset(false)} onConfirm={() => { clearWorkspace(); replaceState(emptyState()); setConfirmReset(false); navigate('/entree'); }} />
      </Panel>
    </div>
  );
}

function DemoControls() {
  const s = useAppState();
  const humans = [...new Set(list(s, 'member', s.session.orgId).map((m) => m.userId))];
  const experts = list(s, 'expert', s.session.orgId);
  const exceptions = list(s, 'exception', s.session.orgId).filter((e) => effectiveExceptionStatus(s, e) === 'approved');
  const shares = list(s, 'share', s.session.orgId).filter((x) => shareStatus(s, x) === 'active');
  const [days, setDays] = useState(4);
  return (
    <div className="stack">
      <Notice tone="ai" title="Paramètres de démonstration.">Ces commandes servent à rejouer les situations du scénario. Elles sont séparées des actions métier et tracées comme « démo » dans les Chroniques.</Notice>
      <div className="grid-2">
        <Panel title="Changer d’acteur">
          <p className="small muted">Pour démontrer auteur, approbateur distinct, lecteur, auditeur et agent IA.</p>
          <ul className="plain stack tight">
            {humans.map((h) => <li key={h} className="row between"><Person id={h} showRole /><CmdButton def={cmd.setActor} payload={{ actor: { type: 'human', userId: h } }} size="small" success={`Vous agissez comme ${s.users[h]?.name}`} showReason={false}>{s.session.actor.type === 'human' && s.session.actor.userId === h ? 'Acteur courant' : 'Agir comme'}</CmdButton></li>)}
          </ul>
          <Select label="Ou agir comme un agent IA" value={s.session.actor.type === 'agent' ? s.session.actor.expertId : ''} placeholder="Choisir un agent…" onChange={(e) => e.target.value && dispatch(cmd.setActor, { actor: { type: 'agent', expertId: e.target.value } }, { success: 'Vous agissez comme un agent IA' })} options={experts.map((e) => ({ value: e.id, label: `${e.name} (agent IA)` }))} />
        </Panel>
        <Panel title="Injecter un échec">
          <p className="small">Prochaine exécution : {s.demo.nextFailure === 'tool-error' ? <Badge tone="danger">erreur d’outil</Badge> : s.demo.nextFailure === 'inconclusive' ? <Badge tone="warning">non concluant</Badge> : <Badge tone="success">normale</Badge>}</p>
          <div className="row">
            <CmdButton def={cmd.demoInjectFailure} payload={{ kind: 'tool-error' }} size="small" success="La prochaine exécution échouera techniquement">Erreur d’outil</CmdButton>
            <CmdButton def={cmd.demoInjectFailure} payload={{ kind: 'inconclusive' }} size="small" success="Le prochain contrôle sera non concluant">Résultat non concluant</CmdButton>
            <CmdButton def={cmd.demoInjectFailure} payload={{ kind: null }} size="small" success="Injection retirée">Retirer</CmdButton>
          </div>
          <p className="tiny muted">La prochaine connexion d’intégration échoue aussi lorsqu’une erreur d’outil est injectée.</p>
        </Panel>
        <Panel title="Simuler le passage du temps et les expirations">
          <p className="small">Horloge de démonstration : {fmtDate(nowOf(s), true)}{s.demo.timeOffsetMs ? ` (+${Math.round(s.demo.timeOffsetMs / 86_400_000)} j)` : ''}</p>
          <div className="row"><TextField label="Avancer de (jours)" type="number" min={1} value={days} onChange={(e) => setDays(Number(e.target.value))} /><CmdButton def={cmd.demoAdvanceTime} payload={{ days }} size="small" icon="clock" success={`Horloge avancée de ${days} jour(s)`}>Avancer l’horloge</CmdButton></div>
          <h3 style={{ marginTop: 8 }}>Faire expirer maintenant</h3>
          <ul className="plain stack tight">
            {exceptions.map((e) => <li key={e.id} className="row between small"><span>Exception {s.db.rule[e.ruleId]?.code} — {s.db.project[e.projectId]?.name}</span><CmdButton def={cmd.demoExpire} payload={{ kind: 'exception', id: e.id }} size="small" success="Exception expirée (simulation)">Expirer</CmdButton></li>)}
            {shares.map((x) => <li key={x.id} className="row between small"><span>Partage — {s.db.deliverable[x.deliverableId]?.title}</span><CmdButton def={cmd.demoExpire} payload={{ kind: 'share', id: x.id }} size="small" success="Partage expiré (simulation)">Expirer</CmdButton></li>)}
            {!exceptions.length && !shares.length && <li className="small muted">Rien à faire expirer.</li>}
          </ul>
        </Panel>
        <Panel title="Charger un scénario">
          <p className="small muted">Recharger « Atelier Nova » remet ce scénario dans son état initial (les autres organisations sont conservées).</p>
          <div className="row">
            <Button icon="replace" onClick={() => { dispatch(cmd.loadDemo, { reload: true }, { success: 'Scénario Atelier Nova rechargé' }); navigate('/royaume'); }}>Recharger Atelier Nova</Button>
            <Button icon="plus" onClick={() => navigate('/entree')}>Créer une organisation vierge</Button>
          </div>
        </Panel>
      </div>
    </div>
  );
}
