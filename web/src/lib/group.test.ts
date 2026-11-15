import { afterEach, describe, expect, it } from "vitest";
import { captureGroup, storedGroup } from "./group";

afterEach(() => {
  window.sessionStorage.clear();
  window.history.replaceState(null, "", "/");
});

describe("captureGroup", () => {
  it("keeps a valid g in sessionStorage and removes it from the URL, keeping the rest", () => {
    window.history.replaceState(null, "", "/p?lang=es&g=grupo-1_a#frag");

    expect(captureGroup()).toBe("grupo-1_a");
    expect(window.sessionStorage.getItem("pricor_group")).toBe("grupo-1_a");
    expect(window.location.search).toBe("?lang=es");
    expect(window.location.pathname).toBe("/p");
    expect(window.location.hash).toBe("#frag");
  });

  it("removes an invalid g from the URL without storing it", () => {
    window.history.replaceState(null, "", "/?g=Bad%20Group");

    expect(captureGroup()).toBeNull();
    expect(window.sessionStorage.getItem("pricor_group")).toBeNull();
    expect(window.location.search).toBe("");
  });

  it("rejects more than 40 characters", () => {
    window.history.replaceState(null, "", `/?g=${"a".repeat(41)}`);
    expect(captureGroup()).toBeNull();
    window.history.replaceState(null, "", `/?g=${"a".repeat(40)}`);
    expect(captureGroup()).toBe("a".repeat(40));
  });

  it("keeps the stored group when the URL has none (a second pass or a reload)", () => {
    window.history.replaceState(null, "", "/?g=uno");
    captureGroup();

    expect(captureGroup()).toBe("uno");
    expect(storedGroup()).toBe("uno");
  });

  it("keeps the #w= personal link fragment untouched", () => {
    const token = "A".repeat(43);
    window.history.replaceState(null, "", `/?g=uno#w=${token}`);

    captureGroup();

    expect(window.location.hash).toBe(`#w=${token}`);
  });

  it("does nothing without a g", () => {
    expect(captureGroup()).toBeNull();
    expect(storedGroup()).toBeNull();
  });
});
