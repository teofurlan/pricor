import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

afterEach(() => vi.unstubAllGlobals());

describe("warming the models on page load (S18)", () => {
  it("posts to /warm-up exactly once on mount, whatever the answer", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("offline"));
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    await Promise.resolve();

    const warmUps = fetchMock.mock.calls.filter(([url]) => url === "/warm-up");
    expect(warmUps).toHaveLength(1);
    expect(warmUps[0][1].method).toBe("POST");
  });
});
