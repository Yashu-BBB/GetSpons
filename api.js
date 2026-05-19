/**
 * api.js — All fetch() calls to the FastAPI backend in one place.
 *
 * HOW TO USE:
 *   import { API } from './js/api.js';
 *   const result = await API.login('you@email.com', 'password');
 *
 * BASE_URL points to your local FastAPI server.
 * When you deploy, change it to your live URL (Render / Railway).
 */

export const BASE_URL = "http://localhost:8000"; // ← change this when deploying

// ─── Token helpers ───────────────────────────────────────────────────────────
// We store the JWT in localStorage so the user stays logged in across pages.

export function saveToken(token) {
  localStorage.setItem("gs_token", token);
}

export function getToken() {
  return localStorage.getItem("gs_token");
}

export function clearToken() {
  localStorage.removeItem("gs_token");
  localStorage.removeItem("gs_user_id");
}

export function saveUserId(id) {
  localStorage.setItem("gs_user_id", id);
}

export function getUserId() {
  return localStorage.getItem("gs_user_id");
}

// Returns the Authorization header object if a token exists.
function authHeader() {
  const token = getToken();
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
}

// ─── Generic fetch wrapper ────────────────────────────────────────────────────
// Handles JSON parsing and surfaces error messages consistently.

async function request(method, path, body = null, extraHeaders = {}) {
  const options = {
    method,
    headers: {
      "Content-Type": "application/json",
      ...authHeader(),
      ...extraHeaders,
    },
  };
  if (body) options.body = JSON.stringify(body);

  const res = await fetch(`${BASE_URL}${path}`, options);

  // PDF endpoint returns binary, not JSON
  if (res.headers.get("Content-Type")?.includes("application/pdf")) {
    const blob = await res.blob();
    return { ok: res.ok, blob };
  }

  const data = await res.json();
  if (!res.ok) {
    // FastAPI wraps errors in { detail: "..." }
    throw new Error(data.detail || JSON.stringify(data));
  }
  return data;
}

// ─── Auth ─────────────────────────────────────────────────────────────────────

export const API = {

  async signup(email, password) {
    // POST /api/auth/signup
    // Returns: { success: true, user_id: "..." }
    return request("POST", "/api/auth/signup", { email, password });
  },

  async login(email, password) {
    // POST /api/auth/login
    // Returns: { access_token: "...", user_id: "..." }
    const data = await request("POST", "/api/auth/login", { email, password });
    if (data.access_token) {
      saveToken(data.access_token);
      saveUserId(data.user_id);
    }
    return data;
  },

  logout() {
    clearToken();
    window.location.href = "/login.html";
  },

  // ─── Profile ───────────────────────────────────────────────────────────────

  async getProfile() {
    // GET /api/profile/me  (requires Authorization header)
    // Returns the full profile row from Supabase
    return request("GET", "/api/profile/me");
  },

  async saveProfile(profileData) {
    // POST /api/profile/save  (requires Authorization header)
    // profileData shape: { full_name, platform, handle, followers,
    //                      niche, engagement_rate, bio,
    //                      past_sponsors[], pricing_min, pricing_max }
    return request("POST", "/api/profile/save", profileData);
  },

  // ─── Media Kit ─────────────────────────────────────────────────────────────

  async generateMediaKit() {
    // POST /api/mediakit/generate  (requires Authorization header)
    // Returns AI-generated JSON: { headline, bio_short, key_stats,
    //   audience_description, content_style, why_partner,
    //   pricing_table, cta }
    return request("POST", "/api/mediakit/generate");
  },

  async downloadMediaKitPDF() {
    // POST /api/mediakit/pdf  (requires Authorization header)
    // Returns: { ok: true, blob: Blob }  ← binary PDF
    return request("POST", "/api/mediakit/pdf");
  },

  // ─── Brands ────────────────────────────────────────────────────────────────

  async getBrands(filters = {}) {
    // GET /api/brands/?niche=Beauty&min_followers=10000
    // filters: { niche?: string, min_followers?: number }
    const params = new URLSearchParams();
    if (filters.niche) params.append("niche", filters.niche);
    if (filters.min_followers) params.append("min_followers", filters.min_followers);
    const qs = params.toString() ? `?${params}` : "";
    return request("GET", `/api/brands/${qs}`);
  },

  async getBrand(brandId) {
    // GET /api/brands/{brand_id}
    return request("GET", `/api/brands/${brandId}`);
  },

  // ─── Pitches ───────────────────────────────────────────────────────────────

  async generatePitch(brandId) {
    // POST /api/pitches/generate  (requires Authorization header)
    // Returns: { id, subject, body, status }
    return request("POST", "/api/pitches/generate", { brand_id: brandId });
  },

  async getMyPitches() {
    // GET /api/pitches/mine  (requires Authorization header)
    // Returns: [{ id, subject, body, status, created_at, brands: { name } }]
    return request("GET", "/api/pitches/mine");
  },

  async updatePitchStatus(pitchId, status) {
    // PATCH /api/pitches/{pitch_id}
    // status: "draft" | "sent" | "replied" | "deal"
    return request("PATCH", `/api/pitches/${pitchId}`, { status });
  },
};
