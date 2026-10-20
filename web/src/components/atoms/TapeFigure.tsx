import type { CSSProperties, HTMLAttributes } from "react";

export interface SplitParts {
  intPart: string;
  fracPart: string;
}

export function splitFigure(text: string | number): SplitParts {
  const s = String(text);
  // Matches integer part and decimal separator (. or , followed by digits/ellipsis, plus optional trailing currency/unit)
  const match = s.match(/^(.*?)([.,]\d+…?)(\s+.*)?$/);
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
  style,
  ...props
}: {
  value: string | number;
  full?: string;
  className?: string;
  fracWidth?: number;
} & HTMLAttributes<HTMLSpanElement>) {
  const { intPart, fracPart } = splitFigure(value);
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
