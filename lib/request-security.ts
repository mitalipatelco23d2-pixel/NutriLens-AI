export function isSameOriginMutation(request: Request): boolean {
  if (["GET", "HEAD", "OPTIONS"].includes(request.method)) return true;
  return request.headers.get("origin") === new URL(request.url).origin;
}

export class RequestBodyTooLargeError extends Error {}

export async function readBoundedRequestBody(
  request: Request,
  maximumBytes: number,
): Promise<ArrayBuffer | undefined> {
  if (["GET", "HEAD"].includes(request.method) || request.body === null) {
    return undefined;
  }
  const declared = request.headers.get("content-length");
  if (declared !== null) {
    const parsed = Number(declared);
    if (!Number.isSafeInteger(parsed) || parsed < 0) {
      throw new TypeError("Invalid Content-Length header.");
    }
    if (parsed > maximumBytes) throw new RequestBodyTooLargeError();
  }
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maximumBytes) {
      await reader.cancel();
      throw new RequestBodyTooLargeError();
    }
    chunks.push(value);
  }
  const buffer = new ArrayBuffer(total);
  const body = new Uint8Array(buffer);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return buffer;
}
