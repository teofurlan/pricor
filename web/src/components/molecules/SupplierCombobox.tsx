import { useId, useMemo, useState, type KeyboardEvent } from "react";
import { useI18n } from "../../i18n";

interface Props {
  value: string;
  ariaLabel: string;
  suppliers: string[];
  disabled?: boolean;
  onChange(value: string): void;
}

/** Accent- and case-insensitive normalization for filtering saved supplier names. */
function foldForFilter(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim()
    .replace(/\s+/g, " ")
    .toLowerCase();
}

/** Mirrors backend `lookup_key` (preserves accents) so the reuse mark matches server plan lookup. */
function normalizeLookupKey(text: string): string {
  return text
    .replace(/[\u200b-\u200d\ufeff]/g, "")
    .trim()
    .replace(/\s+/g, " ")
    .toLowerCase();
}

/** Free-text supplier input with an in-world dropdown of suppliers that already have a saved plan. */
export function SupplierCombobox({ value, ariaLabel, suppliers, disabled = false, onChange }: Props) {
  const { t } = useI18n();
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  const matches = useMemo(() => {
    if (suppliers.length === 0) return [];
    const query = foldForFilter(value);
    if (!query) return suppliers;
    const prefix: string[] = [];
    const contains: string[] = [];
    for (const supplier of suppliers) {
      const folded = foldForFilter(supplier);
      if (folded.startsWith(query)) prefix.push(supplier);
      else if (folded.includes(query)) contains.push(supplier);
    }
    return [...prefix, ...contains];
  }, [suppliers, value]);

  const exactSavedMatch = useMemo(() => {
    const key = normalizeLookupKey(value);
    return key !== "" && suppliers.some((supplier) => normalizeLookupKey(supplier) === key);
  }, [suppliers, value]);

  const showList = !disabled && open && matches.length > 0;
  const boundedActive = activeIndex >= 0 && activeIndex < matches.length ? activeIndex : -1;
  const activeOptionId = showList && boundedActive >= 0 ? `${listId}-opt-${boundedActive}` : undefined;

  function selectOption(name: string) {
    onChange(name);
    setOpen(false);
    setActiveIndex(-1);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (disabled || matches.length === 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        setActiveIndex(0);
      } else {
        setActiveIndex((current) => (current + 1) % matches.length);
      }
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        setActiveIndex(matches.length - 1);
      } else {
        setActiveIndex((current) => (current <= 0 ? matches.length - 1 : current - 1));
      }
      return;
    }
    if (event.key === "Enter" && showList && boundedActive >= 0) {
      event.preventDefault();
      selectOption(matches[boundedActive]);
      return;
    }
    if (event.key === "Escape" && open) {
      event.preventDefault();
      setOpen(false);
      setActiveIndex(-1);
    }
  }

  return (
    <div className="supplier-combo">
      <div className="supplier-combo__control">
        <input
          aria-label={ariaLabel}
          value={value}
          disabled={disabled}
          autoComplete="off"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={showList}
          aria-controls={showList ? listId : undefined}
          aria-activedescendant={activeOptionId}
          onFocus={() => {
            if (matches.length > 0) setOpen(true);
          }}
          onClick={() => {
            if (matches.length > 0) setOpen(true);
          }}
          onBlur={() => {
            setOpen(false);
            setActiveIndex(-1);
          }}
          onChange={(event) => {
            onChange(event.target.value);
            setOpen(true);
            setActiveIndex(-1);
          }}
          onKeyDown={handleKeyDown}
        />
        {showList && (
          <ul
            id={listId}
            role="listbox"
            aria-label={t("upload.savedSuppliers")}
            className="supplier-combo__list"
          >
            {matches.map((supplier, index) => {
              const active = index === boundedActive;
              return (
                <li
                  key={supplier}
                  id={`${listId}-opt-${index}`}
                  role="option"
                  aria-selected={active}
                  className={`supplier-combo__option${active ? " supplier-combo__option--active" : ""}`}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => selectOption(supplier)}
                >
                  <span className="supplier-combo__name">{supplier}</span>
                  <span className="supplier-combo__tag">{t("upload.savedPlanTag")}</span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      {exactSavedMatch && (
        <span className="supplier-combo__match">{t("upload.savedPlanWillReuse")}</span>
      )}
    </div>
  );
}
