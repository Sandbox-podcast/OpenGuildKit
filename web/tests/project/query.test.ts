import { describe, expect, it } from 'vitest';
import { forget, load, peek } from '@/project/query';

describe('cache of the local API', () => {
  /** Issue #467: every key typed in a field left an entry in the cache, which has no eviction. */
  it('drops an entry nobody shows any more', async () => {
    await load('test:typed:a', async () => 'answer');
    expect(peek('test:typed:a')?.data).toBe('answer');
    forget('test:typed:a');
    expect(peek('test:typed:a')).toBeUndefined();
  });

  /** Issue #467: the answer to a question a person had already changed came back into the cache. */
  it('does not bring back an entry that was forgotten while its request was in flight', async () => {
    let finish!: (value: unknown) => void;
    const pending = load('test:typed:b', () => new Promise((resolve) => { finish = resolve; }));
    expect(peek('test:typed:b')?.loading).toBe(true);
    forget('test:typed:b');
    finish('late answer');
    await pending;
    expect(peek('test:typed:b')).toBeUndefined();
  });

  it('does not bring back a forgotten entry whose request failed either', async () => {
    let fail!: (reason: Error) => void;
    const pending = load('test:typed:c', () => new Promise((_, reject) => { fail = reject; }));
    forget('test:typed:c');
    fail(new Error('server stopped'));
    await pending;
    expect(peek('test:typed:c')).toBeUndefined();
  });
});
