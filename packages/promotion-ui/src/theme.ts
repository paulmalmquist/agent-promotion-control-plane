import type { CSSProperties } from "react";
import type { PromotionThemeTokens } from "./types.js";

export const defaultPromotionTheme: PromotionThemeTokens = {
  background: "#101116",
  surface: "#161820",
  surfaceRaised: "#1b1e27",
  text: "#f4f1e9",
  textMuted: "#a6a5ae",
  line: "#30323c",
  lineStrong: "#4a4d59",
  decision: "#9578ff",
  comparison: "#2f9d82",
  degraded: "#c9963f",
  stop: "#d16065",
  focus: "#c4b7ff",
  fontSans: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  fontMono: "'IBM Plex Mono', 'SFMono-Regular', Consolas, monospace",
  radiusSmall: "2px",
  radiusLarge: "6px"
};

const tokenToVariable: Record<keyof PromotionThemeTokens, string> = {
  background: "--pcp-background",
  surface: "--pcp-surface",
  surfaceRaised: "--pcp-surface-raised",
  text: "--pcp-text",
  textMuted: "--pcp-text-muted",
  line: "--pcp-line",
  lineStrong: "--pcp-line-strong",
  decision: "--pcp-decision",
  comparison: "--pcp-comparison",
  degraded: "--pcp-degraded",
  stop: "--pcp-stop",
  focus: "--pcp-focus",
  fontSans: "--pcp-font-sans",
  fontMono: "--pcp-font-mono",
  radiusSmall: "--pcp-radius-small",
  radiusLarge: "--pcp-radius-large"
};

export function themeTokenStyle(tokens?: Partial<PromotionThemeTokens>): CSSProperties {
  const resolved = { ...defaultPromotionTheme, ...tokens };
  return Object.fromEntries(
    Object.entries(resolved).map(([key, value]) => [
      tokenToVariable[key as keyof PromotionThemeTokens],
      value
    ])
  ) as CSSProperties;
}
