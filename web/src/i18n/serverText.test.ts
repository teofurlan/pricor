import { describe, expect, it } from "vitest";
import { describeError, localizeNotice, localizeServerText } from "./serverText";

describe("localizeServerText", () => {
  it.each([
    ["no column was identified as the cost price", "ninguna columna se identificó como el precio de costo"],
    ["2 columns were identified as the product code; exactly one is needed", "2 columnas se identificaron como el código de producto; se necesita exactamente una"],
    ["3 columns were identified as the barcode", "3 columnas se identificaron como el código de barras"],
    ["it is not known whether the cost price includes VAT", "no se sabe si el precio de costo incluye IVA"],
    ["prices include VAT but there is no VAT column or constant rate", "los precios incluyen IVA, pero no hay una columna de IVA ni una alícuota fija"],
    ["a units-per-pack source exists but it is not known whether the price is per pack", "hay un dato de unidades por bulto, pero no se sabe si el precio es por bulto"],
    ["the price is per pack but no units-per-pack source is known", "el precio es por bulto, pero no se sabe cuántas unidades trae cada bulto"],
    ["the currency of the prices is not known", "no se sabe en qué moneda están los precios"],
    ["a currency column exists but its values are not all recognized as currencies", "hay una columna de moneda, pero no todos sus valores se reconocen como monedas"],
    ["a currency column exists; its values were read as 'U$S' -> USD, '$' -> ARS and need the user's confirmation", "hay una columna de moneda; sus valores se leyeron como 'U$S' -> USD, '$' -> ARS y hace falta su confirmación"],
    ["the confirmed currency map does not cover: 'EUR'", "la tabla de monedas confirmada no cubre: 'EUR'"],
    ["the prices include USD; it is not known whether to convert them to ARS", "los precios incluyen USD; no se sabe si convertirlos a ARS"],
    ["the prices include USD, EUR; one exchange rate cannot convert more than one currency", "los precios incluyen USD, EUR; una sola cotización no puede convertir más de una moneda"],
    ["column 'Precio' does not read as numbers, so its decimal and thousands separators are unknown", "la columna 'Precio' no se lee como números, así que no se conocen sus separadores de decimales y de miles"],
    ["4 value(s) such as '1.250' read as either thousands groups or decimals, and nothing else settles it", "4 valor(es) como '1.250' se pueden leer como miles o como decimales, y nada más lo resuelve"],
    ["conflicting evidence: ',' is decimal in '1,5' but '.' is decimal in '2.5'", "la evidencia se contradice: ',' es decimal en '1,5' pero '.' es decimal en '2.5'"],
    ["no separators in any value", "ningún valor tiene separadores"],
    ["the discount column 'Desc' that plan v2 applies is no longer in the file; assign the discount role to another column or start again as a first import", "la columna de descuento 'Desc' que aplica el plan v2 ya no está en el archivo; asigne el rol de descuento a otra columna o empiece de nuevo como primera importación"],
    ["CODIGO: supplier_code is empty", "CODIGO: el código de producto está vacío"],
    ["DESC: unreadable discount: '10%'", "DESC: descuento ilegible: '10%'"],
    ["DTO: conditional quantity discount '10% x  10 UN' cannot be applied to a unit cost", "DTO: el descuento por cantidad condicional '10% x  10 UN' no se puede aplicar a un costo unitario"],
  ])("translates %j", (english, spanish) => {
    expect(localizeServerText(english, "es")).toBe(spanish);
    expect(localizeServerText(english, "en")).toBe(english);
  });

  it("keeps a text it does not know", () => {
    expect(localizeServerText("steps[2].rate_from: unknown field", "es")).toBe("steps[2].rate_from: unknown field");
  });
});

describe("describeError", () => {
  it("keeps the server's own message in English", () => {
    expect(describeError({ code: "invalid_input", message: "'x' is not an option" }, "en")).toBe("'x' is not an option");
  });

  it("says what went wrong in Spanish for every known code", () => {
    expect(describeError({ code: "invalid_input", message: "'x' is not an option" }, "es")).toBe("El servidor rechazó ese dato. Revíselo e intente de nuevo.");
    expect(describeError({ code: "session_not_found", message: "no session" }, "es")).toBe("Esta importación ya no existe. Empiece una nueva.");
  });

  it("falls back to a Spanish sentence with the technical detail for an unknown code", () => {
    expect(describeError({ code: "teapot", message: "short and stout" }, "es")).toBe("Ocurrió un error inesperado (detalle: short and stout).");
  });
});

describe("localizeNotice", () => {
  it.each([
    [
      "stage 'gemma' could not classify columns (ModelUnavailableError): connection refused",
      "La etapa 'gemma' no pudo clasificar las columnas.",
      "ModelUnavailableError: connection refused",
    ],
    [
      "stage 'laya' was skipped: the Laya model could not be loaded (ImportError: no module); install it",
      "Se omitió la etapa 'laya'.",
      "the Laya model could not be loaded (ImportError: no module); install it",
    ],
    [
      "the plan advisor could not help (ModelTimeoutError): timed out after 30s",
      "El asesor del plan no pudo ayudar.",
      "ModelTimeoutError: timed out after 30s",
    ],
    [
      "semantic memory could not be retrieved (EmbedderUnavailableError): no vector",
      "No se pudo consultar la memoria semántica.",
      "EmbedderUnavailableError: no vector",
    ],
  ])("gives a Spanish sentence for %j and keeps the technical detail apart", (english, sentence, detail) => {
    expect(localizeNotice(english, "es")).toEqual({ text: sentence, detail });
    expect(localizeNotice(english, "en")).toEqual({ text: english, detail: null });
  });

  it("keeps a notice it does not know as the server wrote it", () => {
    expect(localizeNotice("something new happened", "es")).toEqual({ text: "something new happened", detail: null });
  });
});

describe("combined export with different output formats", () => {
  it("explains it in Spanish instead of the generic step message", () => {
    const text = describeError({
      code: "invalid_operation",
      message: "these files were approved with different output formats; export them separately or approve them again with the same format",
    }, "es");
    expect(text).toBe("Estos archivos se aprobaron con formatos de salida distintos. Descárguelos por separado o vuelva a aprobarlos con el mismo formato.");
  });
});
