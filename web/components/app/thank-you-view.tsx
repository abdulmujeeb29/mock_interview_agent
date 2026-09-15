import { motion } from 'motion/react';
import { Button } from '@/components/ui/button';

const rise = {
  initial: { opacity: 0, y: 14 },
  animate: { opacity: 1, y: 0 },
};

interface ThankYouViewProps {
  onRestart: () => void;
}

export const ThankYouView = ({
  onRestart,
  ref,
}: React.ComponentProps<'div'> & ThankYouViewProps) => {
  return (
    <div ref={ref}>
      <section className="flex flex-col items-center justify-center px-6 text-center">
        <motion.div
          initial={{ opacity: 0, scale: 0.6 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.45, ease: 'easeOut' }}
          className="bg-primary/10 text-primary mb-5 flex size-16 items-center justify-center rounded-full text-3xl"
        >
          ✓
        </motion.div>

        <motion.h1
          {...rise}
          transition={{ duration: 0.4, delay: 0.08, ease: 'easeOut' }}
          className="text-foreground text-2xl font-semibold tracking-tight"
        >
          Interview complete
        </motion.h1>

        <motion.p
          {...rise}
          transition={{ duration: 0.4, delay: 0.15, ease: 'easeOut' }}
          className="text-muted-foreground max-w-prose pt-2 leading-6"
        >
          Thanks for your time — that wraps up the mock interview. You covered the introduction and
          a past project. Feel free to run it again to practice more.
        </motion.p>

        <motion.div {...rise} transition={{ duration: 0.4, delay: 0.22, ease: 'easeOut' }}>
          <Button
            size="lg"
            onClick={onRestart}
            className="mt-6 w-64 rounded-full font-mono text-xs font-bold tracking-wider uppercase transition-transform hover:scale-[1.03]"
          >
            Start a new interview
          </Button>
        </motion.div>
      </section>
    </div>
  );
};
