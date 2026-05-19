# getSpons — Frontend Setup & Backend Connection Guide

## Your Complete File Structure

```
GetSpons-main/
├── backend/              ← your existing FastAPI code (don't touch)
│   ├── main.py
│   ├── auth.py
│   ├── profile.py
│   ├── brands.py
│   ├── pitch.py
│   ├── mediakit.py
│   └── ai.py
├── templates/
│   └── mediakit.html
│
└── frontend/             ← NEW: create this folder
    ├── index.html        ← Landing page
    ├── signup.html       ← Sign up
    ├── login.html        ← Log in
    ├── profile.html      ← Profile setup
    ├── dashboard.html    ← Dashboard
    ├── brands.html       ← Find brands
    ├── pitches.html      ← My pitches tracker
    ├── css/
    │   └── shared.css    ← Design tokens & reusable styles
    └── js/
        └── api.js        ← ALL fetch() calls to FastAPI
```

---

## Step 1 — Fix CORS (Critical)

Your FastAPI only allows `http://localhost:3000`. Since your frontend
HTML files run from the filesystem (or a different port), open
`backend/main.py` and update the CORS middleware:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5500",    # VS Code Live Server default
        "http://127.0.0.1:5500",
        "http://localhost:8080",    # another common dev port
        "null",                    # for opening HTML files directly
        "https://*.vercel.app",
        "https://yourdomain.com",  # add your real domain here when deploying
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## Step 2 — Set up your .env file

Copy `.env.example` to `.env` and fill in your values:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key-here
SUPABASE_SERVICE_KEY=your-service-role-key-here
ANTHROPIC_API_KEY=your-key-here          # optional for now (MOCK_AI=true by default)
RESEND_API_KEY=your-key-here             # optional
MOCK_AI=true                             # keep this true during development
```

---

## Step 3 — Start the backend

```bash
# Navigate to backend folder
cd GetSpons-main/backend

# Install dependencies (first time only)
pip install fastapi uvicorn supabase python-dotenv anthropic weasyprint

# Start the server
uvicorn main:app --reload --port 8000
```

Test it's running: open http://localhost:8000/health in your browser.
You should see: `{"status": "ok"}`

---

## Step 4 — Serve the frontend

**Option A — VS Code Live Server (recommended for beginners)**
1. Install the "Live Server" extension in VS Code
2. Right-click `frontend/index.html` → "Open with Live Server"
3. It opens at http://127.0.0.1:5500

**Option B — Python simple server**
```bash
cd frontend
python -m http.server 5500
# Open http://localhost:5500
```

---

## Step 5 — Update the API base URL

Open `frontend/js/api.js` and make sure this line matches your backend:

```javascript
export const BASE_URL = "http://localhost:8000";
```

If you change the backend port, update this. When deploying, change it to
your production URL (e.g. `https://getspons.onrender.com`).

---

## How Every Page Connects to the Backend

| Page | API Call Made | Backend Endpoint |
|------|--------------|-----------------|
| signup.html | `API.signup(email, pass)` | POST /api/auth/signup |
| login.html | `API.login(email, pass)` | POST /api/auth/login |
| profile.html | `API.getProfile()` + `API.saveProfile(data)` | GET + POST /api/profile/me, /save |
| dashboard.html | `API.getProfile()` | GET /api/profile/me |
| dashboard.html | `API.generateMediaKit()` | POST /api/mediakit/generate |
| dashboard.html | `API.downloadMediaKitPDF()` | POST /api/mediakit/pdf |
| dashboard.html | `API.getMyPitches()` | GET /api/pitches/mine |
| brands.html | `API.getBrands({niche})` | GET /api/brands/ |
| brands.html | `API.generatePitch(brandId)` | POST /api/pitches/generate |
| pitches.html | `API.getMyPitches()` | GET /api/pitches/mine |
| pitches.html | `API.updatePitchStatus(id, status)` | PATCH /api/pitches/{id} |

---

## How Authentication Works

1. User logs in → backend returns `{ access_token, user_id }`
2. `api.js` saves both to `localStorage` automatically
3. Every subsequent API call adds `Authorization: Bearer <token>` header
4. If token is missing → pages redirect to `login.html`
5. Logout clears localStorage and redirects to `login.html`

You don't need to manage tokens manually — `api.js` handles it all.

---

## Supabase Tables Required

Run this SQL in your Supabase SQL editor if not already done:

```sql
-- Profiles table
CREATE TABLE profiles (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid REFERENCES auth.users(id) ON DELETE CASCADE,
  full_name text,
  platform text,
  handle text,
  followers integer,
  niche text,
  engagement_rate float,
  bio text,
  past_sponsors text[],
  pricing_min integer,
  pricing_max integer,
  is_pro boolean DEFAULT false,
  UNIQUE(user_id)
);

-- Brands table (add your brands here or via Supabase UI)
CREATE TABLE brands (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  name text NOT NULL,
  niche text,
  min_followers integer DEFAULT 0,
  max_followers integer,
  contact_email text,
  website text,
  country text DEFAULT 'India',
  active boolean DEFAULT true
);

-- Pitches table
CREATE TABLE pitches (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid REFERENCES auth.users(id) ON DELETE CASCADE,
  brand_id uuid REFERENCES brands(id),
  subject text,
  body text,
  status text DEFAULT 'draft',
  created_at timestamptz DEFAULT now()
);

-- RLS Policies
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE brands   ENABLE ROW LEVEL SECURITY;
ALTER TABLE pitches  ENABLE ROW LEVEL SECURITY;

-- Profiles: users see only their own
CREATE POLICY "own profile" ON profiles FOR ALL USING (auth.uid() = user_id);

-- Brands: everyone can read (no write from frontend)
CREATE POLICY "public read brands" ON brands FOR SELECT USING (true);

-- Pitches: users see only their own
CREATE POLICY "own pitches" ON pitches FOR ALL USING (auth.uid() = user_id);
```

---

## Deployment (When Ready)

**Backend → Render.com**
1. Push your code to GitHub
2. New Web Service on Render → connect repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
5. Add all `.env` variables in Render's Environment tab

**Frontend → Vercel / Netlify**
1. Drag & drop your `frontend/` folder to Netlify, OR
2. Push to GitHub and connect to Vercel
3. Update `BASE_URL` in `api.js` to your Render backend URL before deploying

---

## Common Errors & Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `CORS error` in browser console | Frontend origin not in CORS list | Add your port to `allow_origins` in main.py |
| `401 Unauthorized` | Token expired or missing | Log out and log back in |
| `404 profile not found` | Profile not saved yet | Go to profile.html and fill in the form |
| `500 PDF rendering failed` | WeasyPrint missing GTK | `pip install weasyprint` + install GTK3 on your OS |
| `Module not found` error in JS | Browser can't load ES modules from `file://` | Use Live Server instead of opening HTML directly |
