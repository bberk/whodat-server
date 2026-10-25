import { useEffect, useState, type FormEvent } from "react";

import { api } from "../api/endpoints";
import { toDisplayError, type DisplayError } from "../api/errors";
import type { EloConfigResponse } from "../api/types";
import { ApiAlert } from "../components/ApiAlert";
import { ErrorState, LoadingState } from "../components/DataStates";
import { InfoTooltip } from "../components/InfoTooltip";
import {
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "../components/formStyles";
import { useLeague } from "./LeagueContext";

type ConfigState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; config: EloConfigResponse };

type FieldKey =
  "starting_rating" | "k_factor" | "margin_weight" | "margin_cap" | "season_regression";
type FormValues = Record<FieldKey, string>;
type FormErrors = Partial<Record<FieldKey, string>>;

interface FieldSpec {
  key: FieldKey;
  label: string;
  tooltipLabel: string;
  tooltip: string;
  hint: string;
  min: number;
  max: number;
}

const FIELDS: readonly FieldSpec[] = [
  {
    key: "starting_rating",
    label: "Starting rating",
    tooltipLabel: "About the starting rating",
    tooltip:
      "Every franchise starts at this rating, including a team that first appears mid-history. Before each new season, returning teams move back toward it by the season regression.",
    hint: "Allowed 1000 to 2000. The default is 1500.",
    min: 1000,
    max: 2000,
  },
  {
    key: "k_factor",
    label: "K factor",
    tooltipLabel: "About the K factor",
    tooltip:
      "The base number of rating points exchanged for an equal-rating result. A larger K reacts faster to results and is more volatile; a smaller K is steadier.",
    hint: "Allowed 1 to 100. The default is 24.",
    min: 1,
    max: 100,
  },
  {
    key: "margin_weight",
    label: "Margin weight",
    tooltipLabel: "About the margin weight",
    tooltip:
      "The extra share of K a decisive margin can add, from 0 (ignore the margin) to 1 (+100% at the cap). The default 0.25 gives at most a 25% bonus.",
    hint: "Allowed 0 to 1. The default is 0.25.",
    min: 0,
    max: 1,
  },
  {
    key: "margin_cap",
    label: "Margin cap",
    tooltipLabel: "About the margin cap",
    tooltip:
      "The point margin at which the maximum margin bonus applies. A larger cap makes a given blowout worth less extra; margins above the cap add nothing more.",
    hint: "Allowed 1 to 200 points. The default is 50.",
    min: 1,
    max: 200,
  },
  {
    key: "season_regression",
    label: "Season regression",
    tooltipLabel: "About the season regression",
    tooltip:
      "The fraction of the gap to the starting rating removed before every new season. The default one third keeps a strong team favored next season without erasing the multi-season story.",
    hint: "Allowed 0 to 1. The default is one third.",
    min: 0,
    max: 1,
  },
];

function formFromConfig(config: EloConfigResponse): FormValues {
  return {
    starting_rating: config.starting_rating,
    k_factor: config.k_factor,
    margin_weight: config.margin_weight,
    margin_cap: config.margin_cap,
    season_regression: config.season_regression,
  };
}

function validate(values: FormValues): FormErrors {
  const errors: FormErrors = {};
  for (const field of FIELDS) {
    const raw = values[field.key].trim();
    if (raw === "") {
      errors[field.key] = "Enter a value.";
      continue;
    }
    const parsed = Number(raw);
    if (!Number.isFinite(parsed)) {
      errors[field.key] = "Enter a number.";
    } else if (parsed < field.min || parsed > field.max) {
      errors[field.key] = `Enter a number from ${field.min} to ${field.max}.`;
    }
  }
  return errors;
}

/**
 * Admin: per-league Elo settings (AC-Elo-*).
 *
 * Each field carries an accessible explanation that appears on hover and keyboard focus. Saving
 * validates locally, PUTs the values, and bumps the shared data version so every History view
 * refetches and recalculates from stored results. The section owns its own loading, saving,
 * success, and error states and does not alter the other admin sections.
 */
