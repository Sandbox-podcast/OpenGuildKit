/** Optional, sober UI sounds (disabled by default, never automatic). Synthesised, no audio files. */
let ctx: AudioContext | null = null;
const NOTES = { success: [660, 880], error: [330, 220], open: [520] } as const;

export function playSound(kind: keyof typeof NOTES) {
  try {
    ctx ??= new AudioContext();
    NOTES[kind].forEach((freq, i) => {
      const osc = ctx!.createOscillator();
      const gain = ctx!.createGain();
      osc.type = 'square';
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.03, ctx!.currentTime + i * 0.08);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx!.currentTime + i * 0.08 + 0.12);
      osc.connect(gain).connect(ctx!.destination);
      osc.start(ctx!.currentTime + i * 0.08);
      osc.stop(ctx!.currentTime + i * 0.08 + 0.13);
    });
  } catch { /* audio unavailable: silently ignored */ }
}
