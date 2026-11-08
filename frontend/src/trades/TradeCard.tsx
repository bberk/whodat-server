import type { TradeItem, TradePartyItem } from "../api/types";
import { dollarBadgeClass, dollarTone, formatAuctionDollars, formatTradeDate } from "./format";

export interface TradeCardProps {
  trade: TradeItem;
}

function formatPlayer(player: Record<string, unknown>): string {
  const name = String(player.name ?? player.player_name ?? "Unknown Player");
  const pos = player.position ? ` (${String(player.position)})` : "";
  const team = player.team || player.pro_team ? ` - ${String(player.team || player.pro_team)}` : "";
  return `${name}${pos}${team}`;
}

function formatPick(pick: Record<string, unknown>): string {
  const year = pick.draft_year ?? pick.year ?? "";
  const round = pick.round ? `Round ${pick.round}` : "Pick";
  const via = pick.original_owner ? ` (via ${String(pick.original_owner)})` : "";
  return `${year} ${round}${via}`.trim();
}

function extractTargetDraftYears(trade: TradeItem): number[] {
  const years = new Set<number>();
  for (const party of trade.parties) {
    for (const b of party.auction_dollars) {
      if (b.draft_year) years.add(b.draft_year);
    }
    for (const p of party.draft_picks_sent) {
      if (p.draft_year && typeof p.draft_year === "number") years.add(p.draft_year);
    }
    for (const p of party.draft_picks_received) {
      if (p.draft_year && typeof p.draft_year === "number") years.add(p.draft_year);
    }
  }
  for (const cond of trade.conditions) {
    if (cond.draft_year && typeof cond.draft_year === "number") {
      years.add(cond.draft_year);
    }
  }
  return Array.from(years).sort((a, b) => a - b);
}

