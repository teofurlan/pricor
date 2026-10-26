import type { Language } from "../api/types";

/**
 * The server explains questions, column issues and errors in English. These rules give the
 * Spanish interface the same sentences; a text without a rule is shown as the server wrote it.
 * Keep them in step with `domain/plan_builder.py`, `domain/cells.py` and
 * `application/reuse_supplier_plan.py`.
 */
const ROLE_LABELS: Record<string, string> = {
  "the product code": "el código de producto",
  "supplier_code": "el código de producto",
  "code": "el código de producto",
  "the description": "la descripción",
  "description": "la descripción",
  "the cost price": "el precio de costo",
  "cost_price": "el precio de costo",
  "the barcode": "el código de barras",
  "barcode": "el código de barras",
  "the retail price": "el precio de venta sugerido",
  "retail_price": "el precio de venta sugerido",
  "suggested_retail_price": "el precio de venta sugerido",
  "the vat rate": "la alícuota de IVA",
  "vat_rate": "la alícuota de IVA",
  "the units per pack": "las unidades por bulto",
  "units_per_pack": "las unidades por bulto",
  "the discount": "el descuento",
  "discount": "el descuento",
  "the currency": "la moneda",
  "currency": "la moneda",
};

const role = (label: string) => ROLE_LABELS[label] ?? label;

const RULES: Array<[RegExp, (...groups: string[]) => string]> = [
  [/^no column was identified as (.+)$/, (label) => `ninguna columna se identificó como ${role(label)}`],
  [/^(\d+) columns were identified as (.+); exactly one is needed$/, (count, label) => `${count} columnas se identificaron como ${role(label)}; se necesita exactamente una`],
  [/^(\d+) columns were identified as (.+)$/, (count, label) => `${count} columnas se identificaron como ${role(label)}`],
  [/^it is not known whether the cost price includes VAT$/, () => "no se sabe si el precio de costo incluye IVA"],
  [/^prices include VAT but there is no VAT column or constant rate$/, () => "los precios incluyen IVA, pero no hay una columna de IVA ni una alícuota fija"],
  [/^a units-per-pack source exists but it is not known whether the price is per pack$/, () => "hay un dato de unidades por bulto, pero no se sabe si el precio es por bulto"],
  [/^the price is per pack but no units-per-pack source is known$/, () => "el precio es por bulto, pero no se sabe cuántas unidades trae cada bulto"],
  [/^the currency of the prices is not known$/, () => "no se sabe en qué moneda están los precios"],
  [/^a currency column exists but its values are not all recognized as currencies$/, () => "hay una columna de moneda, pero no todos sus valores se reconocen como monedas"],
  [/^a currency column exists; its values were read as (.+) and need the user's confirmation$/, (map) => `hay una columna de moneda; sus valores se leyeron como ${map} y hace falta su confirmación`],
  [/^the confirmed currency map does not cover: (.+)$/, (values) => `la tabla de monedas confirmada no cubre: ${values}`],
  [/^the prices include (.+); it is not known whether to convert them to (\w+)$/, (codes, target) => `los precios incluyen ${codes}; no se sabe si convertirlos a ${target}`],
  [/^the prices include (.+); one exchange rate cannot convert more than one currency$/, (codes) => `los precios incluyen ${codes}; una sola cotización no puede convertir más de una moneda`],
  [/^column (.+) does not read as numbers, so its decimal and thousands separators are unknown$/, (name) => `la columna ${name} no se lee como números, así que no se conocen sus separadores de decimales y de miles`],
  [/^(\d+) value\(s\) such as (.+) read as either thousands groups or decimals, and nothing else settles it$/, (count, example) => `${count} valor(es) como ${example} se pueden leer como miles o como decimales, y nada más lo resuelve`],
  [/^conflicting evidence: (.+) is decimal in (.+) but (.+) is decimal in (.+)$/, (a, inA, b, inB) => `la evidencia se contradice: ${a} es decimal en ${inA} pero ${b} es decimal en ${inB}`],
  [/^(.+) is the decimal separator: (\d+) value\(s\) prove it, e\.g\. (.+)$/, (separator, count, example) => `${separator} es el separador decimal: lo prueban ${count} valor(es), por ejemplo ${example}`],
  [/^no separators in any value$/, () => "ningún valor tiene separadores"],
  [/^native numeric cells carry no separators$/, () => "las celdas numéricas nativas no tienen separadores"],
  [/^no values$/, () => "no hay valores"],
  [/^the discount column (.+) that plan v(\d+) applies is no longer in the file; assign the discount role to another column or start again as a first import$/, (name, version) => `la columna de descuento ${name} que aplica el plan v${version} ya no está en el archivo; asigne el rol de descuento a otra columna o empiece de nuevo como primera importación`],
  [/^(.+): (.+) is empty$/, (column, roleName) => `${column}: ${role(roleName)} está vacío`],
  [/^(.+): conditional quantity discount '([^']*)' cannot be applied to a unit cost$/, (column, value) => `${column}: el descuento por cantidad condicional '${value}' no se puede aplicar a un costo unitario`],
  [/^(.+): unreadable discount: '([^']*)'$/, (column, value) => `${column}: descuento ilegible: '${value}'`],
];

