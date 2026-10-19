# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The primary user is the owner or manager of a small Argentine store, such as a hardware store, distributor or kiosk. Every week they receive price lists from suppliers in Excel or CSV, each in a different format, and prepare the costs for import into their own store-management system. They work on a desktop PC (Windows) in the back office and have no technical background.

## Product Purpose

Pricor turns heterogeneous supplier price lists into consistent, importable product records: supplier code, description, net unit cost and currency, with optional fields and row-level traceability. It exists because store systems only import fixed formats, and misreading the unit, the VAT treatment or the discounts silently corrupts costs.

Success means the user approves a list knowing exactly what was assumed. A recurring supplier's next list is then reused with only its changes re-asked, and the user sees what changed in price.

## Positioning

Open-weight models run locally and only interpret the file: they propose column roles and suggest answers. The user confirms. A deterministic engine with exact decimal math, working from a closed catalog of operations, does every calculation. No model output is ever executed, and nothing leaves the computer. Pricor prepares the file; it does not replace the store's management system.

## Operating Context

- **First import:** upload a list, confirm the header row and column roles (Laya, then Gemma, then the user), answer the plan questions (VAT included, price per pack, discounts, currency, exchange rate), review a per-step preview of original against transformed values, approve, and export CSV/XLSX plus a rejected-rows report.
- **Reuse:** the next list from the same supplier reuses the saved plan. Moved, new or missing columns are flagged, and only what changed is asked again.
- **Price report:** compare consecutive lists to see increases, decreases, new and discontinued products, and anomalies with an adjustable threshold.
- **Memory:** notes the user writes, or Gemma suggestions they accept ("Remember this"), are retrieved as context for later imports. Suggestions cite the notes they used, and a Memory panel lets the user view, edit and delete them.

## Capabilities and Constraints

- Local web app served by FastAPI, with a React + Vite + TypeScript frontend; SQLite storage; Ollama for Gemma 4 E4B and bge-m3; an optional fine-tuned Laya classifier on a CUDA GPU.
- When a model is unavailable, the import continues and asks the user more. Model confidence is shown as uncalibrated unless a threshold was calibrated.
- Partial imports are allowed, but rejected rows are always visible and exportable. Nothing is omitted silently.
- Bilingual UI: English and Spanish, with a language toggle and a question language chosen per import.
- Out of scope: PDFs, multi-supplier consolidation, ERP-specific export formats, an installable desktop app.

## Brand Commitments

- Name: **Pricor** (price + order).
- Line: "The models fill the form, the engine does the math, you sign."
- Promise: nothing leaves this computer.
- Bilingual EN/ES interface.

## Evidence on Hand

- Real public supplier lists from six distributors (gitignored under `data/raw/`). An explicitly labeled SIMULATED week-2 list exists for Distribución Masiva.
- Benchmark of column classifiers on 29 held-out columns: `docs/benchmark.md`.
- Verified browser rehearsal and its evidence under `docs/private/submission/`.
- No paying customer, user interview, measured time savings or testimonial exists. Do not fabricate any.

## Product Principles

1. Interpretation is proposed, never applied: every assumption that changes a cost is confirmed by the user.
2. Show the math: the original value, each applied step and the result stay visible and traceable.
3. Nothing silent: rejected rows, unavailable models and uncertain columns are always surfaced.
4. Local and private by default.
5. A recurring supplier should cost less attention each week than the last.

## Accessibility & Inclusion

Desktop first (Windows PC), meeting WCAG 2.2 AA for contrast and keyboard operation. On mobile the app must work but is not the design focus.
