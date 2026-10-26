import { describe, expect, it } from "vitest";
import { conversionText, formatDecimalText } from "./decimalText";

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
