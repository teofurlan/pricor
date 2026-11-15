export type FileKind = "xlsx" | "xls" | "xlsm" | "csv" | "other";

/** The kind of price list a file name suggests, from its extension. */
export function fileKind(name: string): FileKind {
  const extension = name.includes(".") ? name.slice(name.lastIndexOf(".") + 1).toLowerCase() : "";
  return extension === "xlsx" || extension === "xls" || extension === "xlsm" || extension === "csv" ? extension : "other";
}

/**
 * A printed slip that tells the kind of file at a glance: a cell grid for the Excel kinds, comma-separated
 * rows for CSV, a gear for macro workbooks, and the kind in figures underneath.
 */
export function FileMark({ name }: { name: string }) {
  const kind = fileKind(name);
  const excel = kind === "xlsx" || kind === "xls" || kind === "xlsm";
  return (
    <span className="file-mark" data-kind={kind} aria-hidden="true">
      <svg width="40" height="48" viewBox="0 0 40 48" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <path d="M5 3h20l10 10v32H5z" />
        <path d="M25 3v10h10" />
        {excel && (
          <>
            <path d="M10 20h20v18H10z" />
            <path d="M10 26h20M10 32h20M17 20v18" />
          </>
        )}
        {kind === "xlsm" && <circle cx="30" cy="38" r="5" fill="var(--paper)" />}
        {kind === "xlsm" && <path d="M30 35.5v5M27.5 38h5" />}
        {kind === "csv" && (
          <>
            <path d="M10 21h5M19 21h4M27 21h3M10 28h6M20 28h3M27 28h3M10 35h4M18 35h6M28 35h2" />
            <path d="M16.5 22.5l-.8 1.6M24.5 22.5l-.8 1.6M17.5 29.5l-.8 1.6M24.5 29.5l-.8 1.6M15.5 36.5l-.8 1.6M25.5 36.5l-.8 1.6" />
          </>
        )}
        {kind === "other" && <path d="M10 22h20M10 28h20M10 34h14" />}
      </svg>
      <span className="file-mark__label">{kind === "other" ? "?" : kind.toUpperCase()}</span>
    </span>
  );
}
