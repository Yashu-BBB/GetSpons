from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from database import supabase, supabase_admin

router = APIRouter()

class ProfileInput(BaseModel):
    full_name: str
    platform: str
    handle: str
    followers: int
    niche: str
    engagement_rate: float
    bio: str
    past_sponsors: Optional[List[str]] = []
    pricing_min: int
    pricing_max: int

@router.post("/save")
def save_profile(data: ProfileInput, authorization: str = Header(...)):
    try:
        token = authorization.replace("Bearer ", "")
        user = supabase.auth.get_user(token)
        user_id = user.user.id

        supabase_admin.table("profiles").upsert({
            "user_id": user_id,
            **data.model_dump()
        }).execute()

        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/me")
def get_profile(authorization: str = Header(...)):
    try:
        token = authorization.replace("Bearer ", "")
        user = supabase_admin.auth.get_user(token)
        user_id = user.user.id

        res = supabase_admin.table("profiles").select("*").eq("user_id", user_id).single().execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))