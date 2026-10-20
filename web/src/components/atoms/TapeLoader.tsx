import type { ReactNode } from "react";

/** Paper advancing through a slot: the one animated sign that the app is working. */
export function TapeLoader({
  size = "normal",
  text,
  announce = true,
}: {
  size?: "normal" | "small";
  text: ReactNode;
  /** Off inside a button, which announces itself through `aria-busy`. */
  announce?: boolean;
}) {
  return (
    <span
      className={`tape-loader${size === "small" ? " tape-loader--small" : ""}`}
      {...(announce ? { role: "status", "aria-busy": true } : {})}
    >
      <span className="tape-loader__slot" aria-hidden="true">
        <span className="tape-loader__tape">
          <span className="tape-loader__line" />
          <span className="tape-loader__line" />
          {size === "normal" && <span className="tape-loader__line" />}
        </span>
      </span>
      <span className="tape-loader__text">{text}</span>
    </span>
  );
}
