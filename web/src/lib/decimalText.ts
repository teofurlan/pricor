import type { Language } from "../api/types";

/** Exact decimal text from the API shown the way each language writes numbers; digits are never rounded. */

const DECIMAL = /^(-?)(\d+)(?:\.(\d+))?$/;
const MAX_FRACTION = 6;
const MARKS = { es: { group: ".", decimal: "," }, en: { group: ",", decimal: "." } } as const;

export function formatDecimalText(text: string, language: Language): string {
  const match = DECIMAL.exec(text);
  if (!match) return text;
  const [, sign, whole, fraction = ""] = match;
  const marks = MARKS[language];
  const grouped = whole.replace(/\B(?=(\d{3})+$)/g, marks.group);
  const cut = fraction.length > MAX_FRACTION;
  const shown = cut ? fraction.slice(0, MAX_FRACTION).replace(/0+$/, "") : fraction;
  return `${sign}${grouped}${shown ? marks.decimal + shown : ""}${cut ? "…" : ""}`;
}

interface Conversion {
  source: string;
  rate: string;
  value: string;
}

/** "2,588 USD × 1.550 = 4.011,40 ARS": the input the engine really used, not the rounded cost. */
export function conversionText(step: Conversion, from: string, to: string, language: Language): string {
  const format = (text: string) => formatDecimalText(text, language);
  return `${format(step.source)} ${from} × ${format(step.rate)} = ${format(step.value)} ${to}`;
}
