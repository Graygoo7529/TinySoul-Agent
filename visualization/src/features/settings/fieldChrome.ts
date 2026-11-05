/**
 * Shared visual chrome for settings field controls, consumed by both control
 * libraries (editors/draftControls, models/modelControls). Only visual values
 * live here — layout (width, flex) stays at each usage site.
 */

/** Text-input treatment: sunken fill inside elevated cards, accent focus glow. */
export const inputChrome =
  "focus-ring h-8 rounded-md border border-line bg-bg px-2.5 text-[12.5px] text-fg outline-none transition-colors focus:border-accent disabled:cursor-not-allowed disabled:opacity-50";

/** Row padding shared by both FieldRow implementations. */
export const fieldRowPadding = "px-4 py-2.5";
