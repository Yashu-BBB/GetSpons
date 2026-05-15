from fastapi import APIRouter
from pydantic import BaseModel
from database import supabase

router = APIRouter()

class AuthInput(BaseModel):
    email: str
    password: str

@router.post("/signup")
def signup(data: AuthInput):
    try:
        res = supabase.auth.sign_up({
            "email": data.email,
            "password": data.password
        })
        return {"success": True, "user_id": res.user.id}
    except Exception as e:
        return {"error": str(e)}

@router.post("/login")
def login(data: AuthInput):
    try:
        res = supabase.auth.sign_in_with_password({
            "email": data.email,
            "password": data.password
        })
        return {
            "access_token": res.session.access_token,
            "user_id": res.user.id
        }
    except Exception as e:
        return {"error": str(e)}