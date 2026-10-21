import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";

import { toDisplayError, type DisplayError } from "../api/errors";
import { ApiAlert } from "../components/ApiAlert";
import { inputClass, labelClass, primaryButtonClass } from "../components/formStyles";
import { AuthLayout } from "./AuthLayout";
import { useAuth } from "./AuthContext";
import { afterAuthTarget, redirectTarget } from "./redirect";

/** Email/password login. A success returns the visitor to the route that redirected them here. */
export function LoginPage() {
  const { status, user, login, bootError } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const target = redirectTarget(location.state);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
      const signedIn = await login(email.trim(), password);
      navigate(afterAuthTarget(signedIn, target), { replace: true });
    } catch (failure) {
      setError(toDisplayError(failure));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthLayout
      title="Log in"
      subtitle="Use the email and password for your invite."
      footer={
        <>
          Have an invite?{" "}
          <Link
            to="/signup"
            state={location.state}
            className="font-semibold text-brand hover:underline"
          >
            Create an account
          </Link>
        </>
      }
    >
      {bootError === null ? null : (
        <p role="alert" className="mb-4 text-[13px] text-red-800">
          {bootError}
        </p>
      )}
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <div>
          <label htmlFor="login-email" className={labelClass}>
            Email
          </label>
          <input
            id="login-email"
            name="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className={inputClass}
          />
        </div>
        <div>
          <label htmlFor="login-password" className={labelClass}>
            Password
          </label>
          <input
            id="login-password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className={inputClass}
          />
        </div>
        <ApiAlert error={error} />
        <button type="submit" disabled={submitting} className={`${primaryButtonClass} w-full`}>
          {submitting ? "Logging in…" : "Log in"}
        </button>
      </form>
    </AuthLayout>
  );
}