export function EloSettingsSection({ leagueId }: { leagueId: number }) {
  const { notifyDataChanged } = useLeague();
  const [state, setState] = useState<ConfigState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [values, setValues] = useState<FormValues | null>(null);
  const [errors, setErrors] = useState<FormErrors>({});
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);
  const [failure, setFailure] = useState<DisplayError | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    api.eloConfig(leagueId, controller.signal).then(
      (config) => {
        if (controller.signal.aborted) {
          return;
        }
        setState({ status: "ready", config });
        setValues(formFromConfig(config));
      },
      (error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setState({
          status: "error",
          message: error instanceof Error ? error.message : "Could not load Elo settings.",
        });
      },
    );
    return () => {
      controller.abort();
    };
  }, [leagueId, attempt]);

  const updateValue = (key: FieldKey, value: string) => {
    setValues((current) => (current === null ? current : { ...current, [key]: value }));
    setErrors((current) => ({ ...current, [key]: undefined }));
    setSuccess(null);
    setFailure(null);
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (values === null) {
      return;
    }
    const nextErrors = validate(values);
    if (Object.keys(nextErrors).length > 0) {
      setErrors(nextErrors);
      setSuccess(null);
      return;
    }
    setSaving(true);
    setFailure(null);
    setSuccess(null);
    try {
      const saved = await api.updateEloConfig(leagueId, {
        starting_rating: values.starting_rating,
        k_factor: values.k_factor,
        margin_weight: values.margin_weight,
        margin_cap: values.margin_cap,
        season_regression: values.season_regression,
      });
      setState({ status: "ready", config: saved });
      setValues(formFromConfig(saved));
      setSuccess("Elo settings saved. History now recalculates from stored results.");
      notifyDataChanged();
    } catch (error) {
      setFailure(toDisplayError(error));
    } finally {
      setSaving(false);
    }
  };

  const reset = () => {
    if (state.status !== "ready") {
      return;
    }
    setValues(formFromConfig(state.config));
    setErrors({});
    setSuccess(null);
    setFailure(null);
  };

  return (
    <section aria-labelledby="h-elo-settings" className="mt-7">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id="h-elo-settings" className="text-base font-bold">
            Elo settings
          </h2>
          <p className="mt-1 text-[13px] text-ink-faint">
            Per league · saved changes recompute the History page from stored results.
          </p>
        </div>
      </div>

      {state.status === "loading" ? <LoadingState label="Loading Elo settings…" /> : null}

      {state.status === "error" ? (
        <ErrorState onRetry={() => setAttempt((current) => current + 1)} message={state.message} />
      ) : null}

      {state.status === "ready" && values !== null ? (
        <form
          onSubmit={(event) => {
            void submit(event);
          }}
          noValidate
          className="mt-3 rounded-xl border border-line bg-surface p-4"
        >
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {FIELDS.map((field) => {
              const error = errors[field.key];
              return (
                <div key={field.key} className="relative min-w-0">
                  <div className="flex items-center">
                    <label htmlFor={`elo-${field.key}`} className={labelClass}>
                      {field.label}
                    </label>
                    <InfoTooltip
                      id={`elo-tip-${field.key}`}
                      label={field.tooltipLabel}
                      text={field.tooltip}
                    />
                  </div>
                  <input
                    id={`elo-${field.key}`}
                    name={field.key}
                    type="text"
                    inputMode="decimal"
                    value={values[field.key]}
                    onChange={(event) => updateValue(field.key, event.target.value)}
                    aria-describedby={`elo-hint-${field.key}`}
                    aria-invalid={error !== undefined}
                    disabled={saving}
                    className={inputClass}
                  />
                  <p id={`elo-hint-${field.key}`} className="mt-1 text-xs text-ink-faint">
                    {field.hint}
                  </p>
                  {error === undefined ? null : (
                    <p role="alert" className="mt-1 text-[12.5px] text-danger-ink">
                      {field.label}: {error}
                    </p>
                  )}
                </div>
              );
            })}
          </div>

          <p className="mt-3 text-[12.5px] text-ink-faint">
            Saving these values does not store a snapshot: every History view is recomputed from
            stored matchups and scores, so adding or deleting a season also changes it.
          </p>

          {failure === null ? null : (
            <div className="mt-3">
              <ApiAlert error={failure} />
            </div>
          )}
          {success === null ? null : (
            <p role="status" className="mt-3 text-[13px] font-semibold text-ink-strong">
              {success}
            </p>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button type="submit" disabled={saving} className={primaryButtonClass}>
              {saving ? "Saving…" : "Recalculate Elo history"}
            </button>
            <button
              type="button"
              onClick={reset}
              disabled={saving}
              className={secondaryButtonClass}
            >
              Discard changes
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
