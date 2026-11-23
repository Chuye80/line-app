import { useEffect, useRef, useState } from "react";
import type { JSX } from "react";
import { animate, motion, useReducedMotion } from "motion/react";

/* ---------------------------------------------------------------------------
   Small presentational pieces shared by the screens: icons, bottom nav,
   count-up numbers, confetti and the medal ladder.
   Motion rules (Emil Kowalski): strong ease-out, under ~300ms for UI,
   springs only for things that arrive (avatars, pill), nothing on keyboard
   actions, and everything respects prefers-reduced-motion.
   ------------------------------------------------------------------------- */

const EASE_OUT = [0.23, 1, 0.32, 1] as const;

/* ---------- Icons ---------- */

function HomeIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3.5 11.2 12 4l8.5 7.2" />
      <path d="M5.5 10v9.5h13V10" />
      <path d="M10 19.5v-5h4v5" />
    </svg>
  );
}

function BallIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="8.5" />
      <path d="m12 8 3.4 2.5-1.3 4h-4.2l-1.3-4Z" />
      <path d="M12 8V3.6M15.4 10.5l4-1.2M14.1 14.5l2.4 3.4M9.9 14.5l-2.4 3.4M8.6 10.5l-4-1.2" />
    </svg>
  );
}

function GroupIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="9" cy="8.5" r="3.2" />
      <path d="M3.5 19c.4-3 2.6-4.6 5.5-4.6s5.1 1.6 5.5 4.6" />
      <circle cx="17" cy="9.5" r="2.5" />
      <path d="M16.5 14.6c2.4.1 3.8 1.5 4.2 4" />
    </svg>
  );
}

function StatsIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 20v-7M12 20V5M19 20v-10" />
    </svg>
  );
}

const NAV_ICONS: Record<string, () => JSX.Element> = {
  home: HomeIcon,
  game: BallIcon,
  group: GroupIcon,
  stats: StatsIcon,
};

/* ---------- Bottom navigation ---------- */

