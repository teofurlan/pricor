import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "../atoms/Button";

/** Matches the `.drawer` transform transition in styles.css. */
const EXIT_MS = 240;

interface Props {
  open: boolean;
  label: string;
  closeLabel: string;
  onClose(): void;
  /** A modifier class, also suffixed with `--closing` while the drawer leaves. */
  className: string;
  children: ReactNode;
}

/**
 * A non-modal side panel. It slides in from the edge it lives on and leaves the same way,
 * stays unusable while leaving, and returns focus to whatever opened it.
 */
export function SideDrawer({ open, label, closeLabel, onClose, className, children }: Props) {
  const panelRef = useRef<HTMLElement>(null);
  // The drawer stays mounted while it slides back out the way it came in.
  const [present, setPresent] = useState(open);
  if (open && !present) setPresent(true);

  useEffect(() => {
    if (open || !present) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? true;
    if (reduced) { setPresent(false); return; }
    const timer = window.setTimeout(() => setPresent(false), EXIT_MS);
    return () => window.clearTimeout(timer);
  }, [open, present]);

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    panelRef.current?.querySelector("button")?.focus();
    return () => { if (opener?.isConnected) opener.focus(); };
  }, [open]);

  if (!present) return null;
  const closing = !open;

  return (
    <aside
      ref={panelRef}
      className={`drawer ${className}${closing ? ` drawer--closing ${className}--closing` : ""}`}
      inert={closing}
      aria-label={label}
      onKeyDown={(event) => {
        if (event.key === "Escape") { event.stopPropagation(); onClose(); }
      }}
    >
      <div className="drawer__close">
        <Button variant="link" onClick={onClose}>{closeLabel}</Button>
      </div>
      {children}
    </aside>
  );
}
