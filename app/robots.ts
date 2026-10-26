import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  const origin = (
    process.env.PUBLIC_WEBSITE_URL ?? "http://localhost:3000"
  ).replace(/\/$/, "");
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: ["/account", "/admin", "/api/", "/dashboard", "/research"],
    },
    sitemap: `${origin}/sitemap.xml`,
  };
}
