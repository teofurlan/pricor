import { describe, expect, it } from "vitest";
import { conversionText, decimalMark, formatDecimalText, formatFigure, formatInteger } from "./decimalText";

describe("formatDecimalText", () => {
  it("groups thousands and writes the decimal mark the way each language does", () => {
    expect(formatDecimalText("1550", "es")).toBe("1.550");
    expect(formatDecimalText("2.588", "es")).toBe("2,588");
    expect(formatDecimalText("4011.40", "es")).toBe("4.011,40");
    expect(formatDecimalText("1550", "en")).toBe("1,550");
    expect(formatDecimalText("4011.40", "en")).toBe("4,011.40");
    expect(formatDecimalText("-1234567.5", "es")).toBe("-1.234.567,5");
  });

  it("keeps the digits exactly, trailing zeros included", () => {
    expect(formatDecimalText("2.50", "en")).toBe("2.50");
  });

  it("cuts a long fraction for reading and says so", () => {
    expect(formatDecimalText("2.58800000000000000000000001", "en")).toBe("2.588…");
    expect(formatDecimalText("904.97737556561085912", "en")).toBe("904.977375…");
  });

  it("returns text that is not a plain decimal untouched", () => {
    expect(formatDecimalText("n/a", "es")).toBe("n/a");
  });
});

describe("conversionText", () => {
  const step = { source: "2.588", rate: "1550", value: "4011.40" };

  it("shows the real input, the rate and the result", () => {
    expect(conversionText(step, "USD", "ARS", "es")).toBe("2,588 USD × 1.550 = 4.011,40 ARS");
    expect(conversionText(step, "USD", "ARS", "en")).toBe("2.588 USD × 1,550 = 4,011.40 ARS");
  });
});

describe("formatInteger", () => {
  it("groups four-digit counters the way each language does", () => {
    expect(formatInteger(1234, "es")).toBe("1.234");
    expect(formatInteger(1234, "en")).toBe("1,234");
    expect(formatInteger(12, "es")).toBe("12");
  });
});

describe("formatFigure", () => {
  it("formats the number inside a figure that ends with a currency or sign", () => {
    expect(formatFigure("3387.84 ARS", "es")).toBe("3.387,84 ARS");
    expect(formatFigure("+3387.84 ARS", "es")).toBe("+3.387,84 ARS");
    expect(formatFigure("3387.84", "en")).toBe("3,387.84");
    expect(formatFigure("2.50", "es")).toBe("2,50");
    expect(formatFigure("sin dato", "es")).toBe("sin dato");
  });
});

describe("decimalMark", () => {
  it("is the comma in Spanish and the point in English", () => {
    expect(decimalMark("es")).toBe(",");
    expect(decimalMark("en")).toBe(".");
  });
});
