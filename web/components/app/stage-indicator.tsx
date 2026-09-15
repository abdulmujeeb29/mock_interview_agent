'use client';

import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { type InterviewStage, useInterviewStage } from '@/hooks/useInterviewStage';
import { cn } from '@/lib/shadcn/utils';

const STEPS: { key: Exclude<InterviewStage, null>; label: string }[] = [
  { key: 'intro', label: 'Introduction' },
  { key: 'past_experience', label: 'Past experience' },
  { key: 'done', label: 'Complete' },
];

const REASON_LABEL: Record<string, string> = {
  coverage: 'covered enough',
  budget: 'enough follow-ups',
  timer: 'time limit reached (fallback)',
  utility: 'ready to move on',
};

function fmt(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/** Live MM:SS timer for the current stage with a bar that fills toward the hard
 * time-limit and turns amber near the TIMER fallback — so the countdown is visible
 * on screen without reading any logs. */
function StageTimer({ limit, startedAt }: { limit: number; startedAt: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, []);

  if (!startedAt || !limit) return null;
  const elapsed = Math.max(0, (now - startedAt) / 1000);
  const remaining = Math.max(0, limit - elapsed);
  const pct = Math.min(100, (elapsed / limit) * 100);
  const near = remaining <= Math.min(15, limit * 0.25); // amber warning zone

  return (
    <div className="bg-background/80 flex w-56 flex-col gap-1.5 rounded-2xl border px-4 py-2 shadow-md backdrop-blur-md">
      <div className="flex items-center justify-between text-xs font-semibold tabular-nums">
        <span className={cn('flex items-center gap-1', near && 'text-amber-600')}>
          <motion.span
            animate={near ? { opacity: [1, 0.4, 1] } : { opacity: 1 }}
            transition={{ duration: 1, repeat: near ? Infinity : 0 }}
          >
            ⏱
          </motion.span>
          {fmt(remaining)} left
        </span>
        <span className="text-muted-foreground/70">{fmt(limit)}</span>
      </div>
      <div className="bg-muted h-1.5 overflow-hidden rounded-full">
        <motion.div
          className={cn('h-full rounded-full', near ? 'bg-amber-500' : 'bg-primary')}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.25, ease: 'linear' }}
        />
      </div>
    </div>
  );
}

export function StageIndicator() {
  const { stage, reason, limit, startedAt } = useInterviewStage();
  const [banner, setBanner] = useState<{ label: string; reason: string; timer: boolean } | null>(
    null
  );
  const prev = useRef<InterviewStage>(null);

  useEffect(() => {
    if (!stage) {
      prev.current = null;
      return;
    }
    if (prev.current && prev.current !== stage) {
      const isTimer = reason === 'timer';
      const step = STEPS.find((s) => s.key === stage);
      setBanner({
        label: step?.label ?? stage,
        reason: REASON_LABEL[reason] ?? reason,
        timer: isTimer,
      });
      // Timer-fallback switches linger longer — they're the "no logs needed" proof.
      const t = setTimeout(() => setBanner(null), isTimer ? 7000 : 5000);
      prev.current = stage;
      return () => clearTimeout(t);
    }
    prev.current = stage;
  }, [stage, reason]);

  if (!stage) return null;
  const activeIdx = STEPS.findIndex((s) => s.key === stage);

  return (
    <div className="pointer-events-none fixed top-16 left-1/2 z-40 flex -translate-x-1/2 flex-col items-center gap-3">
      {/* Stage stepper */}
      <div className="bg-background/80 flex items-center gap-0.5 rounded-full border p-1 shadow-lg backdrop-blur-md">
        {STEPS.map((s, i) => {
          const state = i === activeIdx ? 'active' : i < activeIdx ? 'done' : 'todo';
          return (
            <div key={s.key} className="flex items-center">
              <motion.span
                animate={state === 'active' ? { scale: [1, 1.04, 1] } : { scale: 1 }}
                transition={{ duration: 0.5 }}
                className={cn(
                  'rounded-full px-4 py-1.5 text-sm font-semibold transition-colors',
                  state === 'active' && 'bg-primary text-primary-foreground shadow',
                  state === 'done' && 'text-muted-foreground',
                  state === 'todo' && 'text-muted-foreground/45'
                )}
              >
                {state === 'done' ? '✓ ' : ''}
                {s.label}
              </motion.span>
              {i < STEPS.length - 1 && (
                <span className="text-muted-foreground/40 px-0.5 text-sm">→</span>
              )}
            </div>
          );
        })}
      </div>

      {/* Live countdown for the active stage (hidden once the interview is complete) */}
      {stage !== 'done' && <StageTimer limit={limit} startedAt={startedAt} />}

      {/* Transition banner — appears when the stage changes, says WHY */}
      <AnimatePresence mode="wait">
        {banner && (
          <motion.div
            key={banner.label + banner.reason}
            initial={{ opacity: 0, y: -8, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.35, ease: 'easeOut' }}
            className={cn(
              'shadow-md',
              banner.timer
                ? 'flex items-center gap-3 rounded-2xl bg-amber-500 px-5 py-2.5 text-white ring-4 ring-amber-500/25'
                : 'bg-foreground text-background rounded-full px-5 py-2 text-sm font-semibold'
            )}
          >
            {banner.label === 'Complete' ? (
              '✓ Interview complete'
            ) : banner.timer ? (
              <>
                <motion.span
                  className="text-lg"
                  animate={{ rotate: [0, -12, 12, -8, 0] }}
                  transition={{ duration: 0.6 }}
                >
                  ⏱
                </motion.span>
                <span className="flex flex-col leading-tight">
                  <span className="text-[13px] font-bold">Time&apos;s up — advancing</span>
                  <span className="text-xs font-medium text-white/90">
                    Now: {banner.label} · time-based fallback
                  </span>
                </span>
              </>
            ) : (
              `→ Now: ${banner.label} · ${banner.reason}`
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
