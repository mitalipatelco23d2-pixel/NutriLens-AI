export const WEB_CLIENT_INFERENCE_CONTRACT_VERSION = "1.0.0" as const;

export type BrowserExecutionCandidate =
  | "WEBGPU_CANDIDATE"
  | "WASM_CANDIDATE"
  | "SERVER_ONLY";

export type BrowserInferenceCapabilities = {
  clientInferenceContractVersion: typeof WEB_CLIENT_INFERENCE_CONTRACT_VERSION;
  platform: "WEB";
  secureContext: boolean;
  webgpuApiPresent: boolean;
  webgpuAdapterAvailable: boolean;
  wasmAvailable: boolean;
  wasmThreadsEligible: boolean;
  crossOriginIsolated: boolean;
  hardwareConcurrency: number | null;
  deviceMemoryGiB: number | null;
  preferredExecutionCandidate: BrowserExecutionCandidate;
  localOcrStatus: "UNSELECTED_QUALITY_GATE";
  customDetectorStatus: "BLOCKED_LICENSE_AND_IP_REVIEW";
  serverFallbackRequired: true;
};

export type BrowserCapabilityEnvironment = {
  secureContext: boolean;
  crossOriginIsolated: boolean;
  webAssemblyAvailable: boolean;
  sharedArrayBufferAvailable: boolean;
  hardwareConcurrency?: number;
  deviceMemoryGiB?: number;
  requestWebGpuAdapter?: () => Promise<unknown | null>;
};

function finitePositive(value: number | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? value
    : null;
}

export async function detectBrowserInferenceCapabilities(
  environment: BrowserCapabilityEnvironment,
): Promise<BrowserInferenceCapabilities> {
  const webgpuApiPresent = environment.requestWebGpuAdapter !== undefined;
  let webgpuAdapterAvailable = false;
  if (environment.secureContext && environment.requestWebGpuAdapter) {
    try {
      webgpuAdapterAvailable =
        (await environment.requestWebGpuAdapter()) !== null;
    } catch {
      webgpuAdapterAvailable = false;
    }
  }
  const wasmAvailable = environment.webAssemblyAvailable;
  const wasmThreadsEligible =
    wasmAvailable &&
    environment.secureContext &&
    environment.crossOriginIsolated &&
    environment.sharedArrayBufferAvailable;
  const preferredExecutionCandidate: BrowserExecutionCandidate =
    webgpuAdapterAvailable
      ? "WEBGPU_CANDIDATE"
      : wasmAvailable
        ? "WASM_CANDIDATE"
        : "SERVER_ONLY";

  return {
    clientInferenceContractVersion: WEB_CLIENT_INFERENCE_CONTRACT_VERSION,
    platform: "WEB",
    secureContext: environment.secureContext,
    webgpuApiPresent,
    webgpuAdapterAvailable,
    wasmAvailable,
    wasmThreadsEligible,
    crossOriginIsolated: environment.crossOriginIsolated,
    hardwareConcurrency: finitePositive(environment.hardwareConcurrency),
    deviceMemoryGiB: finitePositive(environment.deviceMemoryGiB),
    preferredExecutionCandidate,
    localOcrStatus: "UNSELECTED_QUALITY_GATE",
    customDetectorStatus: "BLOCKED_LICENSE_AND_IP_REVIEW",
    serverFallbackRequired: true,
  };
}

type NavigatorWithOptionalInference = Navigator & {
  deviceMemory?: number;
  gpu?: { requestAdapter: () => Promise<unknown | null> };
};

export async function detectCurrentBrowserInferenceCapabilities(): Promise<BrowserInferenceCapabilities> {
  const currentNavigator = navigator as NavigatorWithOptionalInference;
  return detectBrowserInferenceCapabilities({
    secureContext: window.isSecureContext,
    crossOriginIsolated: window.crossOriginIsolated,
    webAssemblyAvailable: typeof WebAssembly === "object",
    sharedArrayBufferAvailable: typeof SharedArrayBuffer === "function",
    hardwareConcurrency: currentNavigator.hardwareConcurrency,
    deviceMemoryGiB: currentNavigator.deviceMemory,
    requestWebGpuAdapter: currentNavigator.gpu
      ? () => currentNavigator.gpu!.requestAdapter()
      : undefined,
  });
}