export function TradeCard({ trade }: TradeCardProps) {
  const targetYears = extractTargetDraftYears(trade);

  return (
    <article
      aria-label={`Trade ${trade.external_trade_id}`}
      className="rounded-lg border border-line bg-surface p-4 shadow-sm transition-shadow hover:shadow-md"
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line-subtle pb-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs font-bold text-ink-strong">
            #{trade.external_trade_id}
          </span>
          <span className="text-xs text-ink-muted">•</span>
          <time dateTime={trade.trade_date} className="text-xs font-medium text-ink-muted">
            {formatTradeDate(trade.trade_date)}
          </time>
          <span className="inline-flex items-center rounded-md bg-surface-strong px-2 py-0.5 text-[11px] font-semibold text-ink-muted">
            {trade.agreement_season} Season
          </span>
          {trade.is_settled && (
            <span className="inline-flex items-center rounded-md bg-surface-strong px-2 py-0.5 text-[11px] font-semibold text-ink-faint">
              Settled / Drafted
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {targetYears.map((year) => (
            <span
              key={year}
              className="inline-flex items-center rounded-full bg-brand-soft px-2.5 py-0.5 text-[11px] font-semibold text-brand-ink border border-brand-soft-line"
            >
              {year} Draft
            </span>
          ))}
          {trade.discord_url && (
            <a
              href={trade.discord_url}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`View trade ${trade.external_trade_id} on Discord`}
              className="inline-flex items-center gap-1 rounded bg-surface-strong px-2 py-0.5 text-xs font-medium text-ink hover:bg-surface-emphasis hover:text-ink-strong focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"
            >
              <span>Discord</span>
              <span aria-hidden="true">↗</span>
            </a>
          )}
        </div>
      </div>

      {/* Summary Notes */}
      {trade.summary && (
        <div className="mt-3 rounded bg-surface-muted p-2.5 text-xs leading-relaxed text-ink-muted border border-line-subtle">
          <span className="font-semibold text-ink">Summary: </span>
          {trade.summary}
        </div>
      )}

      {/* Parties Grid */}
      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        {trade.parties.map((party: TradePartyItem) => {
          // Negative dollars mean the party is giving/sending dollars away;
          // Positive dollars mean the party is receiving dollars.
          const dollarsGiving = party.auction_dollars.filter((d) => Number(d.amount) < 0);
          const dollarsReceiving = party.auction_dollars.filter((d) => Number(d.amount) > 0);

          return (
            <div
              key={party.id || party.team_name_raw}
              className="flex flex-col justify-between rounded-lg border border-line bg-surface-muted/50 p-3"
            >
              <div>
                <h3 className="font-bold text-sm text-ink">{party.team_name_raw}</h3>

                {/* Gives Section */}
                <div className="mt-2 space-y-1">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-ink-faint">
                    Gives / Sends:
                  </span>
                  <ul className="space-y-1 pl-1 text-xs">
                    {party.players_sent.length === 0 &&
                    party.draft_picks_sent.length === 0 &&
                    dollarsGiving.length === 0 ? (
                      <li className="italic text-ink-faint">No outgoing assets</li>
                    ) : (
                      <>
                        {party.players_sent.map((p, idx) => (
                          <li key={idx} className="flex items-center gap-1.5 text-ink">
                            <span className="text-danger-ink" aria-hidden="true">
                              −
                            </span>
                            <span>{formatPlayer(p)}</span>
                          </li>
                        ))}
                        {party.draft_picks_sent.map((pick, idx) => (
                          <li key={idx} className="flex items-center gap-1.5 text-ink">
                            <span className="text-danger-ink" aria-hidden="true">
                              −
                            </span>
                            <span>{formatPick(pick)}</span>
                          </li>
                        ))}
                        {dollarsGiving.map((b, idx) => (
                          <li
                            key={idx}
                            className="flex items-center gap-1.5 font-semibold text-danger-ink"
                          >
                            <span aria-hidden="true">−</span>
                            <span>
                              {formatAuctionDollars(Math.abs(Number(b.amount)))} ({b.draft_year}{" "}
                              Auction $)
                            </span>
                          </li>
                        ))}
                      </>
                    )}
                  </ul>
                </div>

                {/* Receives Section */}
                <div className="mt-3 space-y-1 border-t border-line-subtle pt-2">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-ink-faint">
                    Receives:
                  </span>
                  <ul className="space-y-1 pl-1 text-xs">
                    {party.players_received.length === 0 &&
                    party.draft_picks_received.length === 0 &&
                    dollarsReceiving.length === 0 ? (
                      <li className="italic text-ink-faint">No incoming assets</li>
                    ) : (
                      <>
                        {party.players_received.map((p, idx) => (
                          <li key={idx} className="flex items-center gap-1.5 text-ink">
                            <span className="text-brand-ink" aria-hidden="true">
                              +
                            </span>
                            <span>{formatPlayer(p)}</span>
                          </li>
                        ))}
                        {party.draft_picks_received.map((pick, idx) => (
                          <li key={idx} className="flex items-center gap-1.5 text-ink">
                            <span className="text-brand-ink" aria-hidden="true">
                              +
                            </span>
                            <span>{formatPick(pick)}</span>
                          </li>
                        ))}
                        {dollarsReceiving.map((b, idx) => (
                          <li
                            key={idx}
                            className="flex items-center gap-1.5 font-semibold text-brand-ink"
                          >
                            <span aria-hidden="true">+</span>
                            <span>
                              {formatAuctionDollars(b.amount)} ({b.draft_year} Auction $)
                            </span>
                          </li>
                        ))}
                      </>
                    )}
                  </ul>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Conditional Terms Section */}
      {trade.conditions && trade.conditions.length > 0 && (
        <div className="mt-4 rounded-lg border border-line-subtle bg-surface-strong/30 p-3">
          <h4 className="text-xs font-bold uppercase tracking-wider text-ink-faint">
            Conditional Clauses ({trade.conditions.length})
          </h4>
          <div className="mt-2 space-y-2">
            {trade.conditions.map((cond, idx) => {
              const status = String(cond.status || "pending").toLowerCase();
              const isFulfilled = status === "fulfilled";
              const isPending = status === "pending";

              const badgeColor = isFulfilled
                ? "bg-brand-soft text-brand-ink border-brand-soft-line"
                : isPending
                  ? "bg-warning-surface text-warning-ink border-warning-line"
                  : "bg-surface-strong text-ink-faint border-line";

              const desc = String(
                cond.description || cond.condition || cond.text || "Conditional terms",
              );
              const amount = cond.amount ? Number(cond.amount) : null;
              const draftYear = cond.draft_year ? String(cond.draft_year) : null;
              const paying = cond.paying_team ? String(cond.paying_team) : null;
              const receiving = cond.receiving_team ? String(cond.receiving_team) : null;

              return (
                <div
                  key={idx}
                  className="flex flex-wrap items-center justify-between gap-2 rounded border border-line-subtle bg-surface p-2 text-xs"
                >
                  <div className="flex-1 space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span
                        className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase ${badgeColor}`}
                      >
                        {status}
                      </span>
                      <span className="font-medium text-ink">{desc}</span>
                    </div>
                    {(paying || receiving || draftYear) && (
                      <p className="text-[11px] text-ink-faint">
                        {paying && receiving && (
                          <span>
                            {paying} → {receiving}
                          </span>
                        )}
                        {draftYear && <span> • {draftYear} Draft</span>}
                      </p>
                    )}
                  </div>
                  {amount !== null && (
                    <div className="shrink-0 text-right">
                      <span
                        className={`inline-block rounded px-2 py-0.5 text-xs font-bold ${dollarBadgeClass(
                          dollarTone(amount),
                        )}`}
                      >
                        {formatAuctionDollars(amount, { showPlus: true })}
                      </span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </article>
  );
}
