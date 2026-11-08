import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api } from "../api/endpoints";
import { toDisplayError, type DisplayError } from "../api/errors";
import type { OwnerTeamAliasSummary, TradeConfigResponse } from "../api/types";
import { ApiAlert } from "../components/ApiAlert";
import { ErrorState, LoadingState } from "../components/DataStates";
import {
  dangerSecondaryButtonClass,
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "../components/formStyles";
import { useLeague } from "./LeagueContext";

const TRADE_REPO_SETUP_DOCS_URL =
  "https://github.com/bberk/whodat-server/blob/main/docs/trade-repo-template/README.md";

/**
 * Admin: Trade Tracker & Projected Auction Budget configuration (AC-TRADE-CONFIG).
 *
 * Allows administrators to:
 * - Toggle the Trade Tracker on/off using an accessible sliding square switch.
 * - Set the starting base auction budget (e.g. $200.00).
 * - Configure the GitHub trade repository (owner, name, branch, personal access token).
 * - Configure the Discord trade announcements channel ID and encrypted bot token.
 * - Manage ESPN team & owner alias mappings with current season team names.
 * - Manually trigger GitHub trade sync or Discord trade ingestion.
 * - Inspect the latest sync statuses, timestamps, commit SHAs, and errors.
 */
export function TradeTrackerSection({ leagueId }: { leagueId: number }) {
  const { leagues, selectedLeague, upsertLeague } = useLeague();
  const league =
    leagues.find((item) => item.league_id === leagueId) ??
    (selectedLeague?.league_id === leagueId ? selectedLeague : null);

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Form state
  const [enabled, setEnabled] = useState(false);
  const [baseBudget, setBaseBudget] = useState("200.00");
  const [repoOwner, setRepoOwner] = useState("");
  const [repoName, setRepoName] = useState("");
  const [branch, setBranch] = useState("main");
  const [githubToken, setGithubToken] = useState("");
  const [clearGithubToken, setClearGithubToken] = useState(false);
  const [hasGithubToken, setHasGithubToken] = useState(false);
  const [discordToken, setDiscordToken] = useState("");
  const [clearDiscordToken, setClearDiscordToken] = useState(false);
  const [hasDiscordToken, setHasDiscordToken] = useState(false);
  const [discordChannelId, setDiscordChannelId] = useState("");
  const [owners, setOwners] = useState<OwnerTeamAliasSummary[]>([]);
  const [ownerAliasesInput, setOwnerAliasesInput] = useState<Record<number, string>>({});

  // Sync state tracking from server
  const [syncStatus, setSyncStatus] = useState<TradeConfigResponse | null>(null);

  // Actions state
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);
  const [saveFailure, setSaveFailure] = useState<DisplayError | null>(null);

  const [syncingRepo, setSyncingRepo] = useState(false);
  const [repoSyncResult, setRepoSyncResult] = useState<string | null>(null);
  const [repoSyncFailure, setRepoSyncFailure] = useState<DisplayError | null>(null);

  const [syncingDiscord, setSyncingDiscord] = useState(false);
  const [discordSyncResult, setDiscordSyncResult] = useState<string | null>(null);
  const [discordSyncFailure, setDiscordSyncFailure] = useState<DisplayError | null>(null);

  const loadConfig = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setLoadError(null);
      try {
        const data = await api.tradeConfig(leagueId, signal);
        setSyncStatus(data);
        setEnabled(data.enabled);
        setBaseBudget(data.base_auction_budget);
        setRepoOwner(data.repo_owner);
        setRepoName(data.repo_name);
        setBranch(data.branch);
        setHasGithubToken(data.has_github_token);
        setClearGithubToken(false);
        setGithubToken("");
        setHasDiscordToken(data.has_discord_token);
        setClearDiscordToken(false);
        setDiscordToken("");
        setDiscordChannelId(data.discord_channel_id ?? "");

        const ownersList = data.owners ?? [];
        setOwners(ownersList);
        const initialInputs: Record<number, string> = {};
        ownersList.forEach((o) => {
          initialInputs[o.owner_id] = (o.aliases ?? []).join(", ");
        });
        setOwnerAliasesInput(initialInputs);
        setLoading(false);
      } catch (err) {
        if (signal?.aborted) return;
        setLoadError(toDisplayError(err).message);
        setLoading(false);
      }
    },
    [leagueId],
  );

  useEffect(() => {
    setLoading(true);
    setLoadError(null);
    setSaveSuccess(null);
    setSaveFailure(null);
    setRepoSyncResult(null);
    setRepoSyncFailure(null);
    setDiscordSyncResult(null);
    setDiscordSyncFailure(null);

    const controller = new AbortController();
    void loadConfig(controller.signal);
    return () => controller.abort();
  }, [loadConfig]);

  const handleToggleEnabled = async (nextEnabled: boolean) => {
    setEnabled(nextEnabled);
    setSaveSuccess(null);
    setSaveFailure(null);

    // If disabling a currently active configuration on the server, persist immediately
    if (!nextEnabled && syncStatus?.enabled) {
      setSaving(true);
      try {
        const updated = await api.updateTradeConfig(leagueId, {
          enabled: false,
          clear_github_token: false,
          clear_discord_token: false,
        });
        setSyncStatus(updated);
        setEnabled(false);
        if (league) {
          upsertLeague({
            ...league,
            has_trades_enabled: false,
          });
        }
        setSaveSuccess("Trade tracker disabled.");
      } catch (err) {
        setSaveFailure(toDisplayError(err));
        setEnabled(true);
      } finally {
        setSaving(false);
      }
    }
  };

  const handleOwnerAliasesChange = (ownerId: number, value: string) => {
    setOwnerAliasesInput((prev) => ({
      ...prev,
      [ownerId]: value,
    }));
  };

  const handleSave = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setSaveFailure(null);
    setSaveSuccess(null);

    const team_aliases: Record<string, string> = {};
    owners.forEach((o) => {
      const rawInput = ownerAliasesInput[o.owner_id] ?? "";
      const parts = rawInput
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      parts.forEach((alias) => {
        team_aliases[alias] = o.display_name;
      });
    });

    try {
      const updated = await api.updateTradeConfig(leagueId, {
        enabled,
        base_auction_budget: baseBudget,
        repo_owner: repoOwner.trim(),
        repo_name: repoName.trim(),
        branch: branch.trim() || "main",
        github_token: githubToken.trim() ? githubToken.trim() : null,
        clear_github_token: clearGithubToken,
        discord_token: discordToken.trim() ? discordToken.trim() : null,
        clear_discord_token: clearDiscordToken,
        discord_channel_id: discordChannelId.trim() ? discordChannelId.trim() : null,
        team_aliases,
      });

      setSyncStatus(updated);
      setHasGithubToken(updated.has_github_token);
      setClearGithubToken(false);
      setGithubToken("");
      setHasDiscordToken(updated.has_discord_token);
      setClearDiscordToken(false);
      setDiscordToken("");
      const updatedOwners = updated.owners ?? [];
      setOwners(updatedOwners);
      const updatedInputs: Record<number, string> = {};
      updatedOwners.forEach((o) => {
        updatedInputs[o.owner_id] = (o.aliases ?? []).join(", ");
      });
      setOwnerAliasesInput(updatedInputs);
      setSaveSuccess("Trade tracker configuration saved.");

      // Sync league context navigation tab visibility
      if (league) {
        upsertLeague({
          ...league,
          has_trades_enabled: updated.enabled,
        });
      }
    } catch (err) {
      setSaveFailure(toDisplayError(err));
    } finally {
      setSaving(false);
    }
  };

  const handleSyncRepo = async () => {
    setSyncingRepo(true);
    setRepoSyncResult(null);
    setRepoSyncFailure(null);

    try {
      const res = await api.syncTradeRepo(leagueId);
      const commitInfo = res.commit_sha ? ` (commit ${res.commit_sha.slice(0, 7)})` : "";
      setRepoSyncResult(`Successfully synced ${res.trades_synced} trade(s)${commitInfo}.`);
      void loadConfig();
    } catch (err) {
      setRepoSyncFailure(toDisplayError(err));
    } finally {
      setSyncingRepo(false);
    }
  };

  const handleSyncDiscord = async () => {
    setSyncingDiscord(true);
    setDiscordSyncResult(null);
    setDiscordSyncFailure(null);

    try {
      const res = await api.syncDiscordTrades(leagueId);
      setDiscordSyncResult(res.message);
      void loadConfig();
    } catch (err) {
      setDiscordSyncFailure(toDisplayError(err));
    } finally {
      setSyncingDiscord(false);
    }
  };

  if (loading) {
    return (
      <section className="mt-8 border-t border-line-subtle pt-6">
        <h2 className="text-base font-bold">Trade tracker & auction budget</h2>
        <div className="mt-4">
          <LoadingState label="Loading trade tracker configuration..." />
        </div>
      </section>
    );
  }

  if (loadError) {
    return (
      <section className="mt-8 border-t border-line-subtle pt-6">
        <h2 className="text-base font-bold">Trade tracker & auction budget</h2>
        <div className="mt-4">
          <ErrorState message={loadError} onRetry={() => void loadConfig()} />
        </div>
      </section>
    );
  }

  return (
    <section className="mt-8 border-t border-line-subtle pt-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-bold">Trade tracker & auction budget</h2>
          <p className="mt-1 text-[13px] text-ink-faint">
            Ingest announced trades from Discord, track multi-draft auction dollars, and project
            future auction budgets.{" "}
            <a
              href={TRADE_REPO_SETUP_DOCS_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-brand hover:underline"
            >
              Setup instructions & docs &rarr;
            </a>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {enabled && (
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={syncingRepo}
                onClick={() => void handleSyncRepo()}
                className={secondaryButtonClass}
              >
                {syncingRepo ? "Syncing repo..." : "Sync Trade Repo"}
              </button>
              <button
                type="button"
                disabled={syncingDiscord}
                onClick={() => void handleSyncDiscord()}
                className={secondaryButtonClass}
              >
                {syncingDiscord ? "Starting sync..." : "Sync Discord Trades"}
              </button>
            </div>
          )}
          <div className="flex items-center gap-2">
            <span
              id="trade-tracker-toggle-label"
              className="text-xs font-semibold uppercase tracking-wider text-ink-muted"
            >
              {enabled ? "Enabled" : "Disabled"}
            </span>
            <button
              type="button"
              role="switch"
              aria-checked={enabled}
              aria-label="Toggle trade tracker"
              disabled={saving}
              onClick={() => void handleToggleEnabled(!enabled)}
              className={[
                "relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center",
                "rounded-none border border-line-strong transition-colors duration-200 ease-in-out",
                "focus:outline-none focus:ring-2 focus:ring-brand focus:ring-offset-2",
                enabled ? "bg-brand" : "bg-surface-muted",
              ].join(" ")}
            >
              <span
                aria-hidden="true"
                className={[
                  "pointer-events-none inline-block h-4 w-4 transform rounded-none bg-surface",
                  "shadow transition duration-200 ease-in-out",
                  enabled ? "translate-x-6 bg-white" : "translate-x-1 bg-ink-muted",
                ].join(" ")}
              />
            </button>
          </div>
        </div>
      </div>

      {/* Sync Alert Banners */}
      <div className="mt-3 space-y-2">
        {saveSuccess && (
          <div className="rounded-lg border border-brand-line bg-brand-soft px-3 py-2 text-[13px]">
            <span className="text-brand-ink">{saveSuccess}</span>
          </div>
        )}
        <ApiAlert error={saveFailure} />
        {repoSyncResult && (
          <div className="rounded-lg border border-brand-line bg-brand-soft px-3 py-2 text-[13px]">
            <span className="text-brand-ink">{repoSyncResult}</span>
          </div>
        )}
        <ApiAlert error={repoSyncFailure} />
        {discordSyncResult && (
          <div className="rounded-lg border border-brand-line bg-brand-soft px-3 py-2 text-[13px]">
            <span className="text-brand-ink">{discordSyncResult}</span>
          </div>
        )}
        <ApiAlert error={discordSyncFailure} />
      </div>

      {!enabled ? (
        <div className="mt-4 rounded-lg border border-line bg-surface p-4 text-center text-sm">
          <p className="text-ink-muted">
            Trade tracker is currently disabled for this league. Turn on the switch above to
            configure trade tracking and projected auction budgets.
          </p>
          <p className="mt-2 text-xs text-ink-faint">
            Need setup instructions? See the{" "}
            <a
              href={TRADE_REPO_SETUP_DOCS_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-brand hover:underline"
            >
              Trade Repository Setup Guide
            </a>{" "}
            on GitHub.
          </p>
        </div>
      ) : (
        <>
          {/* Sync Status Cards */}
          {syncStatus && (
            <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-line bg-surface p-3 text-[13px]">
                <div className="flex items-center justify-between font-semibold">
                  <span>GitHub Repo Sync</span>
                  <span
                    className={`rounded px-1.5 py-0.5 text-xs font-bold uppercase ${
                      syncStatus.last_sync_status === "success"
                        ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950"
                        : syncStatus.last_sync_status === "error"
                          ? "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300"
                          : "bg-surface-muted text-ink-muted"
                    }`}
                  >
                    {syncStatus.last_sync_status}
                  </span>
                </div>
                <p className="mt-1 text-ink-muted">
                  Last synced: {syncStatus.last_synced_at ?? "Never"}
                </p>
                {syncStatus.last_sync_commit && (
                  <p className="text-ink-faint">
                    Commit: {syncStatus.last_sync_commit.slice(0, 7)}
                  </p>
                )}
                {syncStatus.last_sync_error && (
                  <p className="mt-1 text-danger-ink">Error: {syncStatus.last_sync_error}</p>
                )}
              </div>

              <div className="rounded-lg border border-line bg-surface p-3 text-[13px]">
                <div className="flex items-center justify-between font-semibold">
                  <span>Discord Ingestion Worker</span>
                  <span
                    className={`rounded px-1.5 py-0.5 text-xs font-bold uppercase ${
                      syncStatus.discord_sync_status === "running"
                        ? "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"
                        : syncStatus.discord_sync_status === "success"
                          ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950"
                          : syncStatus.discord_sync_status === "error"
                            ? "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300"
                            : "bg-surface-muted text-ink-muted"
                    }`}
                  >
                    {syncStatus.discord_sync_status}
                  </span>
                </div>
                <p className="mt-1 text-ink-muted">
                  Last run: {syncStatus.last_discord_sync_at ?? "Never"}
                </p>
                {syncStatus.last_discord_sync_error && (
                  <p className="mt-1 text-danger-ink">
                    Error: {syncStatus.last_discord_sync_error}
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Main Settings Form */}
          <form onSubmit={(e) => void handleSave(e)} className="mt-6 space-y-4">
            <div
              className={[
                "rounded-lg border border-line bg-surface-muted/50 p-3 text-xs text-ink-muted",
              ].join(" ")}
            >
              Need help configuring the trade repository, GitHub PAT, or Discord bot? See the{" "}
              <a
                href={TRADE_REPO_SETUP_DOCS_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-brand hover:underline"
              >
                Trade Repository Setup Guide
              </a>{" "}
              on GitHub for step-by-step instructions.
            </div>
            {/* Starting Auction Budget */}
            <div>
              <label htmlFor="base_budget" className={labelClass}>
                Base starting auction budget ($)
              </label>
              <input
                id="base_budget"
                type="text"
                value={baseBudget}
                onChange={(e) => setBaseBudget(e.target.value)}
                placeholder="200.00"
                className={inputClass}
              />
              <p className="mt-1 text-xs text-ink-faint">
                The standard starting budget every team begins with prior to trade deltas.
              </p>
            </div>

            {/* GitHub Repository Settings */}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div>
                <label htmlFor="repo_owner" className={labelClass}>
                  GitHub Repo Owner
                </label>
                <input
                  id="repo_owner"
                  type="text"
                  value={repoOwner}
                  onChange={(e) => setRepoOwner(e.target.value)}
                  placeholder="e.g. your-org"
                  className={inputClass}
                />
              </div>
              <div>
                <label htmlFor="repo_name" className={labelClass}>
                  GitHub Repo Name
                </label>
                <input
                  id="repo_name"
                  type="text"
                  value={repoName}
                  onChange={(e) => setRepoName(e.target.value)}
                  placeholder="e.g. your-trades"
                  className={inputClass}
                />
              </div>
              <div>
                <label htmlFor="repo_branch" className={labelClass}>
                  Branch
                </label>
                <input
                  id="repo_branch"
                  type="text"
                  value={branch}
                  onChange={(e) => setBranch(e.target.value)}
                  placeholder="main"
                  className={inputClass}
                />
              </div>
            </div>

            {/* GitHub Token */}
            <div>
              <label htmlFor="github_token" className={labelClass}>
                GitHub Personal Access Token (PAT)
              </label>
              <div className="mt-1 flex items-center gap-2">
                <input
                  id="github_token"
                  type="password"
                  value={githubToken}
                  disabled={clearGithubToken}
                  onChange={(e) => setGithubToken(e.target.value)}
                  placeholder={
                    hasGithubToken && !clearGithubToken
                      ? "•••••••••••• (configured on server)"
                      : "ghp_..."
                  }
                  className={inputClass}
                />
                {hasGithubToken && (
                  <button
                    type="button"
                    onClick={() => {
                      setClearGithubToken(!clearGithubToken);
                      setGithubToken("");
                    }}
                    className={clearGithubToken ? secondaryButtonClass : dangerSecondaryButtonClass}
                  >
                    {clearGithubToken ? "Keep Token" : "Clear Token"}
                  </button>
                )}
              </div>
              <p className="mt-1 text-xs text-ink-faint">
                Required if the trade repository is private. Needs read access to contents.
              </p>
            </div>

            {/* Discord Channel ID */}
            <div>
              <label htmlFor="discord_channel_id" className={labelClass}>
                Discord #trades Channel ID
              </label>
              <input
                id="discord_channel_id"
                type="text"
                value={discordChannelId}
                onChange={(e) => setDiscordChannelId(e.target.value)}
                placeholder="e.g. 123456789012345678"
                className={inputClass}
              />
              <p className="mt-1 text-xs text-ink-faint">
                Channel ID where trade announcements are posted and extracted by the worker.
              </p>
            </div>

            {/* Discord Bot Token */}
            <div>
              <label htmlFor="discord_token" className={labelClass}>
                Discord Bot Token
              </label>
              <div className="mt-1 flex items-center gap-2">
                <input
                  id="discord_token"
                  type="password"
                  value={discordToken}
                  disabled={clearDiscordToken}
                  onChange={(e) => setDiscordToken(e.target.value)}
                  placeholder={
                    hasDiscordToken && !clearDiscordToken
                      ? "•••••••••••• (configured on server)"
                      : "Bot token..."
                  }
                  className={inputClass}
                />
                {hasDiscordToken && (
                  <button
                    type="button"
                    onClick={() => {
                      setClearDiscordToken(!clearDiscordToken);
                      setDiscordToken("");
                    }}
                    className={
                      clearDiscordToken ? secondaryButtonClass : dangerSecondaryButtonClass
                    }
                  >
                    {clearDiscordToken ? "Keep Token" : "Clear Token"}
                  </button>
                )}
              </div>
              <p className="mt-1 text-xs text-ink-faint">
                Required to access announcements in private Discord servers or channels.
              </p>
            </div>

            {/* Team & Owner Alias Mappings */}
            <div className="border-t border-line-subtle pt-4">
              <label className={labelClass}>Team & Owner Alias Mappings</label>
              <p className="mt-1 text-xs text-ink-faint">
                List of ESPN owners and their current team names. Enter a comma-separated list of
                aliases for each owner (real names, Discord usernames, or nicknames) to map trade
                messages and ledger records to the actual ESPN team.
              </p>

              {owners.length === 0 ? (
                <p className="mt-3 text-xs italic text-ink-faint">
                  No ESPN owners found for this league. Run a league sync to load teams and owners.
                </p>
              ) : (
                <div className="mt-3 overflow-hidden rounded-lg border border-line bg-surface">
                  <div
                    className={[
                      "hidden grid-cols-12 gap-3 border-b border-line bg-surface-muted",
                      "px-3 py-2 text-[11px] font-semibold uppercase tracking-wider",
                      "text-ink-faint sm:grid",
                    ].join(" ")}
                  >
                    <span className="col-span-3">ESPN Owner</span>
                    <span className="col-span-3">Current Team (Latest Season)</span>
                    <span className="col-span-6">Aliases (comma-separated)</span>
                  </div>

                  <div className="divide-y divide-line-subtle">
                    {owners.map((owner) => (
                      <div
                        key={owner.owner_id}
                        className={[
                          "grid grid-cols-1 gap-2 p-3",
                          "sm:grid-cols-12 sm:items-center sm:gap-3",
                        ].join(" ")}
                      >
                        <div className="sm:col-span-3">
                          <span
                            className={[
                              "text-xs font-semibold uppercase tracking-wider",
                              "text-ink-faint sm:hidden",
                            ].join(" ")}
                          >
                            Owner:{" "}
                          </span>
                          <span className="text-sm font-semibold text-ink">
                            {owner.display_name}
                          </span>
                        </div>

                        <div className="sm:col-span-3">
                          <span
                            className={[
                              "text-xs font-semibold uppercase tracking-wider",
                              "text-ink-faint sm:hidden",
                            ].join(" ")}
                          >
                            Current Team:{" "}
                          </span>
                          <span className="text-sm text-ink-muted">
                            {owner.current_team_name ?? (
                              <span className="italic text-ink-faint">None</span>
                            )}
                          </span>
                        </div>

                        <div className="sm:col-span-6">
                          <label htmlFor={`owner-aliases-${owner.owner_id}`} className="sr-only">
                            Aliases for {owner.display_name}
                          </label>
                          <input
                            id={`owner-aliases-${owner.owner_id}`}
                            type="text"
                            value={ownerAliasesInput[owner.owner_id] ?? ""}
                            onChange={(e) =>
                              handleOwnerAliasesChange(owner.owner_id, e.target.value)
                            }
                            placeholder="e.g. Brad, @brad_discord, Champ"
                            className={[
                              "w-full rounded-lg border border-line-strong bg-surface",
                              "px-3 py-1.5 text-xs text-ink placeholder:text-ink-faint",
                              "focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand",
                            ].join(" ")}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Save Button */}
            <div className="pt-2">
              <button type="submit" disabled={saving} className={primaryButtonClass}>
                {saving ? "Saving settings..." : "Save Trade Settings"}
              </button>
            </div>
          </form>
        </>
      )}
    </section>
  );
}
