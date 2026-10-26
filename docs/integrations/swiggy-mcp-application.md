# Swiggy Instamart Model Context Protocol (MCP) Integration Application Document

## 1. Applicant & Entity Identification
- **Company / Entity**: Yash AI Technologies
- **Application / Product**: NutriLens X (Android & Web)
- **Primary Business Focus**: Personal nutrition intelligence platform helping consumers understand packaged food nutrition facts, identify food allergens, evaluate dietary choices, and manage pantry/grocery workflows.

---

## 2. Integration Purpose & User Value
NutriLens X integrates with Swiggy Instamart via the official Model Context Protocol (MCP) to bridge nutritional understanding and grocery fulfillment:
- **Low-Stock Pantry Replenishment**: When a user's inventory falls below their self-configured threshold, NutriLens generates a grocery shortfall list.
- **Recipe Deficit Resolution**: When planning a meal or recipe, missing ingredients can be searched on Instamart.
- **User-Directed Cart Sync**: After reviewing search results and explicit confirmation by the user, selected items are added directly to the authenticated user's Instamart cart.
- **Non-Autonomous Guardrail**: NutriLens X never places orders, never initiates automated payments, and never modifies user carts without direct, explicit interactive user initiation. Final checkout and payment occur exclusively within the official Swiggy application or checkout interface.

---

## 3. Architecture & Security Model
```
[NutriLens Android App / Web Client]
               │
               ▼  (TLS HTTPS / NutriLens Session JWT)
[NutriLens Backend API Service]
               │
               ▼  (Swiggy OAuth 2.0 Bearer / X-Swiggy-Client-ID)
[Official Swiggy Instamart MCP Endpoint: https://mcp.swiggy.com/im]
               │
               ▼
[Swiggy Instamart Inventory & Cart Service]
```

- **Client-Side Secret Isolation**: No Swiggy client secrets, access tokens, or refresh tokens are ever sent to, stored on, or accessible from client devices or mobile APKs.
- **Server-Side Token Custody**: OAuth tokens and credentials reside solely within secured backend environment stores.
- **Protocol Conformance**: Implementation strictly adheres to official Swiggy MCP JSON-RPC 2.0 methods:
  - `get_addresses`: Retrieves user-approved delivery addresses for store availability lookup.
  - `search_products`: Searches real-time catalog items matching user shortfall queries.
  - `get_cart`: Reads user's current Instamart cart state.
  - `update_cart`: Adds selected SKU/spin items and quantities upon user confirmation.

---

## 4. Redirect URIs & Endpoints
- **Proposed Production OAuth Callback**: `https://api.nutrilens.ai/api/v1/instamart/oauth/callback`
- **Proposed Development / Local QA Callback**: `http://127.0.0.1:8000/api/v1/instamart/oauth/callback`
*(Note: Final production redirect URI to be governed by primary deployment domain).*

---

## 5. Network Egress & Infrastructure Truth
- **Current Infrastructure**: Cloud-hosted backend (Render / OCI / local development host).
- **Static IP / Gateway**: NutriLens backend currently utilizes dynamic IP assignment with standard HTTPS egress. If Swiggy requires a strictly whitelisted static outbound CIDR/IP, an outbound proxy gateway (e.g., AWS NAT Gateway or dedicated static egress proxy) will be designated upon application progression.

---

## 6. Security Contact & Administrative Ownership
- **Owner / Technical Contact**: Yash Baid (NutriLens Lead / Yash AI Technologies)
- **Primary Support / Contact Email**: `yash07@gmail.com` (or official project contact `support@nutrilensx.tech`)

---

## 7. Data Handling & Privacy Guarantees
- **Minimal Data Retrieval**: The integration accesses only delivery address labels (for store mapping), product catalog metadata, and cart item IDs.
- **No Financial / Card Data**: NutriLens never requests, intercepts, or stores payment credentials, UPI details, credit card numbers, or billing instruments.
- **No Data Resale / Redistribution**: Swiggy catalog items and pricing data are used exclusively for real-time display within user search sessions and are never scraped, aggregated for resale, or shared with third parties.
- **Compliance Attestation**: NutriLens does not make unsubstantiated claims of SOC2 or ISO certifications. Infrastructure employs TLS 1.3 encryption in transit and AES-256 encryption at rest.

---

## 8. Expected Traffic & Volume Estimates
- **Initial College Demo & Pilot Phase**: ~50–100 active test users; < 500 catalog queries/day; < 100 cart updates/day.
- **Early Consumer Rollout (Estimated)**: ~2,000–5,000 active users; ~10,000 queries/day.
*(Note: These figures represent early-stage projections, not historical traffic).*

---

## 9. Next Steps / Owner Action Checklist
- [ ] Submit developer partner request to Swiggy Developers / Builders Club (`https://mcp.swiggy.com`).
- [ ] Agree to Swiggy Developer Terms of Service upon invitation.
- [ ] Receive official `SWIGGY_CLIENT_ID` and `SWIGGY_CLIENT_SECRET`.
- [ ] Configure secrets in server environment to transition Instamart from `PENDING_SWIGGY_APPROVAL` to `READY`.
