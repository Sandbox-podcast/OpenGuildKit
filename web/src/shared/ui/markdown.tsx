/** Markdown parsed into React elements, never injected as HTML. Links are limited to http(s). */
import { useMemo, type ReactNode } from 'react';
import { isSafeUrl } from '@/shared/text';

function inline(text: string, key = 0): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|\*[^*]+\*|_[^_]+_)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    const k = `${key}-${i++}`;
    if (t.startsWith('**')) out.push(<strong key={k}>{t.slice(2, -2)}</strong>);
    else if (t.startsWith('`')) out.push(<code key={k}>{t.slice(1, -1)}</code>);
    else if (t.startsWith('[')) {
      const lm = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(t)!;
      out.push(isSafeUrl(lm[2]!) ? <a key={k} href={lm[2]} target="_blank" rel="noopener noreferrer">{lm[1]}</a> : <span key={k}>{lm[1]}</span>);
    } else out.push(<em key={k}>{t.slice(1, -1)}</em>);
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ text }: { text: string }) {
  const blocks = useMemo(() => {
    const lines = text.replace(/\r\n/g, '\n').split('\n');
    const out: ReactNode[] = [];
    let i = 0;
    while (i < lines.length) {
      const l = lines[i]!;
      if (l.startsWith('<!--')) { i++; continue; }
      if (l.startsWith('```')) {
        const buf: string[] = [];
        i++;
        while (i < lines.length && !lines[i]!.startsWith('```')) buf.push(lines[i++]!);
        out.push(<pre key={i}><code>{buf.join('\n')}</code></pre>);
        i++;
        continue;
      }
      const h = /^(#{1,4})\s+(.*)$/.exec(l);
      if (h) { const Tag = `h${Math.min(h[1]!.length + 1, 4)}` as 'h2'; out.push(<Tag key={i}>{inline(h[2]!, i)}</Tag>); i++; continue; }
      if (/^\s*([-*]|\d+\.)\s/.test(l)) {
        const ordered = /^\s*\d+\./.test(l);
        const items: ReactNode[] = [];
        while (i < lines.length && /^\s*([-*]|\d+\.)\s/.test(lines[i]!)) { items.push(<li key={i}>{inline(lines[i]!.replace(/^\s*([-*]|\d+\.)\s/, ''), i)}</li>); i++; }
        out.push(ordered ? <ol key={`l${i}`}>{items}</ol> : <ul key={`l${i}`}>{items}</ul>);
        continue;
      }
      if (l.startsWith('|')) {
        const rows: string[][] = [];
        while (i < lines.length && lines[i]!.startsWith('|')) { if (!/^\|\s*-/.test(lines[i]!)) rows.push(lines[i]!.split('|').slice(1, -1).map((c) => c.trim())); i++; }
        out.push(<div className="table-wrap" key={`t${i}`}><table><thead><tr>{rows[0]?.map((c, j) => <th key={j}>{inline(c)}</th>)}</tr></thead><tbody>{rows.slice(1).map((r, j) => <tr key={j}>{r.map((c, k) => <td key={k}>{inline(c)}</td>)}</tr>)}</tbody></table></div>);
        continue;
      }
      if (l.startsWith('>')) { out.push(<blockquote key={i} className="notice ai" style={{ margin: '8px 0' }}>{inline(l.replace(/^>\s?/, ''), i)}</blockquote>); i++; continue; }
      if (!l.trim()) { i++; continue; }
      const para: string[] = [];
      while (i < lines.length && lines[i]!.trim() && !/^(#|```|\||>|\s*([-*]|\d+\.)\s)/.test(lines[i]!)) para.push(lines[i++]!);
      out.push(<p key={`p${i}`}>{inline(para.join(' '), i)}</p>);
    }
    return out;
  }, [text]);
  return <div className="prose">{blocks}</div>;
}

