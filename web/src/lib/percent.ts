/** Percentages and ratios as exact decimal text: the digits are shifted, never multiplied. */

const PERCENT_TEXT = /^\d+(?:[.,]\d+)?$/;
const ZERO = /^0*(?:\.0*)?$/;

/** What the user typed in a percent field ("30", "4,5") as the ratio the API takes ("0.30"), or null. */
export function percentToRatio(text: string): string | null {
  const trimmed = text.trim();
  if (!PERCENT_TEXT.test(trimmed)) return null;
  const [whole, fraction = ""] = trimmed.replace(",", ".").split(".");
  if (ZERO.test(trimmed.replace(",", "."))) return "0";
  const digits = whole + fraction;
  const point = whole.length - 2;
  return point <= 0 ? `0.${"0".repeat(-point)}${digits}` : `${digits.slice(0, point)}.${digits.slice(point)}`;
}

/** A ratio from the API ("0.045") as the percent to show in a field ("4.5"). */
export function ratioToPercent(ratio: string): string {
  const [whole, fraction = ""] = ratio.split(".");
  const padded = fraction.padEnd(2, "0");
  const integer = (whole + padded.slice(0, 2)).replace(/^0+(?=\d)/, "");
  const rest = padded.slice(2).replace(/0+$/, "");
  return rest ? `${integer}.${rest}` : integer;
}

/** A display percentage ("4.20") with an explicit sign for increases: "+4.20%". */
export function signedPercent(value: string): string {
  return value.startsWith("-") || ZERO.test(value) ? `${value}%` : `+${value}%`;
}
