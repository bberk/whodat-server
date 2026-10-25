import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { ThemeToggle } from "../theme/ThemeToggle";

/** Shared centered shell for the login, signup, and onboarding pages. */
export function AuthLayout({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <div className="flex min-h-full flex-col bg-page text-ink">
      <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-4 py-10 sm:px-6">
        <div className="mb-4 flex justify-end">
          <ThemeToggle />
        </div>
        <div className="mb-6 flex items-center gap-3">
          <span
            aria-hidden="true"
            className="flex h-[34px] w-[34px] items-center justify-center rounded-lg bg-brand text-[15px] font-bold tracking-wide text-brand-foreground"
          >
            VP
          </span>
          <div>
            <p className="text-[15px] font-semibold">Victory Points Standings</p>
            <p className="text-xs text-ink-faint">Fantasy football, ranked your way</p>
          </div>
        </div>
        <section className="rounded-xl border border-line bg-surface p-5 shadow-sm sm:p-6">
          <h1 className="text-xl font-bold">{title}</h1>
          <p className="mt-1 text-[13px] text-ink-faint">{subtitle}</p>
          <div className="mt-5">{children}</div>
        </section>
        <p className="mt-4 text-center text-[13px] text-ink-subtle">{footer}</p>
      </main>
      <footer className="px-4 pb-6 text-center text-xs text-ink-faint">
        <Link to="/" className="hover:text-brand-ink">
          Victory Points
        </Link>
      </footer>
    </div>
  );
}