export function BottomNav({
  items,
  active,
  onSelect,
  ariaLabel,
}: {
  items: readonly (readonly [string, string])[];
  active: string;
  onSelect: (key: string) => void;
  ariaLabel: string;
}) {
  return (
    <nav className="bottom-nav" aria-label={ariaLabel}>
      <div className="bottom-nav-inner">
        {items.map(([key, label]) => {
          const Icon = NAV_ICONS[key] ?? HomeIcon;
          const isActive = active === key;
          return (
            <button
              key={key}
              type="button"
              className={
                isActive ? "bottom-nav-button active" : "bottom-nav-button"
              }
              aria-current={isActive ? "page" : undefined}
              onClick={() => onSelect(key)}
            >
              {isActive && (
                <motion.span
                  layoutId="bottom-nav-pill"
                  className="bottom-nav-pill"
                  transition={{ type: "spring", stiffness: 520, damping: 40 }}
                />
              )}
              <Icon />
              <span className="nav-label">{label}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}

/* ---------- Count-up number ---------- */

export function AnimatedNumber({ value }: { value: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const previous = useRef(value);
  const reduce = useReducedMotion();

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (reduce || previous.current === value) {
      node.textContent = String(value);
      previous.current = value;
      return;
    }
    const controls = animate(previous.current, value, {
      duration: 0.55,
      ease: EASE_OUT,
      onUpdate: (latest) => {
        node.textContent = String(Math.round(latest));
      },
    });
    previous.current = value;
    return () => controls.stop();
  }, [value, reduce]);

  return <span ref={ref}>{value}</span>;
}

/* ---------- Confetti ---------- */

const CONFETTI_COLORS = ["#c6f53f", "#0f6a42", "#f2a31b", "#2f6bf0", "#e5484d", "#ffffff"];

type Piece = {
  id: number;
  x: number;
  y: number;
  rotate: number;
  size: number;
  color: string;
  delay: number;
};

function makePieces(count: number): Piece[] {
  return Array.from({ length: count }, (_, id) => ({
    id,
    x: (Math.random() - 0.5) * 360,
    y: -(120 + Math.random() * 220),
    rotate: (Math.random() - 0.5) * 720,
    size: 6 + Math.random() * 7,
    color: CONFETTI_COLORS[id % CONFETTI_COLORS.length]!,
    delay: Math.random() * 0.08,
  }));
}

/** One-shot burst. Remount it with a new `key` to fire again. */
export function Confetti({
  scope = "screen",
  count = 34,
}: {
  scope?: "screen" | "card";
  count?: number;
}) {
  const reduce = useReducedMotion();
  const [pieces] = useState(() => makePieces(count));
  if (reduce) return null;
  return (
    <div
      className={scope === "screen" ? "confetti confetti-screen" : "confetti"}
      aria-hidden="true"
    >
      {pieces.map((piece) => (
        <motion.span
          key={piece.id}
          className="confetti-piece"
          style={{
            width: piece.size,
            height: piece.size * 1.5,
            background: piece.color,
          }}
          initial={{ x: 0, y: 0, opacity: 1, rotate: 0, scale: 1 }}
          animate={{
            x: piece.x,
            y: [0, piece.y, piece.y + 340],
            opacity: [1, 1, 0],
            rotate: piece.rotate,
          }}
          transition={{
            duration: 1.5,
            delay: piece.delay,
            ease: EASE_OUT,
            times: [0, 0.4, 1],
          }}
        />
      ))}
    </div>
  );
}

/* ---------- Medal ladder ---------- */

const MEDAL_TIERS = [
  { key: "stone", label: "medalStone", from: "#aab0b5", to: "#6d7479" },
  { key: "bronze", label: "medalBronze", from: "#e0a066", to: "#a8642b" },
  { key: "silver", label: "medalSilver", from: "#eef2f6", to: "#aab4bf" },
  { key: "gold", label: "medalGold", from: "#ffe27a", to: "#e2a208" },
  { key: "platinum", label: "medalPlatinum", from: "#d6f6f4", to: "#7fc9c6" },
  { key: "diamond", label: "medalDiamond", from: "#b8f0ff", to: "#3aa6ff" },
] as const;

export type MedalTier = (typeof MEDAL_TIERS)[number]["key"];

export function Medal({
  tier,
  label,
  locked = false,
  shine = false,
}: {
  tier: MedalTier;
  label: string;
  locked?: boolean;
  shine?: boolean;
}) {
  const spec = MEDAL_TIERS.find((item) => item.key === tier) ?? MEDAL_TIERS[0];
  const gradientId = `medal-${tier}`;
  return (
    <span
      className={["medal", locked ? "locked" : "", shine ? "shine" : ""]
        .filter(Boolean)
        .join(" ")}
    >
      <svg viewBox="0 0 48 56" aria-hidden="true">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor={spec.from} />
            <stop offset="1" stopColor={spec.to} />
          </linearGradient>
        </defs>
        <path d="M14 2h8l4 14h-8Z" fill="#2f6bf0" />
        <path d="M34 2h-8l-4 14h8Z" fill="#e5484d" />
        <circle cx="24" cy="34" r="18" fill={`url(#${gradientId})`} />
        <circle
          cx="24"
          cy="34"
          r="13.5"
          fill="none"
          stroke="rgba(255,255,255,0.55)"
          strokeWidth="2"
        />
        {tier === "diamond" ? (
          <path d="m24 25 7 6-7 12-7-12Z" fill="rgba(255,255,255,0.8)" />
        ) : (
          <path
            d="m24 26 2.6 5.4 5.9.8-4.3 4.1 1 5.8-5.2-2.8-5.2 2.8 1-5.8-4.3-4.1 5.9-.8Z"
            fill="rgba(255,255,255,0.8)"
          />
        )}
      </svg>
      <span>{label}</span>
    </span>
  );
}

export function MedalLadder({ t }: { t: (key: string) => string }) {
  return (
    <div className="medal-ladder">
      {MEDAL_TIERS.map((tier, index) => (
        <Medal
          key={tier.key}
          tier={tier.key}
          label={t(tier.label)}
          locked={index > 0}
          shine={index === 0}
        />
      ))}
    </div>
  );
}
