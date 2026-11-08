import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api } from "../api/endpoints";
import { toDisplayError, type DisplayError } from "../api/errors";
import type { TradeConfigResponse } from "../api/types";
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

interface AliasEntry {
  alias: string;
  team: string;
}

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
 * - Manage team & owner alias mappings.
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
  const [aliases, setAliases] = useState<AliasEntry[]>([]);
  const [newAliasKey, setNewAliasKey] = useState("");
  const [newAliasVal, setNewAliasVal] = useState("");

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

        const aliasEntries: AliasEntry[] = Object.entries(data.team_aliases ?? {}).map(
          ([k, v]) => ({
            alias: k,
            team: String(v),
          }),
        );
        setAliases(aliasEntries);
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

  const handleAddAlias = () => {
    const trimmedKey = newAliasKey.trim();
    const trimmedVal = newAliasVal.trim();
    if (!trimmedKey || !trimmedVal) return;

    // Filter out duplicate keys
    const filtered = aliases.filter((a) => a.alias !== trimmedKey);
    setAliases([...filtered, { alias: trimmedKey, team: trimmedVal }]);
    setNewAliasKey("");
    setNewAliasVal("");
  };

  const handleRemoveAlias = (aliasToRemove: string) => {
    setAliases(aliases.filter((a) => a.alias !== aliasToRemove));
  };

  const handleSave = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setSaveFailure(null);
    setSaveSuccess(null);

    const team_aliases: Record<string, string> = {};
    for (const a of aliases) {
      if (a.alias.trim() && a.team.trim()) {
        team_aliases[a.alias.trim()] = a.team.trim();
      }
    }

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
                Map Discord usernames or informal trade nicknames to official ESPN team names or
                IDs.
              </p>

              <div className="mt-3 space-y-2">
                {aliases.map((a) => (
                  <div key={a.alias} className="flex items-center gap-2 text-sm">
                    <span className="w-1/3 truncate font-mono text-ink-muted">{a.alias}</span>
                    <span className="text-ink-faint">&rarr;</span>
                    <span className="flex-1 truncate font-medium text-ink">{a.team}</span>
                    <button
                      type="button"
                      onClick={() => handleRemoveAlias(a.alias)}
                      className={dangerSecondaryButtonClass}
                    >
                      Delete
                    </button>
                  </div>
                ))}

                {aliases.length === 0 && (
                  <p className="text-xs italic text-ink-faint">No aliases configured yet.</p>
                )}

                {/* Add Alias Row */}
                <div className="mt-2 flex flex-wrap items-center gap-2 pt-2">
                  <input
                    type="text"
                    value={newAliasKey}
                    onChange={(e) => setNewAliasKey(e.target.value)}
                    placeholder="Alias (e.g. alice_discord)"
                    className={[
                      "w-full rounded-lg border border-line-strong bg-surface",
                      "px-3 py-1.5 text-xs text-ink sm:w-1/3",
                    ].join(" ")}
                  />
                  <input
                    type="text"
                    value={newAliasVal}
                    onChange={(e) => setNewAliasVal(e.target.value)}
                    placeholder="Canonical Team Name / ID"
                    className={[
                      "w-full flex-1 rounded-lg border border-line-strong bg-surface",
                      "px-3 py-1.5 text-xs text-ink",
                    ].join(" ")}
                  />
                  <button
                    type="button"
                    onClick={handleAddAlias}
                    disabled={!newAliasKey.trim() || !newAliasVal.trim()}
                    className={secondaryButtonClass}
                  >
                    Add Alias
                  </button>
                </div>
              </div>
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
