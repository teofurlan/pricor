# Pricor: agent instructions

Product context lives in `PRODUCT.md`; the committed visual world of the web app lives in `.impeccable/surfaces/web-src.md`.

## Web UI changes go through Impeccable

Every change under `web/` that affects what the user sees (components, styles, copy, layout, states) goes through the Impeccable skill (`/impeccable`), so the interface follows one standard instead of generic AI defaults.

1. Run `impeccable context` once per session with `--target` set to the changed file, and read the surface brief it points to.
2. Read `reference/craft-floor.md` from the Impeccable skill immediately before editing UI code.
3. Treat changes as in-world: inherit the adding-machine-tape look from the surface brief unless the user asks for a redesign.
4. When the change is finished, run the detector once over the changed files (`impeccable detect --json <files>`) and fix real findings.
5. Look at the rendered result at the sizes it ships at (desktop first, then 375 px wide) before calling the change done.

Backend-only changes do not need this step.

## Checks

- Backend: `uv run pytest`
- Web: `npm test` and `npm run build`, run from `web/` (Vitest needs `web/` as its working directory to load jsdom).
