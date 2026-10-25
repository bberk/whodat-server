import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { adminUser } from "../test/fixtures";
import { ThemeProvider } from "../theme/ThemeProvider";
import { AuthContext, type AuthContextValue } from "./AuthContext";
import { LoginPage } from "./LoginPage";
import { SignupPage } from "./SignupPage";

function authValue(overrides: Partial<AuthContextValue> = {}): AuthContextValue {
  return {
    status: "signed-out",
    user: null,
    bootError: null,
    login: vi.fn(),
    signup: vi.fn().mockResolvedValue(adminUser),
    refreshUser: vi.fn(),
    logout: vi.fn(),
    ...overrides,
  };
}

function renderAt(path: string, element: ReactElement, value = authValue()) {
  return render(
    <ThemeProvider>
      <AuthContext.Provider value={value}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={path} element={element} />
            <Route path="/" element={<p>standings destination</p>} />
            <Route path="/onboarding" element={<p>onboarding destination</p>} />
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>
    </ThemeProvider>,
  );
}

describe("auth form input constraints", () => {
  it("bounds login email and password inputs", () => {
    renderAt("/login", <LoginPage />);

    const email = screen.getByLabelText("Email");
    const password = screen.getByLabelText("Password");
    expect(email).toHaveAttribute("type", "email");
    expect(email).toHaveAttribute("inputMode", "email");
    expect(email).toHaveAttribute("maxLength", "320");
    expect(password).toHaveAttribute("type", "password");
    expect(password).toHaveAttribute("maxLength", "1024");
  });

  it("bounds signup fields and constrains the invite alphabet", () => {
    renderAt("/signup", <SignupPage />);

    const email = screen.getByLabelText("Email");
    const password = screen.getByLabelText("Password");
    const invite = screen.getByLabelText("Invite code");
    expect(email).toHaveAttribute("inputMode", "email");
    expect(email).toHaveAttribute("maxLength", "320");
    expect(password).toHaveAttribute("minLength", "8");
    expect(password).toHaveAttribute("maxLength", "1024");
    expect(invite).toHaveAttribute("maxLength", "128");
    expect(invite).toHaveAttribute("pattern", "[A-Za-z0-9_-]+");
    expect(invite).toHaveAttribute("autoCapitalize", "none");
    expect(invite).toHaveAttribute("spellCheck", "false");
  });

  it("rejects a non-ASCII login email or password before calling the API", async () => {
    const user = userEvent.setup();
    const value = authValue();
    renderAt("/login", <LoginPage />, value);

    await user.type(screen.getByLabelText("Email"), "usér@example.com");
    await user.type(screen.getByLabelText("Password"), "ASCII-password");
    await user.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Email must contain only ASCII characters.",
    );
    expect(value.login).not.toHaveBeenCalled();

    await user.clear(screen.getByLabelText("Email"));
    await user.type(screen.getByLabelText("Email"), "fan@example.com");
    await user.clear(screen.getByLabelText("Password"));
    await user.type(screen.getByLabelText("Password"), "pässwörd");
    await user.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Password must contain only ASCII characters.",
    );
    expect(value.login).not.toHaveBeenCalled();
  });

  it.each([
    ["email", "🙂@example.com", "Email"],
    ["password", "🙂🙂🙂🙂🙂🙂🙂🙂", "Password"],
    ["invite", "café", "Invite code"],
  ])("rejects a non-ASCII signup %s before calling the API", async (_field, value, label) => {
    const user = userEvent.setup();
    const auth = authValue();
    renderAt("/signup", <SignupPage />, auth);

    await user.type(screen.getByLabelText("Email"), "fan@example.com");
    await user.type(screen.getByLabelText("Password"), "ASCII-password");
    await user.type(screen.getByLabelText("Invite code"), "valid-code");
    await user.clear(screen.getByLabelText(label));
    await user.type(screen.getByLabelText(label), value);
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      `${label} must contain only ASCII characters.`,
    );
    expect(auth.signup).not.toHaveBeenCalled();
  });

  it("trims the email and invite code before signup, and leaves the password exact", async () => {
    const user = userEvent.setup();
    const value = authValue();
    renderAt("/signup", <SignupPage />, value);

    await user.type(screen.getByLabelText("Email"), "  Fan@Example.COM ");
    await user.type(screen.getByLabelText("Password"), " spaced password ");
    await user.type(screen.getByLabelText("Invite code"), "  valid-code  ");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => {
      expect(value.signup).toHaveBeenCalledWith(
        "Fan@Example.COM",
        " spaced password ",
        "valid-code",
      );
    });
  });
});
