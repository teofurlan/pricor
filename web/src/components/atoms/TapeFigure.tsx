import type { CSSProperties, HTMLAttributes } from "react";
import type { Language } from "../../api/types";
import { formatInteger } from "../../lib/decimalText";

export interface SplitParts {
  intPart: string;
  fracPart: string;
}

/** Splits an already formatted figure at its language's decimal mark, so a thousands dot never reads as decimals. */
export function splitFigure(text: string | number, language: Language = "en"): SplitParts {
  const s = String(text);
  const pattern = language === "es" ? /^(.*?)(,\d+…?)(\s+.*)?$/ : /^(.*?)(\.\d+…?)(\s+.*)?$/;
  const match = s.match(pattern);
  if (match) {
    const intPart = match[1];
    const fracPart = (match[2] || "") + (match[3] || "");
    return { intPart, fracPart };
  }
  return { intPart: s, fracPart: "" };
}

export function TapeFigure({
  value,
  full,
  className = "",
  fracWidth,
  language = "en",
  style,
  ...props
}: {
  /** Text already written for `language` (see formatFigure); a number is formatted here. */
  value: string | number;
  language?: Language;
  full?: string;
  className?: string;
  fracWidth?: number;
} & HTMLAttributes<HTMLSpanElement>) {
  const { intPart, fracPart } = splitFigure(typeof value === "number" ? formatInteger(value, language) : value, language);
  const combinedStyle: CSSProperties = {
    ...style,
    ...(fracWidth !== undefined ? ({ "--frac-width": `${fracWidth}ch` } as CSSProperties) : {}),
  };

  return (
    <span
      className={`num-split ${className}`.trim()}
      title={full}
      style={combinedStyle}
      {...props}
    >
      <span className="num-int">{intPart}</span>
      <span className="num-frac">{fracPart}</span>
    </span>
  );
}
