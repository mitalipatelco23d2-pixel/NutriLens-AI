# Web client inference research checkpoint

Status: capability gate implemented; local OCR provider unselected; custom ONNX
distribution blocked; server fallback required.

## What is safe now

The browser can detect, without uploading an image:

- secure-context status
- a usable WebGPU adapter, rather than only the presence of `navigator.gpu`
- WebAssembly availability
- whether cross-origin isolation and `SharedArrayBuffer` make WASM threading
  eligible
- bounded hardware concurrency/device-memory hints

The detector fails closed to `WASM_CANDIDATE` or `SERVER_ONLY` when WebGPU is
absent, insecure, denied, or returns no adapter. This is capability discovery,
not an inference-quality decision. The custom detector remains explicitly
`BLOCKED_LICENSE_AND_IP_REVIEW`, and every result keeps
`serverFallbackRequired: true`.

## Runtime research result

ONNX Runtime Web officially supports browser WebGPU and WASM execution
providers. WebGPU requires a secure context and a real adapter, and operator
coverage differs by execution provider. Its deployment also requires runtime
WASM/worker assets and a model asset. The latter is the decisive hard gate for
NutriLens: the custom ONNX file must not be added to `public/`, a CDN, a browser
cache, or the JavaScript dependency graph until model distribution is cleared.

Google's ML Kit Text Recognition v2 documentation exposes native Android and
iOS SDK paths, not a web SDK equivalent. Tesseract.js can run OCR in a browser
through WebAssembly, but that fact alone is not a quality result. NutriLens will
not add it to the product until the same nutrition-label fixture matrix proves
useful R3/R4 structure, allergen preservation, latency, memory, and fallback
behavior.

## Next evidence gate

1. Keep the current web scan as an owner-scoped durable server fallback.
2. Do not install ONNX Runtime Web merely for capability detection.
3. If detector distribution is later cleared, benchmark WebGPU first and WASM
   fallback with the existing ONNX parity artifact; never force WebGPU.
4. Evaluate any browser OCR candidate offline against the milk, beverage,
   snack, cereal, ingredient-heavy, rotated, and blurry fixtures before wiring
   it into the authenticated scan path.
5. Accept web evidence only under a separately allowlisted provider/version and
   source-image binding; Android provenance must not be reused for web.

## Sources reviewed

- [ONNX Runtime Web overview](https://onnxruntime.ai/docs/tutorials/web/)
- [ONNX Runtime Web deployment and security](https://onnxruntime.ai/docs/tutorials/web/deploy.html)
- [ONNX Runtime WebGPU execution provider](https://onnxruntime.ai/docs/tutorials/web/ep-webgpu.html)
- [Google ML Kit Text Recognition v2](https://developers.google.com/ml-kit/vision/text-recognition/v2)
- [Tesseract.js project](https://github.com/naptha/tesseract.js/)
- [MDN WebGPU API](https://developer.mozilla.org/en-US/docs/Web/API/WebGPU_API)
