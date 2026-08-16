from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.api.dependencies import get_current_user
from backend.app.db.models import User
from backend.app.schemas.auth import UserResponse


router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get(
    "/me",
    response_model=UserResponse,
)
def get_me(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    return UserResponse.model_validate(current_user)
