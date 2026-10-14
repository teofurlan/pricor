import { useState } from "react";
import type { HeaderCandidate } from "../../api/types";
import { useI18n } from "../../i18n";
import { Button } from "../atoms/Button";

interface Props {
  candidates: HeaderCandidate[];
  busy: boolean;
  onChoose(rowIndex: number | null): void;
}

/** The profiler could not settle which row holds the column names: the user decides. */
export function HeaderChoice({ candidates, busy, onChoose }: Props) {
  const { t } = useI18n();
  const [chosen, setChosen] = useState<number | null>(null);
  return (
    <div className="stack">
      <p className="lede">{t("header.lede")}</p>
      <div className="choices" role="radiogroup" aria-label={t("header.title")}>
        {candidates.map((candidate) => (
          <label key={candidate.row_index} className="choice choice--row">
            <input
              type="radio"
              name="header-row"
              checked={chosen === candidate.row_index}
              onChange={() => setChosen(candidate.row_index)}
            />
            <span className="choice__label">
              <strong>{t("header.row", { row: candidate.file_row })}</strong>
              <span className="choice__cells">{candidate.cells.filter((cell) => cell.trim() !== "").join(", ")}</span>
            </span>
          </label>
        ))}
      </div>
      <div className="actions">
        <Button variant="primary" disabled={busy || chosen === null} onClick={() => chosen !== null && onChoose(chosen)}>
          {t("header.use")}
        </Button>
        <Button disabled={busy} onClick={() => onChoose(null)}>
          {t("header.none")}
        </Button>
      </div>
    </div>
  );
}
