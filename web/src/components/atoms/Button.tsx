import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "quiet" | "link";

export function Button({
  variant = "quiet",
  className = "",
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return <button type={type} className={`button button--${variant} ${className}`.trim()} {...props} />;
}
