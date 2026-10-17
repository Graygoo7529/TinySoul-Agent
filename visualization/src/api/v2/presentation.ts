/** Project-scoped presentation contracts; independent of Agent generation/day. */
export interface InterfaceSettings {
  theme: "light" | "dark";
  font_sans: "inter" | "system" | "serif";
  font_mono: "jetbrains" | "system" | "cascadia";
  font_size: number;
  line_height: number;
  density: "compact" | "comfortable" | "roomy";
  reduced_motion: boolean;
}

export interface PresentationConfig {
  id: "interface";
  path: string;
  exists: boolean;
  values: InterfaceSettings;
  defaults: InterfaceSettings;
}

export interface PresentationAsset {
  path: string;
  media_type: string;
  size: number;
}

export interface PresentationAssets {
  items: PresentationAsset[];
}
