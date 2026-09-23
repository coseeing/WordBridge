from fastapi import APIRouter

# Password/HS256 login ("/login", "/register") is no longer provided -- SSO
# dependencies (app/user/auth.py) authorize requests instead. This router is
# kept as an empty APIRouter so any future user-facing routes have a home;
# nothing is included from it today (see app/main.py).
router = APIRouter()