export function localizeServerText(text: string, language: Language): string {
  if (language !== "es") return text;
  for (const [pattern, translate] of RULES) {
    const match = pattern.exec(text);
    if (match) return translate(...match.slice(1));
  }
  return text;
}

/**
 * Session notices name a stage and quote the error behind it. In Spanish the sentence is
 * translated and the error (class and message, which only the library can word) is kept apart
 * as technical detail. Keep them in step with `application/cascade.py` and
 * `application/import_first_time.py`.
 */
const NOTICE_RULES: Array<[RegExp, (...groups: string[]) => { text: string; detail: string }]> = [
  [/^stage '(.+?)' could not classify columns \((\w+)\): ([\s\S]*)$/, (stage, kind, message) => ({ text: `La etapa '${stage}' no pudo clasificar las columnas.`, detail: `${kind}: ${message}` })],
  [/^stage '(.+?)' was skipped: ([\s\S]*)$/, (stage, reason) => ({ text: `Se omitió la etapa '${stage}'.`, detail: reason })],
  [/^the plan advisor could not help \((\w+)\): ([\s\S]*)$/, (kind, message) => ({ text: "El asesor del plan no pudo ayudar.", detail: `${kind}: ${message}` })],
  [/^semantic memory could not be retrieved \((\w+)\): ([\s\S]*)$/, (kind, message) => ({ text: "No se pudo consultar la memoria semántica.", detail: `${kind}: ${message}` })],
];

/** A session notice: the server's text in English; in Spanish a sentence plus its technical detail. */
export function localizeNotice(message: string, language: Language): { text: string; detail: string | null } {
  if (language === "es") {
    for (const [pattern, translate] of NOTICE_RULES) {
      const match = pattern.exec(message);
      if (match) return translate(...match.slice(1));
    }
  }
  return { text: message, detail: null };
}

const SPANISH_ERRORS: Record<string, string> = {
  invalid_input: "El servidor rechazó ese dato. Revíselo e intente de nuevo.",
  invalid_request: "El servidor no entendió el pedido. Revise los datos e intente de nuevo.",
  invalid_operation: "Ese paso no se puede hacer ahora. Revise el paso actual de la importación.",
  application_error: "El servidor no pudo completar el pedido con esos datos.",
  session_not_found: "Esta importación ya no existe. Empiece una nueva.",
  question_not_found: "Esa pregunta ya no está abierta en esta importación.",
  output_format_not_found: "Todavía no hay columnas propias guardadas.",
  memory_not_found: "Esa nota ya no existe.",
  invalid_memory_text: "La nota no es válida. Revise el texto e intente de nuevo.",
  accepted_suggestion_conflict: "Esa sugerencia ya no coincide con su respuesta, así que no se guardó.",
  model_unavailable: "Los modelos locales no responden ahora. Puede seguir respondiendo usted.",
  memory_unavailable: "La memoria no está disponible ahora.",
  embedder_unavailable: "El modelo que busca en la memoria no está disponible ahora.",
  unsupported_format: "Ese tipo de archivo no se puede leer. Use Excel (.xls, .xlsx) o CSV.",
  file_too_large: "El archivo es demasiado grande.",
  too_many_rows: "El archivo tiene demasiadas filas.",
  unreadable_file: "No se pudo leer el archivo. Revise que no esté dañado ni vacío.",
  internal_error: "Algo falló dentro de Pricor. Intente de nuevo.",
};

/** A failed call for an error banner: the server's message in English, a Spanish sentence in Spanish. */
export function describeError(error: { code: string; message: string }, language: Language): string {
  if (language !== "es") return error.message;
  return SPANISH_ERRORS[error.code] ?? `Ocurrió un error inesperado (detalle: ${error.message}).`;
}

/** A `constant:` answer as the interface writes numbers: "10,5 %" in Spanish, "10.5%" in English. */
export function formatTypedValue(questionId: string, token: string, language: Language): string {
  const value = token.replace(/^constant:/, "");
  const percent = questionId === "vat_rate";
  if (language === "es") return value.replace(".", ",") + (percent ? " %" : "");
  return value + (percent ? "%" : "");
}
