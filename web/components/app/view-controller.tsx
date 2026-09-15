'use client';

import { useEffect, useState } from 'react';
import { useTheme } from 'next-themes';
import { AnimatePresence, motion } from 'motion/react';
import { useSessionContext } from '@livekit/components-react';
import { AgentSessionView_01 } from '@/components/agents-ui/blocks/agent-session-view-01';
import { StageIndicator } from '@/components/app/stage-indicator';
import { ThankYouView } from '@/components/app/thank-you-view';
import { WelcomeView } from '@/components/app/welcome-view';

const MotionWelcomeView = motion.create(WelcomeView);
const MotionThankYouView = motion.create(ThankYouView);
const MotionSessionView = motion.create(AgentSessionView_01);

const VIEW_MOTION_PROPS = {
  variants: {
    visible: {
      opacity: 1,
    },
    hidden: {
      opacity: 0,
    },
  },
  initial: 'hidden',
  animate: 'visible',
  exit: 'hidden',
  transition: {
    duration: 0.5,
    ease: 'linear',
  },
};

export function ViewController() {
  const { isConnected, start } = useSessionContext();
  const { resolvedTheme } = useTheme();

  // Track whether an interview has already run, so ending the call shows a proper
  // "thank you" screen instead of silently returning to the welcome view.
  const [ended, setEnded] = useState(false);
  const [wasConnected, setWasConnected] = useState(false);

  useEffect(() => {
    if (isConnected) {
      setWasConnected(true);
      setEnded(false);
    } else if (wasConnected) {
      setEnded(true);
    }
  }, [isConnected, wasConnected]);

  const handleStart = () => {
    setEnded(false);
    start();
  };

  return (
    <>
      {/* Big, obvious stage indicator (self-hides until the agent publishes a stage) */}
      <StageIndicator />

      <AnimatePresence mode="wait">
        {/* Welcome view (first load) */}
        {!isConnected && !ended && (
          <MotionWelcomeView
            key="welcome"
            {...VIEW_MOTION_PROPS}
            startButtonText="Start interview"
            onStartCall={handleStart}
          />
        )}
        {/* Thank-you view (after the call ends) */}
        {!isConnected && ended && (
          <MotionThankYouView key="thankyou" {...VIEW_MOTION_PROPS} onRestart={handleStart} />
        )}
        {/* Session view */}
        {isConnected && (
          <MotionSessionView
            key="session-view"
            {...VIEW_MOTION_PROPS}
            supportsChatInput={true}
            supportsVideoInput={true}
            supportsScreenShare={true}
            isPreConnectBufferEnabled={true}
            themeMode={resolvedTheme === 'dark' ? 'dark' : 'light'}
            className="fixed inset-0"
          />
        )}
      </AnimatePresence>
    </>
  );
}
