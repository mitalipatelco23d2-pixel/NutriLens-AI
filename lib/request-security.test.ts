import { describe, expect, it } from "vitest";

import {
  isSameOriginMutation,
  readBoundedRequestBody,
  RequestBodyTooLargeError,
} from "./request-security";

describe("same-origin mutation enforcement", () => {
  it("accepts same-origin mutations", () => {
    const request = new Request(
      "https://app.nutrilens.test/api/backend/profile",
      {
        method: "PUT",
        headers: { Origin: "https://app.nutrilens.test" },
      },
    );
    expect(isSameOriginMutation(request)).toBe(true);
  });

  it("rejects missing and cross-origin mutation origins", () => {
    expect(
      isSameOriginMutation(
        new Request("https://app.nutrilens.test/api/backend/profile", {
          method: "POST",
        }),
      ),
    ).toBe(false);
    expect(
      isSameOriginMutation(
        new Request("https://app.nutrilens.test/api/backend/profile", {
          method: "DELETE",
          headers: { Origin: "https://attacker.example" },
        }),
      ),
    ).toBe(false);
  });

  it("allows read-only requests without an origin header", () => {
    expect(
      isSameOriginMutation(
        new Request("https://app.nutrilens.test/api/backend/profile"),
      ),
    ).toBe(true);
  });
});

describe("bounded request bodies", () => {
  it("preserves an exact-limit body byte-for-byte", async () => {
    const request = new Request(
      "https://app.nutrilens.test/api/backend/profile",
      {
        method: "POST",
        body: new Uint8Array([0, 1, 2, 255]),
        duplex: "half",
      } as RequestInit & { duplex: "half" },
    );
    expect(new Uint8Array((await readBoundedRequestBody(request, 4))!)).toEqual(
      new Uint8Array([0, 1, 2, 255]),
    );
  });

  it("rejects declared and streamed bodies above the limit", async () => {
    const declared = new Request(
      "https://app.nutrilens.test/api/backend/profile",
      {
        method: "POST",
        headers: { "Content-Length": "5" },
        body: "12345",
      },
    );
    await expect(readBoundedRequestBody(declared, 4)).rejects.toBeInstanceOf(
      RequestBodyTooLargeError,
    );

    const streamed = new Request(
      "https://app.nutrilens.test/api/backend/profile",
      {
        method: "POST",
        body: new ReadableStream({
          start(controller) {
            controller.enqueue(new Uint8Array([1, 2, 3]));
            controller.enqueue(new Uint8Array([4, 5]));
            controller.close();
          },
        }),
        duplex: "half",
      } as RequestInit & { duplex: "half" },
    );
    await expect(readBoundedRequestBody(streamed, 4)).rejects.toBeInstanceOf(
      RequestBodyTooLargeError,
    );
  });
});
