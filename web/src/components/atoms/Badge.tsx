import type { ReactNode } from "react";

export type BadgeTone = "heuristics" | "gemma" | "user" | "saved" | "pending" | "neutral" | "good" | "bad";

export function Badge({ tone = "neutral", children }: { tone?: BadgeTone; children: ReactNode }) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}
