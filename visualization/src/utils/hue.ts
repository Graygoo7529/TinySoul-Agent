/**
 * Stable hue identity for an entity or type name: FNV-1a hash scattered by
 * the golden angle, so the same name always lands on the same hue and
 * neighbours on the wheel stay apart. No storage, no user configuration.
 */
export function hueForId(id: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < id.length; i += 1) {
    hash ^= id.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  const scattered = ((hash >>> 0) * 137.508) % 360;
  // Stay in the calm green→teal→blue band; warm reds/oranges/yellows and the
  // violet end both fight the theme's indigo/semantic colors.
  return 150 + (scattered / 360) * 105;
}
