/** Documentation: export completed tasks as Documentalist pages, keep the register of shares, read decision records. */
import { useCallback, useState } from 'react';
import { Badge, Button, Checkbox, Notice, Panel, Tabs, TextField } from '@/shared/ui/core';
import { Dialog } from '@/shared/ui/overlay';
import { Markdown } from '@/shared/ui/markdown';
import { listFiles, readText } from '../api';
import { useShares, useTasks } from '../data';
import { useAction, useCliResult, useQuery } from '../query';
import { SHARE, fmtDay, fmtWhen, isDone, shareState } from '../labels';
import { ActionForm, ExternalLink, ListEditor, Pre, Q, TableBox, useRemembered } from '../parts';

export function Docs({ tab = 'export' }: { tab?: string }) {
  const shares = useShares();
  const expired = (shares.data ?? []).filter((s) => shareState(s.state) === 'expired').length;
  return (
    <div className="page-grid">
      <Tabs label="Documentation" value={tab} onChange={(t) => { window.location.hash = `#/documentation/${t}`; }} tabs={[
        { id: 'export', label: 'Export Documentalist', icon: 'scroll' },
        { id: 'partages', label: 'Partages', icon: 'link', count: expired || undefined },
        { id: 'decisions', label: 'Relevés de décision', icon: 'lock' },
      ]} />
      {tab === 'partages' ? <Shares /> : tab === 'decisions' ? <Decisions /> : <Export />}
    </div>
  );
}

function Export() {
  const tasks = useTasks();
  const [picked, setPicked] = useState<string[]>([]);
  const [version, setVersion] = useState('');
  const [output, setOutput] = useState('docs-site');
  const [sections, setSections] = useState(['reference', 'learn', 'blog']);
  const [openapi, setOpenapi] = useState('');
  const [preview, setPreview] = useState<string | null>(null);
  const { act, busy } = useAction();
  const done = (tasks.data ?? []).filter((t) => isDone(t.status));
  const pages = useQuery<{ section: string; files: string[] }[]>(`docs-pages:${output}`, useCallback(async () => {
    return Promise.all(['reference', 'learn', 'blog'].map(async (section) => {
      try { return { section, files: (await listFiles(`${output}/${section}`)).filter((e) => e.kind === 'file').map((e) => e.name) }; } catch { return { section, files: [] }; }
    }));
  }, [output]));
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  return (
    <div className="page-grid">
      <Panel title="Exporter les quêtes terminées">
        <p className="small muted">Seules les quêtes terminées, avec ou sans réserves, s’exportent : leurs résultats sont enregistrés, et la page dit ce qui a été vérifié, ce qui ne s’appliquait pas et ce qui est resté ouvert. Les pages portent le brief, le comportement, les critères atteints, la livraison et la version, jamais les avis des cerveaux ni les preuves internes. Relisez-les avant de les committer, surtout les brouillons Learn.</p>
        {done.length === 0 ? <Notice tone="warn">Aucune quête terminée pour l’instant.</Notice> : <fieldset className="choices"><legend>Quêtes à documenter</legend>{done.map((t) => <Checkbox key={t.id} label={<><span className="mono">{t.id}</span> {t.brief}</>} checked={picked.includes(t.id)} onChange={() => setPicked((p) => toggle(p, t.id))} />)}</fieldset>}
        <div className="grid-2">
          <TextField label="Version du projet" value={version} onChange={(e) => setVersion(e.target.value)} placeholder="1.4.0" />
          <TextField label="Dossier de sortie" value={output} onChange={(e) => setOutput(e.target.value)} hint="Relatif au projet. L’export refuse un dossier qu’il n’a pas créé." />
        </div>
        <fieldset className="choices"><legend>Sections</legend><div className="choice-row">{[['reference', 'Reference'], ['learn', 'Learn'], ['blog', 'Blog']].map(([id, label]) => <Checkbox key={id} label={label} checked={sections.includes(id)} onChange={() => setSections((s) => toggle(s, id))} />)}</div></fieldset>
        <TextField label="Fichier OpenAPI à joindre (facultatif)" value={openapi} onChange={(e) => setOpenapi(e.target.value)} placeholder="openapi.yaml" />
        <Button variant="primary" busy={busy !== null} disabled={!picked.length || !version.trim() || !sections.length} onClick={() => void act(['docs', 'export', '--tasks', picked.join(','), '--output', output, '--version', version.trim(), '--sections', sections.join(','), ...(openapi ? ['--openapi', openapi] : [])], { success: 'Pages écrites' })}>Écrire les pages</Button>
      </Panel>
      <Panel title={`Pages dans ${output}/`}>
        <Q q={pages}>{(list) => list.every((s) => !s.files.length) ? <p className="muted">Pas encore de pages.</p> : <div className="grid-3">{list.map((s) => <div key={s.section}><h3 className="h-card">{s.section}</h3><ul className="plain">{s.files.map((f) => <li key={f}><button className="linklike" onClick={() => setPreview(`${output}/${s.section}/${f}`)}>{f}</button></li>)}</ul></div>)}</div>}</Q>
        <p className="tiny muted">Dans Documentalist : Outils → Intégrations → Importer depuis GitHub, avec les dossiers <code>{output}/reference</code>, <code>{output}/learn</code> et <code>{output}/blog</code>. Réexporter réécrit les mêmes fichiers.</p>
      </Panel>
      <FileDialog path={preview} onClose={() => setPreview(null)} />
    </div>
  );
}

