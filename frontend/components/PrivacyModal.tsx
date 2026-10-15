"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ExternalLink, X } from "@/components/icons";
import { PRIVACY_HTML, PRIVACY_UPDATED, PRIVACY_URL } from "@/lib/legal/privacy";

/** The privacy policy in a dialog over the sign-up form. Accept is enabled once
 *  the reader has scrolled to the end, and ticks the sign-up checkbox. */
export default function PrivacyModal({
  open,
  onClose,
  onAccept,
}: {
  open: boolean;
  onClose: () => void;
  onAccept: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const [atEnd, setAtEnd] = useState(false);

  function checkEnd() {
    const el = bodyRef.current;
    if (el && el.scrollTop + el.clientHeight >= el.scrollHeight - 8) setAtEnd(true);
  }

  useEffect(() => {
    if (!open) return;
    setAtEnd(false);
    bodyRef.current?.scrollTo({ top: 0 });
    closeRef.current?.focus();
    // A tall window may show the whole policy without scrolling.
    requestAnimationFrame(checkEnd);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (!open) return null;

  // Rendered on <body>: the page's entrance animation leaves a transform on its
  // wrapper, which would trap a fixed overlay inside the page box.
  return createPortal(
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="modal policy-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="policy-title"
      >
        <div className="tut-head">
          <div>
            <h2 id="policy-title">Privacy Policy</h2>
            <p className="sub">
              Last updated: {PRIVACY_UPDATED} ·{" "}
              <a href={PRIVACY_URL} target="_blank" rel="noopener">
                Open on docforge.live <ExternalLink size={11} strokeWidth={2} />
              </a>
            </p>
          </div>
          <button ref={closeRef} className="modal-close" onClick={onClose} aria-label="Close">
            <X size={16} strokeWidth={2} />
          </button>
        </div>

        <div
          className="policy-body"
          ref={bodyRef}
          onScroll={checkEnd}
          tabIndex={0}
          dangerouslySetInnerHTML={{ __html: PRIVACY_HTML }}
        />

        <div className="tut-foot policy-foot">
          <span className="policy-hint" aria-live="polite">
            {atEnd ? "" : "Scroll to the end to accept."}
          </span>
          <button className="btn secondary small" onClick={onClose}>
            Close
          </button>
          <button className="btn small" onClick={onAccept} disabled={!atEnd}>
            <Check size={13} strokeWidth={2.4} /> Accept
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
