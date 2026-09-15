'use client';

import { useEffect, useState } from 'react';
import { type Participant, RoomEvent } from 'livekit-client';
import { useSessionContext } from '@livekit/components-react';

export type InterviewStage = 'intro' | 'past_experience' | 'done' | null;

/**
 * Reads the interview stage the agent publishes as room participant attributes
 * (`iv_stage` / `iv_reason`). Lets the UI show a live, obvious stage indicator so a
 * viewer understands the switching without looking at any terminal logs.
 */
export function useInterviewStage() {
  const session = useSessionContext();
  const room = session?.room;
  const [stage, setStage] = useState<InterviewStage>(null);
  const [reason, setReason] = useState<string>('');
  // `limit` = this stage's hard time-limit (seconds); `startedAt` = wall-clock ms when it
  // began. The indicator uses them to run a live countdown toward the TIMER fallback.
  const [limit, setLimit] = useState<number>(0);
  const [startedAt, setStartedAt] = useState<number>(0);

  useEffect(() => {
    if (!room) return;

    const apply = (attrs?: Record<string, string>) => {
      if (!attrs) return;
      if (attrs.iv_stage) setStage(attrs.iv_stage as InterviewStage);
      if (attrs.iv_reason !== undefined) setReason(attrs.iv_reason);
      if (attrs.iv_limit !== undefined) setLimit(Number(attrs.iv_limit) || 0);
      if (attrs.iv_started !== undefined) setStartedAt(Number(attrs.iv_started) || 0);
    };

    // read whatever is already set
    room.remoteParticipants.forEach((p) => apply(p.attributes));

    const onChanged = (changed: Record<string, string>, _p: Participant) => apply(changed);
    room.on(RoomEvent.ParticipantAttributesChanged, onChanged);
    return () => {
      room.off(RoomEvent.ParticipantAttributesChanged, onChanged);
    };
  }, [room]);

  // reset when the room goes away (call ended)
  useEffect(() => {
    if (!room) {
      setStage(null);
      setReason('');
      setLimit(0);
      setStartedAt(0);
    }
  }, [room]);

  return { stage, reason, limit, startedAt };
}
