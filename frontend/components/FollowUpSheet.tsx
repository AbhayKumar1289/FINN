"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Card } from "@/lib/api";
import { contextFor, suggestFollowUps } from "@/lib/followups";

/** "Keep a question open": pick one of three questions predicted from the event, or write your own. */
export default function FollowUpSheet({ card, onSave, onClose }: {
  card: Card;
  onSave: (note: string) => void;
  onClose: () => void;
}) {
  const suggestions = useMemo(() => suggestFollowUps(card), [card]);
  const [choice, setChoice] = useState<number | "own">(0);
  const [note, setNote] = useState(suggestions[0] ?? "");
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function pick(i: number | "own") {
    setChoice(i);
    setNote(i === "own" ? "" : suggestions[i]);
    if (i === "own") setTimeout(() => box.current?.focus(), 0);
  }

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <section className="sheet" role="dialog" aria-modal="true" aria-labelledby="fu-title">
        <div className="grip" />
        <div className="between">
          <h2 id="fu-title" className="headline">Keep a question open.</h2>
          <button onClick={onClose} aria-label="Close" className="muted" style={{ fontSize: 22, lineHeight: 1 }}>×</button>
        </div>
        <p className="small muted" style={{ marginTop: 4 }}>Linked to {card.company.symbol} · {contextFor(card)}</p>

        <div className="caps" id="fu-suggest" style={{ marginTop: 18 }}>Suggested for this event</div>
        <div className="fu-options" role="radiogroup" aria-labelledby="fu-suggest">
          {suggestions.map((q, i) => (
            <button key={q} role="radio" aria-checked={choice === i} className="fu-option" onClick={() => pick(i)}>
              <span className="fu-radio" aria-hidden />{q}
            </button>
          ))}
          <button role="radio" aria-checked={choice === "own"} className="fu-option own" onClick={() => pick("own")}>
            <span className="fu-radio" aria-hidden />✎ Write my own
          </button>
        </div>

        <label className="caps" htmlFor="fu-note" style={{ display: "block", marginTop: 16 }}>Your note</label>
        <textarea id="fu-note" ref={box} className="input" rows={2} value={note} maxLength={280}
                  placeholder="What do you want to come back to?"
                  onChange={(e) => {
                    setNote(e.target.value);
                    // editing a suggestion makes it your own wording
                    if (choice !== "own" && e.target.value !== suggestions[choice as number]) setChoice("own");
                  }}
                  style={{ height: "auto", padding: "12px 14px", marginTop: 8, resize: "none", fontSize: 16 }} />
        <p className="tiny muted" style={{ marginTop: 6 }}>Saved on this device with the event and its source. Follow-ups are questions, not alerts.</p>
        <button className="btn block" style={{ marginTop: 14 }} disabled={note.trim().length < 3}
                onClick={() => { onSave(note); onClose(); }}>Save follow-up</button>
        <button className="plain-link" style={{ display: "flex", margin: "12px auto 0" }} onClick={onClose}>Cancel</button>
      </section>
    </>
  );
}
