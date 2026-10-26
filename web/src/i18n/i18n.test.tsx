import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { en } from "./en";
import { es } from "./es";
import { I18nProvider, interpolate, useI18n } from "./index";

describe("dictionaries", () => {
  it("define the same keys in English and Spanish", () => {
    expect(Object.keys(es).sort()).toEqual(Object.keys(en).sort());
  });

  it("never leave a Spanish string empty", () => {
    const empty = Object.entries(es).filter(([, value]) => value.trim() === "");
    expect(empty).toEqual([]);
  });

  it("use the same placeholders in both languages", () => {
    const placeholders = (text: string) => (text.match(/\{\w+\}/g) ?? []).sort();
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      expect(placeholders(es[key]), key).toEqual(placeholders(en[key]));
    }
  });
});

describe("interpolate", () => {
  it("fills named placeholders", () => {
    expect(interpolate("{a} of {b}", { a: 2, b: "5" })).toBe("2 of 5");
  });

  it("keeps an unknown placeholder visible instead of dropping it", () => {
    expect(interpolate("hello {name}", {})).toBe("hello {name}");
  });
});

function Probe() {
  const { t, language, setLanguage } = useI18n();
  return (
    <div>
      <p data-testid="lang">{language}</p>
      <p>{t("app.name")}</p>
      <button onClick={() => setLanguage(language === "en" ? "es" : "en")}>switch</button>
    </div>
  );
}

describe("I18nProvider", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("starts in English and switches the whole tree to Spanish", async () => {
    render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    );
    expect(screen.getByTestId("lang")).toHaveTextContent("en");
    await userEvent.click(screen.getByRole("button", { name: "switch" }));
    expect(screen.getByTestId("lang")).toHaveTextContent("es");
    expect(document.documentElement.lang).toBe("es");
  });

  it("defaults to Spanish when navigator.language is es-AR", () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("es-AR");
    render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    );
    expect(screen.getByTestId("lang")).toHaveTextContent("es");
  });

  it("defaults to English when navigator.language is en-US", () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("en-US");
    render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    );
    expect(screen.getByTestId("lang")).toHaveTextContent("en");
  });

  it("defaults to Spanish when navigator.language is pt-BR", () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("pt-BR");
    render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    );
    expect(screen.getByTestId("lang")).toHaveTextContent("es");
  });

  it("uses stored choice if present even when navigator is Spanish", () => {
    localStorage.setItem("pricor.language", "en");
    vi.spyOn(navigator, "language", "get").mockReturnValue("es-AR");
    render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    );
    expect(screen.getByTestId("lang")).toHaveTextContent("en");
  });

  it("uses stored choice if present even when navigator is English", () => {
    localStorage.setItem("pricor.language", "es");
    vi.spyOn(navigator, "language", "get").mockReturnValue("en-US");
    render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    );
    expect(screen.getByTestId("lang")).toHaveTextContent("es");
  });

  it("falls back to navigator when storage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });
    vi.spyOn(navigator, "language", "get").mockReturnValue("es-AR");
    render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    );
    expect(screen.getByTestId("lang")).toHaveTextContent("es");
  });
});
