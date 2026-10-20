import type { ButtonHTMLAttributes } from "react";
import { TapeLoader } from "./TapeLoader";

type Variant = "primary" | "quiet" | "link";

/** A key. While `loading`, it stays pressed-in and shows the paper advancing beside its label. */
export function Button({
  variant = "quiet",
  className = "",
  type = "button",
  loading = false,
  disabled,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  const classes = `button button--${variant}${loading ? " button--busy" : ""} ${className}`.trim();
  return (
    <button type={type} className={classes} disabled={disabled || loading} aria-busy={loading || undefined} {...props}>
      {loading ? <TapeLoader size="small" text={children} announce={false} /> : children}
    </button>
  );
}
