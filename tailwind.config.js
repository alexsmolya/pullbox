/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/pullbox/ui/templates/**/*.html",
    "./src/pullbox/ui/static/js/pullbox.js",
  ],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        /* Brand (orange) — logo "o" + active nav dot ONLY in app */
        "pb-brand":             "var(--pb-brand)",
        "pb-brand-hover":       "var(--pb-brand-hover)",
        "pb-brand-dim":         "var(--pb-brand-dim)",
        "pb-brand-border":      "var(--pb-brand-border)",

        /* Interactive (blue) — ALL buttons, toggles, links, focus rings */
        "pb-interactive":       "var(--pb-interactive)",
        "pb-interactive-hover": "var(--pb-interactive-hover)",
        "pb-interactive-dim":   "var(--pb-interactive-dim)",
        "pb-interactive-border":"var(--pb-interactive-border)",

        /* Status — semantic only */
        "pb-success":           "var(--pb-success)",
        "pb-success-dim":       "var(--pb-success-dim)",
        "pb-warning":           "var(--pb-warning)",
        "pb-warning-dim":       "var(--pb-warning-dim)",
        "pb-error":             "var(--pb-error)",
        "pb-error-dim":         "var(--pb-error-dim)",
        "pb-info":              "var(--pb-info)",
        "pb-info-dim":          "var(--pb-info-dim)",
        "pb-purple":            "var(--pb-purple)",
        "pb-purple-dim":        "var(--pb-purple-dim)",

        /* Backgrounds */
        "pb-base":              "var(--pb-bg-base)",
        "pb-surface":           "var(--pb-bg-surface)",
        "pb-card":              "var(--pb-bg-card)",
        "pb-card-hover":        "var(--pb-bg-card-hover)",
        "pb-raised":            "var(--pb-surface-raised)",
        "pb-input":             "var(--pb-bg-input)",
        "pb-overlay":           "var(--pb-bg-overlay)",
        "pb-selected":          "var(--pb-surface-selected)",

        /* Text */
        "pb-text":              "var(--pb-text-primary)",
        "pb-text-sec":          "var(--pb-text-secondary)",
        "pb-text-dim":          "var(--pb-text-dim)",
        "pb-text-inverse":      "var(--pb-text-inverse)",

        /* Borders */
        "pb-border-subtle":     "var(--pb-border-subtle)",
        "pb-border":            "var(--pb-border)",
        "pb-border-hover":      "var(--pb-border-hover)",
        "pb-border-strong":     "var(--pb-border-strong)",

        /* Focus */
        "pb-focus-ring":        "var(--pb-focus-ring)",
        "pb-focus-outline":     "var(--pb-focus-outline)",

        /* Legacy aliases — keep during migration, remove in UI-3.4 */
        surface: {
          DEFAULT: "#0f172a",
          50: "#f8fafc", 100: "#f1f5f9", 200: "#e2e8f0", 300: "#cbd5e1",
          400: "#94a3b8", 500: "#64748b", 600: "#475569", 700: "#334155",
          800: "#1e293b", 900: "#0f172a", 950: "#020617",
        },
        pb: {
          DEFAULT: "#3b82f6",
          50: "#eff6ff", 100: "#dbeafe", 200: "#bfdbfe", 300: "#93c5fd",
          400: "#60a5fa", 500: "#3b82f6", 600: "#2563eb", 700: "#1d4ed8",
          800: "#1e40af", 900: "#1e3a8a",
        },
      },
      fontFamily: {
        display: ['"Bricolage Grotesque"', "sans-serif"],
        sans:    ['"DM Sans"', "sans-serif"],
        mono:    ['"JetBrains Mono"', '"Fira Code"', "monospace"],
      },
      borderRadius: {
        "pb-sm":   "6px",
        "pb-md":   "10px",
        "pb-lg":   "14px",
        "pb-xl":   "20px",
        "pb-full": "9999px",
      },
      fontSize: {
        "pb-xs":   ["0.75rem",  { lineHeight: "1rem" }],
        "pb-sm":   ["0.875rem", { lineHeight: "1.25rem" }],
        "pb-base": ["1rem",     { lineHeight: "1.5rem" }],
        "pb-lg":   ["1.125rem", { lineHeight: "1.75rem" }],
        "pb-xl":   ["1.375rem", { lineHeight: "1.75rem" }],
        "pb-2xl":  ["1.75rem",  { lineHeight: "2.25rem" }],
        "pb-hero": ["clamp(2.5rem, 6vw, 4rem)", { lineHeight: "1.1" }],
      },
    },
  },
  plugins: [],
};
