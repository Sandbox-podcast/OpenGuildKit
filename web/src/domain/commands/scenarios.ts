/** Demo scenario loading, kept apart from business commands (brief §5.12). */
import { buildNova, NOVA } from '@/fixtures/nova';
import { command, emit } from '../engine';

export const loadDemo = command<{ reload?: boolean }, string>({
  name: 'loadDemo',
  global: true,
  run: (d, ctx, p) => {
    if (d.orgs[NOVA] && !p.reload) {
      d.session = { orgId: NOVA, actor: { type: 'human', userId: 'u-yanis' }, projectId: 'prj-export' };
      return NOVA;
    }
    buildNova(d, ctx.now);
    emit(d, { ...ctx, orgId: NOVA, actor: { type: 'system' } }, { action: 'demo.loaded', summary: p.reload ? 'Scénario « Atelier Nova » rechargé (données de démonstration remises à zéro)' : 'Scénario de démonstration « Atelier Nova » chargé', object: { kind: 'org', id: NOVA }, provenance: 'démo' });
    return NOVA;
  },
});