function FileDialog({ path, onClose }: { path: string | null; onClose: () => void }) {
  const text = useQuery<string>(path ? `file:${path}` : null, useCallback(() => readText(path!), [path]));
  return <Dialog open={!!path} onClose={onClose} wide title={path ?? ''} footer={<Button onClick={onClose}>Fermer</Button>}>
    <Q q={text}>{(t) => path?.endsWith('.json') ? <Pre text={t} /> : <div className="scroll-box" tabIndex={0}><Markdown text={t.replace(/^---[\s\S]*?---\n/, '')} /></div>}</Q>
  </Dialog>;
}

function Shares() {
  const shares = useShares();
  const check = useCliResult(['docs', 'share', 'check']);
  const [by, setBy] = useRemembered('decider');
  const [recipients, setRecipients] = useState<string[]>([]);
  const { act, busy } = useAction();
  return (
    <div className="page-grid">
      <Notice tone="info">Documentalist contrôle l’accès (portail public, code partagé ou adresses invitées). OpenGuildKit tient le registre de ce qui a été partagé, avec qui et jusqu’à quand, pour qu’un accès expiré ne reste pas ouvert. Le registre est local (<code>.openguildkit/shares/</code>, ignoré par Git) car il contient des adresses.</Notice>
      {check.data && check.data.code !== 0 && <Notice tone="danger" title="Partages expirés à retirer :"><Pre text={check.data.stdout || check.data.stderr} /></Notice>}
      <Q q={shares}>{(list) => <Panel title={`Registre (${list.length})`}>
        {list.some((s) => !s.revoked_at) && <TextField label="Personne qui enregistre un retrait" hint={by.trim() ? undefined : 'Indique ton nom pour enregistrer qu’un accès a été retiré : le registre note qui l’a fait.'} value={by} onChange={(e) => setBy(e.target.value)} />}
        {list.length === 0 ? <p className="muted">Aucun partage.</p> : <TableBox label="Registre des partages"><table className="data compact"><thead><tr><th>Livrable</th><th>Destinataires</th><th>Jusqu’au</th><th>État</th><th><span className="sr-only">Retrait</span></th></tr></thead><tbody>
          {list.map((s) => { const l = SHARE[shareState(s.state)]; return <tr key={s.id}><td><span className="mono small">{s.deliverable}</span><span className="tiny block"><ExternalLink href={s.portal}>portail</ExternalLink> · {s.by}, {fmtWhen(s.created_at)}</span></td><td className="small">{s.recipients.join(', ')}</td><td>{fmtDay(s.until)}</td><td><Badge tone={l.tone} icon={l.icon}>{l.label}</Badge></td>
            <td>{!s.revoked_at && <Button size="small" variant="danger" busy={busy !== null} disabled={!by.trim()} onClick={() => void act(['docs', 'share', 'revoke', '--id', s.id, '--by', by.trim()], { success: 'Retrait enregistré' })}>Accès retiré</Button>}</td></tr>; })}
        </tbody></table></TableBox>}
        <p className="tiny muted">Retirez d’abord l’accès dans Documentalist (« Retirer l’accès »), puis enregistrez-le ici.</p>
      </Panel>}</Q>
      <Panel title="Enregistrer un partage">
        <ListEditor label="Destinataires (adresses)" items={recipients} onChange={setRecipients} placeholder="client@example.org" />
        <ActionForm busy={busy !== null} submit="Enregistrer le partage" initial={{ by }} problem={recipients.length ? null : 'Il manque un destinataire : ajoute au moins une adresse avec « Ajouter », le registre dit avec qui la page est partagée.'} fields={[
          { name: 'deliverable', label: 'Page ou dossier partagé', required: true, placeholder: 'docs-site/reference/request-status.md', hint: 'Un fichier existant du projet, ou le dossier écrit par l’export, jamais sous .openguildkit/.' },
          { name: 'until', label: 'Dernier jour d’accès', type: 'date', required: true },
          { name: 'portal', label: 'Adresse du portail Documentalist (https)', type: 'url', required: true },
          { name: 'by', label: 'Responsable du partage', required: true },
        ]} onSubmit={async (v) => { setBy(v.by); if (await act(['docs', 'share', 'add', '--deliverable', v.deliverable, ...recipients.flatMap((r) => ['--recipient', r]), '--until', v.until, '--portal', v.portal, '--by', v.by], { success: 'Partage enregistré' })) setRecipients([]); }} />
      </Panel>
    </div>
  );
}

function Decisions() {
  const files = useQuery<string[]>('decision-files', useCallback(async () => (await listFiles('.openguildkit/decisions')).filter((e) => e.kind === 'file').map((e) => e.name), []));
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Panel title="Relevés de décision exportés">
      <p className="small muted"><code>task export</code> écrit un relevé partageable dans <code>.openguildkit/decisions/</code>, à joindre à la pull request : le brief, le verdict de chaque cerveau et l’approbation scellée, sans preuves ni notes internes. La CI peut vérifier ces relevés avec <code>guard --ci</code>.</p>
      <Q q={files}>{(list) => list.length === 0 ? <p className="muted">Aucun relevé. Exportez-en un depuis la fiche d’une quête validée.</p> : <ul>{list.map((f) => <li key={f}><button className="linklike" onClick={() => setOpen(`.openguildkit/decisions/${f}`)}>{f}</button></li>)}</ul>}</Q>
      <FileDialog path={open} onClose={() => setOpen(null)} />
    </Panel>
  );
}
