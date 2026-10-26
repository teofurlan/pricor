import { useEffect, useId, useRef, useState } from "react";
import type { SampleListing } from "../../api/types";
import { useI18n } from "../../i18n";

interface Props {
  list(): Promise<SampleListing[]>;
  onChoose(sample: SampleListing): void;
  disabled?: boolean;
}

/** One-click synthetic lists next to the drop zone. It is not shown when there are none or the request fails. */
export function SamplePicker({ list, onChoose, disabled = false }: Props) {
  const { t, language } = useI18n();
  const [samples, setSamples] = useState<SampleListing[]>([]);
  const labelId = useId();
  const loadList = useRef(list); // the parent may pass a new function each render; ask once

  useEffect(() => {
    let current = true;
    loadList.current()
      .then((items) => { if (current) setSamples(items); })
      .catch(() => { if (current) setSamples([]); });
    return () => { current = false; };
  }, []);

  if (samples.length === 0) return null;
  return (
    <div className="field samples" role="group" aria-labelledby={labelId}>
      <span id={labelId} className="field__label">{t("upload.samples")}</span>
      <ul className="samples__list">
        {samples.map((sample) => (
          <li key={sample.id}>
            <button type="button" className="button button--key button--choose" disabled={disabled} onClick={() => onChoose(sample)}>
              {sample.title[language]}
            </button>
            <span className="field__hint"> {sample.description[language]}</span>
          </li>
        ))}
      </ul>
      <span className="field__hint">{t("upload.samplesHint")}</span>
    </div>
  );
}
