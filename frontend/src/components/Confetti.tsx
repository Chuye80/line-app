import { useEffect, useRef } from "react";

const PARTICLE_COUNT = 140;
const DURATION_MS = 4200;
const COLOURS = ["#22c55e", "#0ea5e9", "#f59e0b", "#ef4444", "#a855f7", "#ffffff"];

type Particle = {
  x: number;
  y: number;
  vx: number;
  vy: number;
  size: number;
  spin: number;
  angle: number;
  colour: string;
};

/**
 * A short burst of confetti over the completion screen.
 *
 * Drawn on a canvas rather than as animated elements so that a hundred-odd
 * pieces cost one paint instead of a hundred layout passes, and it sits behind
 * a pointer-events-none layer so it never gets in the way of the buttons
 * underneath. It runs once, for a few seconds, and then removes itself.
 *
 * Anybody who has asked their system for reduced motion gets no animation.
 */
export function Confetti() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;

    if (!canvas) {
      return;
    }

    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      return;
    }

    const context = canvas.getContext("2d");

    if (!context) {
      return;
    }

    const ratio = window.devicePixelRatio || 1;

    const resize = () => {
      canvas.width = canvas.clientWidth * ratio;
      canvas.height = canvas.clientHeight * ratio;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
    };

    resize();
    window.addEventListener("resize", resize);

    const width = () => canvas.clientWidth;
    const height = () => canvas.clientHeight;

    const particles: Particle[] = Array.from(
      { length: PARTICLE_COUNT },
      () => ({
        x: Math.random() * width(),
        y: -20 - Math.random() * height() * 0.6,
        vx: (Math.random() - 0.5) * 60,
        vy: 90 + Math.random() * 150,
        size: 6 + Math.random() * 7,
        spin: (Math.random() - 0.5) * 8,
        angle: Math.random() * Math.PI,
        colour: COLOURS[Math.floor(Math.random() * COLOURS.length)],
      })
    );

    const started = performance.now();
    let previous = started;
    let frame = 0;

    const draw = (timestamp: number) => {
      const elapsed = timestamp - started;
      const step = Math.min((timestamp - previous) / 1000, 0.05);
      previous = timestamp;

      context.clearRect(0, 0, width(), height());

      // Fade the whole burst out over its final second instead of stopping
      // dead, which reads as celebratory rather than as a glitch.
      context.globalAlpha = Math.max(
        0,
        Math.min(1, (DURATION_MS - elapsed) / 1000)
      );

      particles.forEach((particle) => {
        particle.x += particle.vx * step;
        particle.y += particle.vy * step;
        particle.angle += particle.spin * step;

        context.save();
        context.translate(particle.x, particle.y);
        context.rotate(particle.angle);
        context.fillStyle = particle.colour;
        context.fillRect(
          -particle.size / 2,
          -particle.size / 4,
          particle.size,
          particle.size / 2
        );
        context.restore();
      });

      if (elapsed < DURATION_MS) {
        frame = window.requestAnimationFrame(draw);
      } else {
        context.clearRect(0, 0, width(), height());
      }
    };

    frame = window.requestAnimationFrame(draw);

    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return <canvas className="confetti" ref={canvasRef} aria-hidden="true" />;
}
