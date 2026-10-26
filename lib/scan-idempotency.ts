export async function scanIdempotencyKey(
  scanKind: string,
  imageBytes: ArrayBuffer,
): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", imageBytes);
  const hex = Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  return `client-${scanKind}-${hex}`;
}
