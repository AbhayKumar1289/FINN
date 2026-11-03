"use client";

import { useEffect, useState } from "react";

/** Loading that explains itself: what is loading, then (after 6 s) that the free-tier server
 * may be waking up, then (after 20 s) a Retry button. Announced to screen readers. */
export function Loading({ label, heights = [90, 160], onRetry }: {
  label: string;
  heights?: number[];
  onRetry?: () => void;
}) {
  const [stage, setStage] = useState(0);
  useEffect(() => {
    const slow = setTimeout(() => setStage(1), 6_000);
    const stuck = setTimeout(() => setStage(2), 20_000);
    return () => { clearTimeout(slow); clearTimeout(stuck); };
  }, []);
  return (
    <div className="section stack" role="status" aria-live="polite">
      <p className="small muted">
        {label}
        {stage === 1 && " Still working: the server may be waking up (free hosting sleeps when idle; up to a minute)."}
        {stage === 2 && " This is taking much longer than usual."}
      </p>
      {stage === 2 && onRetry && <button className="btn secondary small" onClick={onRetry}>Retry</button>}
      {heights.map((h, i) => <div key={i} className="skeleton" style={{ height: h }} aria-hidden />)}
    </div>
  );
}

/** A failure the user can act on: what went wrong, and Retry when retrying can help. */
export function Failure({ message, onRetry, children }: {
  message: string;
  onRetry?: () => void;
  children?: React.ReactNode;
}) {
  return (
    <div className="section stack" role="alert">
      <div className="error">{message}</div>
      <div className="row">
        {onRetry && <button className="btn secondary small" onClick={onRetry}>Retry</button>}
        {children}
      </div>
    </div>
  );
}
