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

/** The mark that separates the decimals in `language` (es-AR: comma, en: point). */
export function decimalMark(language: Language): string {
  return MARKS[language].decimal;
}

/** A whole number such as a counter, grouped the way `language` writes it. */
export function formatInteger(value: number, language: Language): string {
  return formatDecimalText(String(Math.trunc(value)), language);
}

const FIGURE = /^([+-]?)(\d+(?:\.\d+)?)(.*)$/s;

/** A figure that may carry a sign or a trailing unit ("+855.00 ARS"): only its number is rewritten. */
export function formatFigure(text: string, language: Language): string {
  const match = FIGURE.exec(text);
  if (!match) return text;
  const [, sign, number, rest] = match;
  return `${sign}${formatDecimalText(number, language)}${rest}`;
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
