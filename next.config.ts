import type { NextConfig } from "next";

const publicApiUrl =
  process.env.PUBLIC_API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output:
    process.env.NEXT_OUTPUT_MODE === "standalone" ? "standalone" : undefined,
  outputFileTracingRoot: process.cwd(),
  async headers() {
    const securityHeaders = [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      { key: "X-Frame-Options", value: "DENY" },
      {
        key: "Permissions-Policy",
        value: "camera=(self), microphone=(), geolocation=()",
      },
      {
        key: "Content-Security-Policy",
        value: [
          "default-src 'self'",
          "base-uri 'self'",
          "object-src 'none'",
          "frame-ancestors 'none'",
          "form-action 'self'",
          "img-src 'self' data: blob: https://lh3.googleusercontent.com",
          "script-src 'self' 'unsafe-inline' https://accounts.google.com https://checkout.razorpay.com",
          "style-src 'self' 'unsafe-inline' https://accounts.google.com",
          "frame-src https://accounts.google.com https://api.razorpay.com https://checkout.razorpay.com",
          `connect-src 'self' ${publicApiUrl} https://accounts.google.com https://api.razorpay.com https://checkout.razorpay.com`,
        ].join("; "),
      },
    ];
    return [{ source: "/(.*)", headers: securityHeaders }];
  },
};

export default nextConfig;
