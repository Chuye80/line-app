import { useEffect, useState } from "react";

/**
 * Isolated so that the once-a-second tick redraws the clock instead of the
 * whole page.
 */
export function Countdown({ opensAt }: { opensAt: string }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const remaining = new Date(opensAt).getTime() - now;

  if (remaining <= 0) {
    return <div className="countdown">Registration open to all members</div>;
  }

  const totalSeconds = Math.floor(remaining / 1000);
  const pad = (value: number) => value.toString().padStart(2, "0");

  return (
    <div className="countdown">
      Subscribers only: {pad(Math.floor(totalSeconds / 3600))}:
      {pad(Math.floor((totalSeconds % 3600) / 60))}:{pad(totalSeconds % 60)}
    </div>
  );
}
