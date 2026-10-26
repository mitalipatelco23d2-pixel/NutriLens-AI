import { describe, expect, it } from "vitest";

import { detectBrowserInferenceCapabilities } from "./browser-inference-capabilities";

describe("browser inference capability gate", () => {
  it("selects WebGPU only in a secure context with a real adapter", async () => {
    const capabilities = await detectBrowserInferenceCapabilities({
      secureContext: true,
      crossOriginIsolated: true,
      webAssemblyAvailable: true,
      sharedArrayBufferAvailable: true,
      hardwareConcurrency: 8,
      deviceMemoryGiB: 8,
      requestWebGpuAdapter: async () => ({ name: "test adapter" }),
    });

    expect(capabilities.preferredExecutionCandidate).toBe(
      "WEBGPU_CANDIDATE",
    );
    expect(capabilities.webgpuAdapterAvailable).toBe(true);
    expect(capabilities.wasmThreadsEligible).toBe(true);
    expect(capabilities.customDetectorStatus).toBe(
      "BLOCKED_LICENSE_AND_IP_REVIEW",
    );
    expect(capabilities.serverFallbackRequired).toBe(true);
  });

  it("falls back to WASM without requesting WebGPU in an insecure context", async () => {
    let adapterRequests = 0;
    const capabilities = await detectBrowserInferenceCapabilities({
      secureContext: false,
      crossOriginIsolated: false,
      webAssemblyAvailable: true,
      sharedArrayBufferAvailable: true,
      requestWebGpuAdapter: async () => {
        adapterRequests += 1;
        return {};
      },
    });

    expect(adapterRequests).toBe(0);
    expect(capabilities.webgpuApiPresent).toBe(true);
    expect(capabilities.webgpuAdapterAvailable).toBe(false);
    expect(capabilities.preferredExecutionCandidate).toBe("WASM_CANDIDATE");
    expect(capabilities.wasmThreadsEligible).toBe(false);
  });

  it("fails closed to server-only when local runtimes are absent", async () => {
    const capabilities = await detectBrowserInferenceCapabilities({
      secureContext: true,
      crossOriginIsolated: false,
      webAssemblyAvailable: false,
      sharedArrayBufferAvailable: false,
      hardwareConcurrency: Number.NaN,
      deviceMemoryGiB: 0,
      requestWebGpuAdapter: async () => null,
    });

    expect(capabilities.preferredExecutionCandidate).toBe("SERVER_ONLY");
    expect(capabilities.hardwareConcurrency).toBeNull();
    expect(capabilities.deviceMemoryGiB).toBeNull();
    expect(capabilities.localOcrStatus).toBe("UNSELECTED_QUALITY_GATE");
  });

  it("treats adapter errors as unavailable instead of breaking scans", async () => {
    const capabilities = await detectBrowserInferenceCapabilities({
      secureContext: true,
      crossOriginIsolated: true,
      webAssemblyAvailable: true,
      sharedArrayBufferAvailable: true,
      requestWebGpuAdapter: async () => {
        throw new Error("adapter unavailable");
      },
    });

    expect(capabilities.webgpuAdapterAvailable).toBe(false);
    expect(capabilities.preferredExecutionCandidate).toBe("WASM_CANDIDATE");
  });
});
