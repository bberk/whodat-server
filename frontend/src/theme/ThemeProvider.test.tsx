import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthLayout } from "../auth/AuthLayout";
import { ThemeProvider } from "./ThemeProvider";
import { ThemeToggle } from "./ThemeToggle";
import { DARK_MEDIA_QUERY, THEME_STORAGE_KEY } from "./theme";

type Listener = (event: MediaQueryListEvent) => void;

interface MatchMediaStub {
  setDark: (dark: boolean) => void;
  listenerCount: () => number;
}

/** Install a controllable `prefers-color-scheme` media query, like a real browser reports it. */
function installMatchMedia(initialDark: boolean): MatchMediaStub {
  const listeners = new Set<Listener>();
  let matches = initialDark;
  const media = {
    get matches() {
      return matches;
    },
    media: DARK_MEDIA_QUERY,
    onchange: null,
    addEventListener: (_type: string, listener: Listener) => {
      listeners.add(listener);
    },
    removeEventListener: (_type: string, listener: Listener) => {
      listeners.delete(listener);
    },
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => true,
  };
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: vi.fn(() => media),
  });
  return {
    setDark: (dark: boolean) => {
      matches = dark;
      listeners.forEach((listener) => listener({ matches: dark } as MediaQueryListEvent));
    },
    listenerCount: () => listeners.size,
  };
}

function renderToggle() {
  return render(
    <ThemeProvider>
      <ThemeToggle />
    </ThemeProvider>,
  );
}

afterEach(() => {
  Reflect.deleteProperty(window, "matchMedia");
  window.localStorage.clear();
  document.documentElement.className = "";
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.style.colorScheme = "";
});

describe("ThemeProvider", () => {
  it("applies the operating system dark preference on a first visit", () => {
    installMatchMedia(true);
    renderToggle();

    expect(document.documentElement).toHaveClass("dark");
    expect(screen.getByRole("radio", { name: "System" })).toBeChecked();
    expect(screen.getByText(/System theme, following your device \(dark\)/)).toBeInTheDocument();
  });

  it("stays light on a first visit when the operating system prefers light", () => {
    installMatchMedia(false);
    renderToggle();

    expect(document.documentElement).not.toHaveClass("dark");
    expect(screen.getByText(/System theme, following your device \(light\)/)).toBeInTheDocument();
  });

  it("restores an explicit stored choice over the system preference", () => {
    installMatchMedia(true);
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");
    renderToggle();

    expect(document.documentElement).not.toHaveClass("dark");
    expect(screen.getByRole("radio", { name: "Light" })).toBeChecked();
  });

  it("persists an explicit choice and applies it immediately", async () => {
    const user = userEvent.setup();
    installMatchMedia(false);
    renderToggle();

    await user.click(screen.getByRole("radio", { name: "Dark" }));

    expect(document.documentElement).toHaveClass("dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(screen.getByText("Dark theme selected.")).toBeInTheDocument();
  });

  it("clears storage when the visitor returns to System and follows the OS again", async () => {
    const user = userEvent.setup();
    installMatchMedia(true);
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");
    renderToggle();
    expect(document.documentElement).not.toHaveClass("dark");

    await user.click(screen.getByRole("radio", { name: "System" }));

    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
    expect(document.documentElement).toHaveClass("dark");
    expect(screen.getByRole("radio", { name: "System" })).toBeChecked();
  });

  it("follows live system changes while in System mode", () => {
    const media = installMatchMedia(false);
    renderToggle();
    expect(document.documentElement).not.toHaveClass("dark");

    act(() => media.setDark(true));
    expect(document.documentElement).toHaveClass("dark");

    act(() => media.setDark(false));
    expect(document.documentElement).not.toHaveClass("dark");
  });

  it("ignores live system changes after an explicit choice", async () => {
    const user = userEvent.setup();
    const media = installMatchMedia(false);
    renderToggle();
    await user.click(screen.getByRole("radio", { name: "Light" }));

    act(() => media.setDark(true));
    expect(document.documentElement).not.toHaveClass("dark");

    await user.click(screen.getByRole("radio", { name: "Dark" }));
    act(() => media.setDark(false));
    expect(document.documentElement).toHaveClass("dark");
  });

  it("removes its media-query listener on unmount", () => {
    const media = installMatchMedia(false);
    const { unmount } = renderToggle();
    expect(media.listenerCount()).toBe(1);

    unmount();
    expect(media.listenerCount()).toBe(0);
  });
});

describe("ThemeToggle", () => {
  it("exposes a named three-state radio group with the current state checked", () => {
    installMatchMedia(false);
    renderToggle();

    expect(screen.getByRole("group", { name: "Colour theme" })).toBeInTheDocument();
    const options = screen.getAllByRole("radio");
    expect(options.map((option) => option.getAttribute("value"))).toEqual([
      "system",
      "light",
      "dark",
    ]);
    expect(screen.getByRole("radio", { name: "System" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Light" })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: "Dark" })).not.toBeChecked();
  });

  it("announces the current state in a polite live region", async () => {
    const user = userEvent.setup();
    installMatchMedia(false);
    renderToggle();

    const live = document.querySelector('[aria-live="polite"]');
    expect(live).toHaveTextContent("System theme, following your device (light).");

    await user.click(screen.getByRole("radio", { name: "Dark" }));
    expect(live).toHaveTextContent("Dark theme selected.");
  });
});

describe("theme coverage across pages", () => {
  it("renders the auth page shell and its toggle in both themes", () => {
    for (const dark of [false, true]) {
      installMatchMedia(dark);
      const { unmount } = render(
        <ThemeProvider>
          <MemoryRouter>
            <AuthLayout title="Log in" subtitle="Use your invite." footer={<span>footer</span>}>
              <p>form body</p>
            </AuthLayout>
          </MemoryRouter>
        </ThemeProvider>,
      );

      expect(screen.getByRole("heading", { level: 1, name: "Log in" })).toBeInTheDocument();
      expect(screen.getByText("form body")).toBeInTheDocument();
      expect(document.documentElement.classList.contains("dark")).toBe(dark);
      expect(screen.getByRole("group", { name: "Colour theme" })).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: "System" })).toBeChecked();

      unmount();
    }
  });
});
