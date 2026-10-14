import { describe, expect, it } from "vitest";
import { percentToRatio, ratioToPercent, signedPercent } from "./percent";

describe("percentToRatio", () => {
  it.each([
    ["30", "0.30"],
    ["4.5", "0.045"],
    ["4,5", "0.045"],
    ["0", "0"],
    ["100", "1.00"],
    ["250", "2.50"],
    ["0.5", "0.005"],
    [" 12 ", "0.12"],
  ])("turns %s into the ratio %s without floating point", (text, ratio) => {
    expect(percentToRatio(text)).toBe(ratio);
  });

  it.each(["", "abc", "-5", "1e3", "30%", "1.2.3", "."])("refuses %j", (text) => {
    expect(percentToRatio(text)).toBeNull();
  });
});

describe("ratioToPercent", () => {
  it.each([
    ["0.30", "30"],
    ["0.045", "4.5"],
    ["0.5", "50"],
    ["1.5", "150"],
    ["0", "0"],
    ["2", "200"],
    ["0.005", "0.5"],
  ])("shows the ratio %s as %s%%", (ratio, percent) => {
    expect(ratioToPercent(ratio)).toBe(percent);
  });
});

describe("signedPercent", () => {
  it.each([
    ["4.20", "+4.20%"],
    ["-1.00", "-1.00%"],
    ["0.00", "0.00%"],
    ["200.00", "+200.00%"],
  ])("writes %s as %s", (value, text) => {
    expect(signedPercent(value)).toBe(text);
  });
});
