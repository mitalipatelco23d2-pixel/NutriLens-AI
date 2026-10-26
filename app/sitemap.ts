import type { MetadataRoute } from "next";

const publicPaths = [
  "",
  "/about",
  "/pricing",
  "/privacy",
  "/terms",
  "/shipping",
  "/refunds",
  "/contact",
] as const;

export default function sitemap(): MetadataRoute.Sitemap {
  const origin = (
    process.env.PUBLIC_WEBSITE_URL ?? "http://localhost:3000"
  ).replace(/\/$/, "");
  return publicPaths.map((path, index) => ({
    url: `${origin}${path}`,
    changeFrequency: index === 0 ? "weekly" : "monthly",
    priority: index === 0 ? 1 : 0.7,
  }));
}
