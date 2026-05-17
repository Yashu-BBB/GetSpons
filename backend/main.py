from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from auth import router as auth_router
from profile import router as profile_router
from mediakit import router as mediakit_router
from brands import router as brands_router
from pitch import router as pitch_router

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://*.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/auth")
app.include_router(profile_router, prefix="/api/profile")
app.include_router(mediakit_router, prefix="/api/mediakit")
app.include_router(brands_router, prefix="/api/brands")
app.include_router(pitch_router, prefix="/api/pitches")

@app.get("/health")
def health():
    return {"status": "ok"}