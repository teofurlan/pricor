import type { OutputKind } from "../api/types";

/** The order the type select offers them in. */
export const OUTPUT_KINDS: readonly OutputKind[] = ["text", "description", "code", "number", "price"];

const FIELD_KINDS: Record<string, OutputKind> = {
  description: "description",
  supplier_code: "code",
  barcode: "code",
  unit_cost_net: "price",
  unit_price: "price",
  suggested_retail_price: "price",
  unit_cost_net_converted: "price",
  vat_rate: "number",
  units_per_pack: "number",
  fx_rate: "number",
  source_row: "number",
};

/** The type a source implies; mirrors the server's `default_kind`. */
export function defaultKind(source: string): OutputKind {
  return source.startsWith("field:") ? (FIELD_KINDS[source.slice("field:".length)] ?? "text") : "text";
}

/** Where a value of this type usually comes from; text has no usual field. */
export const SUGGESTED_SOURCE: Partial<Record<OutputKind, string>> = {
  description: "field:description",
  code: "field:supplier_code",
  price: "field:unit_cost_net",
  number: "field:units_per_pack",
};

/** The source to switch to when the user picks `kind`, or null to keep the current one. */
export function suggestSource(kind: OutputKind, source: string): string | null {
  const suggestion = SUGGESTED_SOURCE[kind];
  if (!suggestion) return null;
  const replaceable = source === "empty" || (source.startsWith("field:") && defaultKind(source) !== kind);
  return replaceable ? suggestion : null;
}
