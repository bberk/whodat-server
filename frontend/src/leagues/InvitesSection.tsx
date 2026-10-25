import { useState, type FormEvent } from "react";

import { api } from "../api/endpoints";
import { toDisplayError, type DisplayError } from "../api/errors";
import type { CreateInviteResponse } from "../api/types";
import { ApiAlert } from "../components/ApiAlert";
import {
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
  selectClass,
} from "../components/formStyles";

const MIN_EXPIRY_DAYS = 1;
const MAX_EXPIRY_DAYS = 3650;
const DEFAULT_EXPIRY_DAYS = 7;

type InviteRole = "member" | "admin";

/**
 * Admin: generate a member invite for this league or a league-less admin invite (AC-AU-21).
 *
 * The server stores only the code's hash, so the raw code is shown once, in this section, and is
 * never fetched again. The copy control copies the exact code; the note tells the admin to store
 * it now. Expiry defaults to seven days and is bounded on both the client and the server.
 */
export function InvitesSection({ leagueId }: { leagueId: number }) {
  const [role, setRole] = useState<InviteRole>("member");
  const [expiryDays, setExpiryDays] = useState(String(DEFAULT_EXPIRY_DAYS));
  const [generating, setGenerating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<DisplayError | null>(null);
  const [invite, setInvite] = useState<CreateInviteResponse | null>(null);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError(null);
    setApiError(null);
    setCopyStatus(null);

    const trimmed = expiryDays.trim();
    const parsed = Number(trimmed);
    if (trimmed === "" || !Number.isInteger(parsed)) {
      setFormError(
        `Enter a whole number of days between ${MIN_EXPIRY_DAYS} and ${MAX_EXPIRY_DAYS}.`,
      );
      return;
    }
    if (parsed < MIN_EXPIRY_DAYS || parsed > MAX_EXPIRY_DAYS) {
      setFormError(`Expiry must be between ${MIN_EXPIRY_DAYS} and ${MAX_EXPIRY_DAYS} days.`);
      return;
    }

    setGenerating(true);
    setInvite(null);
    try {
      const created = await api.createInvite(leagueId, {
        role,
        expires_in_days: parsed,
      });
      setInvite(created);
    } catch (failure) {
      setApiError(toDisplayError(failure));
    } finally {
      setGenerating(false);
    }
  };

  const copyCode = async () => {
    if (invite === null) {
      return;
    }
    try {
      if (navigator.clipboard === undefined) {
        throw new Error("clipboard unavailable");
      }
      await navigator.clipboard.writeText(invite.code);
      setCopyStatus("Copied to the clipboard.");
    } catch {
      setCopyStatus("Copy failed. Select the code and copy it manually.");
    }
  };

  return (
    <section aria-labelledby="h-invites" className="mt-7 max-w-lg">
      <h2 id="h-invites" className="text-base font-bold">
        Invites
      </h2>
      <p className="mt-1 text-[13px] text-ink-faint">
        A member invite joins this league at signup. An admin invite has no league and lets the new
        account create or add one. Invite codes work for anyone who uses them until they expire.
      </p>

      <form
        onSubmit={onSubmit}
        noValidate
        className="mt-3 rounded-xl border border-line bg-surface p-4"
      >
        <label htmlFor="invite-role" className={labelClass}>
          Invite type
        </label>
        <select
          id="invite-role"
          className={`${selectClass} mt-1 w-full`}
          value={role}
          onChange={(event) => setRole(event.target.value === "admin" ? "admin" : "member")}
          disabled={generating}
        >
          <option value="member">Member invite (joins this league)</option>
          <option value="admin">Admin invite (no league)</option>
        </select>

        <label htmlFor="invite-expiry" className={`${labelClass} mt-3`}>
          Expires after (days)
        </label>
        <input
          id="invite-expiry"
          name="expires_in_days"
          type="number"
          inputMode="numeric"
          min={MIN_EXPIRY_DAYS}
          max={MAX_EXPIRY_DAYS}
          step={1}
          required
          value={expiryDays}
          onChange={(event) => setExpiryDays(event.target.value)}
          className={inputClass}
          disabled={generating}
          aria-describedby="invite-expiry-note"
        />
        <p id="invite-expiry-note" className="mt-1 text-xs text-ink-faint">
          Default 7 days, between {MIN_EXPIRY_DAYS} and {MAX_EXPIRY_DAYS}.
        </p>

        {formError === null ? null : (
          <p role="alert" className="mt-3 text-[13px] text-danger-ink">
            {formError}
          </p>
        )}
        <ApiAlert error={apiError} />

        {generating ? (
          <p role="status" className="mt-3 text-[13px] text-ink-muted">
            Generating invite…
          </p>
        ) : null}

        <div className="mt-4 flex justify-end">
          <button type="submit" disabled={generating} className={primaryButtonClass}>
            {generating ? "Generating…" : "Generate invite"}
          </button>
        </div>
      </form>

      {invite === null ? null : (
        <div className="mt-3 rounded-xl border border-warning-line bg-warning-surface p-4">
          <h3 className="text-sm font-bold text-ink">
            {invite.role === "admin" ? "Admin invite code" : "Member invite code"}
          </h3>
          <p className="mt-1 text-[13px] text-ink-muted">
            This code is shown only once. Store it now: it cannot be retrieved again, and
            regenerating means creating a new invite.
          </p>
          <label htmlFor="invite-code" className={`${labelClass} mt-3`}>
            Invite code
          </label>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <input
              id="invite-code"
              readOnly
              value={invite.code}
              onFocus={(event) => event.currentTarget.select()}
              className={`${inputClass} mt-0 min-w-0 flex-1 font-mono`}
            />
            <button
              type="button"
              onClick={() => {
                void copyCode();
              }}
              className={secondaryButtonClass}
            >
              Copy code
            </button>
          </div>
          <p className="mt-2 text-[12.5px] text-ink-subtle">
            {invite.league_id === null
              ? "League-less admin invite"
              : "Member invite for this league"}
            {" · "}
            Expires {new Date(invite.expires_at).toLocaleString()}
          </p>
          {copyStatus === null ? null : (
            <p role="status" className="mt-2 text-[13px] font-semibold text-ink-strong">
              {copyStatus}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
