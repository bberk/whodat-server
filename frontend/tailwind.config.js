/**
 * Design tokens for the light and dark themes.
 *
 * Every surface, line, ink, accent, brand, and status colour resolves through a CSS variable
 * defined in `src/index.css` (light values on `:root`, the deliberate dark palette on
 * `:root.dark`), so a component never hard-codes a light-only colour. Chart colours are tokens too,
 * including a separate, higher-luminance series palette for dark backgrounds. `darkMode: "class"`
 * matches the class the pre-paint script in `index.html` and the theme provider put on `<html>`.
 */
/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        page: "rgb(var(--color-page) / <alpha-value>)",
        surface: {
          DEFAULT: "rgb(var(--color-surface) / <alpha-value>)",
          muted: "rgb(var(--color-surface-muted) / <alpha-value>)",
          strong: "rgb(var(--color-surface-strong) / <alpha-value>)",
          emphasis: "rgb(var(--color-surface-emphasis) / <alpha-value>)",
          disabled: "rgb(var(--color-surface-disabled) / <alpha-value>)",
          hover: "rgb(var(--color-surface-hover) / <alpha-value>)",
        },
        overlay: "rgb(var(--color-overlay) / <alpha-value>)",
        fade: "rgb(var(--color-fade) / <alpha-value>)",
        line: {
          DEFAULT: "rgb(var(--color-line) / <alpha-value>)",
          subtle: "rgb(var(--color-line-subtle) / <alpha-value>)",
          strong: "rgb(var(--color-line-strong) / <alpha-value>)",
          emphasis: "rgb(var(--color-line-emphasis) / <alpha-value>)",
        },
        ink: {
          DEFAULT: "rgb(var(--color-ink) / <alpha-value>)",
          strong: "rgb(var(--color-ink-strong) / <alpha-value>)",
          muted: "rgb(var(--color-ink-muted) / <alpha-value>)",
          subtle: "rgb(var(--color-ink-subtle) / <alpha-value>)",
          faint: "rgb(var(--color-ink-faint) / <alpha-value>)",
          disabled: "rgb(var(--color-ink-disabled) / <alpha-value>)",
        },
        brand: {
          DEFAULT: "rgb(var(--color-brand) / <alpha-value>)",
          foreground: "rgb(var(--color-brand-foreground) / <alpha-value>)",
          hover: "rgb(var(--color-brand-hover) / <alpha-value>)",
          ink: "rgb(var(--color-brand-ink) / <alpha-value>)",
          soft: "rgb(var(--color-brand-soft) / <alpha-value>)",
          "soft-line": "rgb(var(--color-brand-soft-line) / <alpha-value>)",
        },
        danger: {
          DEFAULT: "rgb(var(--color-danger) / <alpha-value>)",
          foreground: "rgb(var(--color-danger-foreground) / <alpha-value>)",
          hover: "rgb(var(--color-danger-hover) / <alpha-value>)",
          surface: "rgb(var(--color-danger-surface) / <alpha-value>)",
          line: "rgb(var(--color-danger-line) / <alpha-value>)",
          "line-strong": "rgb(var(--color-danger-line-strong) / <alpha-value>)",
          ink: "rgb(var(--color-danger-ink) / <alpha-value>)",
          "ink-strong": "rgb(var(--color-danger-ink-strong) / <alpha-value>)",
          "ink-soft": "rgb(var(--color-danger-ink-soft) / <alpha-value>)",
        },
        warning: {
          surface: "rgb(var(--color-warning-surface) / <alpha-value>)",
          line: "rgb(var(--color-warning-line) / <alpha-value>)",
          ink: "rgb(var(--color-warning-ink) / <alpha-value>)",
        },
        chart: {
          axis: "rgb(var(--color-chart-axis) / <alpha-value>)",
          "axis-strong": "rgb(var(--color-chart-axis-strong) / <alpha-value>)",
          label: "rgb(var(--color-chart-label) / <alpha-value>)",
          "label-muted": "rgb(var(--color-chart-label-muted) / <alpha-value>)",
          plot: "rgb(var(--color-chart-plot) / <alpha-value>)",
          grid: "rgb(var(--color-chart-grid) / <alpha-value>)",
          zero: "rgb(var(--color-chart-zero) / <alpha-value>)",
          boundary: "rgb(var(--color-chart-boundary) / <alpha-value>)",
          start: "rgb(var(--color-chart-start) / <alpha-value>)",
          "start-label": "rgb(var(--color-chart-start-label) / <alpha-value>)",
          cup: "rgb(var(--color-chart-cup) / <alpha-value>)",
          "cup-label": "rgb(var(--color-chart-cup-label) / <alpha-value>)",
          "brand-label": "rgb(var(--color-chart-brand-label) / <alpha-value>)",
        },
      },
      boxShadow: {
        sticky: "6px 0 8px -6px rgb(var(--color-shadow) / var(--shadow-strength))",
      },
    },
  },
  plugins: [],
};
