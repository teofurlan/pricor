import { describe, expect, it } from "vitest";
import { defaultKind, suggestSource } from "./outputKind";

describe("output kinds", () => {
  it("derives the type from the source like the server does", () => {
    expect(defaultKind("field:description")).toBe("description");
    expect(defaultKind("field:barcode")).toBe("code");
    expect(defaultKind("field:unit_cost_net")).toBe("price");
    expect(defaultKind("field:vat_rate")).toBe("number");
    expect(defaultKind("field:currency")).toBe("text");
    expect(defaultKind("empty")).toBe("text");
    expect(defaultKind("constant:ARS")).toBe("text");
  });

  it("suggests a source only when the current one is empty or belongs to another type", () => {
    expect(suggestSource("price", "empty")).toBe("field:unit_cost_net");
    expect(suggestSource("price", "field:description")).toBe("field:unit_cost_net");
    expect(suggestSource("price", "field:suggested_retail_price")).toBeNull();
    expect(suggestSource("code", "constant:X")).toBeNull();
    expect(suggestSource("text", "empty")).toBeNull();
    expect(suggestSource("description", "field:supplier_code")).toBe("field:description");
  });
});
