import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";

import { toDisplayError, type DisplayError } from "../api/errors";
import { ApiAlert } from "../components/ApiAlert";
import { inputClass, labelClass, primaryButtonClass } from "../components/formStyles";
import { AuthLayout } from "./AuthLayout";
import { useAuth } from "./AuthContext";
import { afterAuthTarget, redirectTarget } from "./redirect";

/** Invite-gated signup. The invite code is required and never echoed back by the API. */
export function SignupPage() {
  const { status, user, signup } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const target = redirectTarget(location.state);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [error, setError] = useState<DisplayError | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (status === "signed-in") {
    return <Navigate to={user === null ? target : afterAuthTarget(user, target)} replace />;
  }

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const signedIn = await signup(email.trim(), password, inviteCode.trim());
      navigate(afterAuthTarget(signedIn, target), { replace: true });
    } catch (failure) {
      setError(toDisplayError(failure));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthLayout
      title="Create an account"
      subtitle="Signup needs the invite code from your league admin."
      footer={
        <>
          Already have an account?{" "}
          <Link
            to="/login"
            state={location.state}
            className="font-semibold text-brand hover:underline"
          >
            Log in
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <div>
          <label htmlFor="signup-email" className={labelClass}>
            Email
          </label>
          <input
            id="signup-email"
            name="email"
            type="email"
            inputMode="email"
            autoComplete="email"
            maxLength={320}
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className={inputClass}
          />
        </div>
        <div>
          <label htmlFor="signup-password" className={labelClass}>
            Password
          </label>
          <input
            id="signup-password"
            name="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            maxLength={1024}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className={inputClass}
          />
          <p className="mt-1 text-xs text-gray-500">At least 8 characters.</p>
        </div>
        <div>
          <label htmlFor="signup-invite" className={labelClass}>
            Invite code
          </label>
          <input
            id="signup-invite"
            name="invite_code"
            type="password"
            autoComplete="off"
            inputMode="text"
            autoCapitalize="none"
            spellCheck={false}
            pattern="[A-Za-z0-9_-]+"
            maxLength={128}
            required
            value={inviteCode}
            onChange={(event) => setInviteCode(event.target.value)}
            className={inputClass}
          />
        </div>
        <ApiAlert error={error} />
        <button type="submit" disabled={submitting} className={`${primaryButtonClass} w-full`}>
          {submitting ? "Creating account…" : "Create account"}
        </button>
      </form>
    </AuthLayout>
  );
}
