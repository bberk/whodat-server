import { useEffect, useState } from "react";

import { api } from "../api/endpoints";
import { toDisplayError, type DisplayError } from "../api/errors";
import type { LeagueMemberSummary } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ApiAlert } from "../components/ApiAlert";
import { EmptyState, ErrorState, LoadingState } from "../components/DataStates";
import { dangerSecondaryButtonClass, secondaryButtonClass } from "../components/formStyles";

type MembersState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "empty" }
  | { status: "ready"; members: LeagueMemberSummary[] };

interface MembersSectionProps {
  leagueId: number;
  /** Called after the signed-in admin removes their own membership, so the page can leave. */
  onSelfRemoved: () => void;
}

function roleLabel(role: string): string {
  return role === "admin" ? "Admin" : "Member";
}

/**
 * Admin: every account associated with this league, with a confirmed removal action (AC-AU-19/20).
 *
 * Email is the account identifier because the application has no username. A removal deletes only
 * this league's membership; the confirmation names the member and warns when they are the last
 * admin (the action is disabled) or the only member with stored credentials (refresh stops
 * working). Success and failure are announced as text, never by colour alone.
 */
export function MembersSection({ leagueId, onSelfRemoved }: MembersSectionProps) {
  const { user } = useAuth();
  const [state, setState] = useState<MembersState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [pending, setPending] = useState<LeagueMemberSummary | null>(null);
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState<DisplayError | null>(null);
  const [removed, setRemoved] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    api.members(leagueId, controller.signal).then(
      (response) => {
        if (controller.signal.aborted) {
          return;
        }
        setState(
          response.members.length === 0
            ? { status: "empty" }
            : { status: "ready", members: response.members },
        );
      },
      (failure: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setState({
          status: "error",
          message: failure instanceof Error ? failure.message : "Could not load members.",
        });
      },
    );
    return () => {
      controller.abort();
    };
  }, [leagueId, attempt]);

  const members = state.status === "ready" ? state.members : [];
  const adminCount = members.filter((member) => member.role === "admin").length;
  const credentialHolderCount = members.filter((member) => member.has_credentials).length;

  const openConfirmation = (member: LeagueMemberSummary) => {
    setError(null);
    setRemoved(null);
    setPending(member);
  };

  const closeConfirmation = () => {
    if (removing) {
      return;
    }
    setError(null);
    setPending(null);
  };

  const confirmRemoval = async () => {
    if (pending === null) {
      return;
    }
    const target = pending;
    setRemoving(true);
    setError(null);
    try {
      await api.removeMember(leagueId, target.user_id);
      setPending(null);
      if (target.user_id === user?.id) {
        onSelfRemoved();
        return;
      }
      setRemoved(`Removed ${target.email} from this league.`);
      setAttempt((current) => current + 1);
    } catch (failure) {
      setError(toDisplayError(failure));
    } finally {
      setRemoving(false);
    }
  };

  const targetIsSelf = pending !== null && pending.user_id === user?.id;
  const targetIsLastAdmin = pending !== null && pending.role === "admin" && adminCount === 1;
  const targetIsOnlyCredentialHolder =
    pending !== null && pending.has_credentials && credentialHolderCount === 1;

  return (
    <section aria-labelledby="h-members" className="mt-7">
      <h2 id="h-members" className="text-base font-bold">
        Members
      </h2>
      <p className="mt-1 text-[13px] text-ink-faint">
        Everyone with access to this league. Removing a member deletes only their membership here;
        their account and other leagues are not affected.
      </p>

      {state.status === "loading" ? <LoadingState label="Loading members…" /> : null}

      {state.status === "error" ? (
        <ErrorState onRetry={() => setAttempt((current) => current + 1)} message={state.message} />
      ) : null}

      {state.status === "empty" ? (
        <EmptyState
          title="No members"
          detail="This league has no memberships yet. Share a member invite to add someone."
        />
      ) : null}

      {removed === null ? null : (
        <p role="status" className="mt-3 text-[13px] font-semibold text-ink-strong">
          {removed}
        </p>
      )}

      {state.status === "ready" ? (
        <div className="mt-3 overflow-x-auto rounded-xl border border-line bg-surface">
          <table className="w-full min-w-[640px] border-collapse text-left text-[13px]">
            <caption className="sr-only">
              Accounts with access to this league, their role, owner association, and whether they
              hold stored credentials.
            </caption>
            <thead>
              <tr className="border-b border-line bg-surface-muted text-ink-muted">
                <th scope="col" className="px-3 py-2 font-semibold">
                  Email
                </th>
                <th scope="col" className="px-3 py-2 font-semibold">
                  Role
                </th>
                <th scope="col" className="px-3 py-2 font-semibold">
                  Owner
                </th>
                <th scope="col" className="px-3 py-2 font-semibold">
                  Credentials
                </th>
                <th scope="col" className="px-3 py-2 font-semibold">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {state.members.map((member) => {
                const isSelf = member.user_id === user?.id;
                const isLastAdmin = member.role === "admin" && adminCount === 1;
                return (
                  <tr key={member.user_id} className="border-b border-line-subtle last:border-0">
                    <th scope="row" className="max-w-[220px] px-3 py-2 font-medium text-ink">
                      <span className="break-all">{member.email}</span>
                      {isSelf ? (
                        <span className="ml-2 rounded bg-surface-strong px-1.5 py-0.5 text-[11px] font-semibold text-ink-muted">
                          You
                        </span>
                      ) : null}
                    </th>
                    <td className="px-3 py-2 text-ink-muted">{roleLabel(member.role)}</td>
                    <td className="px-3 py-2 text-ink-muted">{member.owner_name ?? "—"}</td>
                    <td className="px-3 py-2 text-ink-muted">
                      {member.has_credentials ? "Stored" : "None"}
                    </td>
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        onClick={() => openConfirmation(member)}
                        disabled={isLastAdmin}
                        aria-describedby={isLastAdmin ? `last-admin-${member.user_id}` : undefined}
                        className={dangerSecondaryButtonClass}
                      >
                        Remove
                      </button>
                      {isLastAdmin ? (
                        <span
                          id={`last-admin-${member.user_id}`}
                          className="mt-1 block text-[12px] text-ink-subtle"
                        >
                          The league&rsquo;s last admin cannot be removed.
                        </span>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      {pending === null ? null : (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-overlay/40 p-4 sm:items-center">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="h-remove-member"
            className="w-full max-w-md rounded-xl border border-line bg-surface p-5 shadow-xl"
          >
            <h3 id="h-remove-member" className="text-lg font-bold">
              Remove {pending.email}?
            </h3>
            <p className="mt-2 text-[13px] text-ink-subtle">
              This deletes {pending.email}&rsquo;s membership in this league only. Their account and
              any other leagues are not affected.
            </p>
            {targetIsSelf ? (
              <p className="mt-2 text-[13px] font-semibold text-ink-strong">
                This is your own membership. You will lose access to this league.
              </p>
            ) : null}
            {targetIsOnlyCredentialHolder ? (
              <p className="mt-2 rounded-lg border border-warning-line bg-warning-surface px-3 py-2 text-[13px] text-warning-ink">
                Refresh will stop working after this removal: this member is the only one in the
                league with stored ESPN credentials.
              </p>
            ) : null}
            {targetIsLastAdmin ? (
              <p className="mt-2 text-[13px] text-danger-ink">
                This is the league&rsquo;s last admin. Add another admin member before removing
                them.
              </p>
            ) : null}
            {error === null ? null : (
              <div className="mt-3">
                <ApiAlert error={error} />
              </div>
            )}
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={closeConfirmation}
                disabled={removing}
                className={secondaryButtonClass}
                autoFocus
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  void confirmRemoval();
                }}
                disabled={removing || targetIsLastAdmin}
                className={dangerSecondaryButtonClass}
              >
                {removing ? "Removing…" : "Remove member"}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
