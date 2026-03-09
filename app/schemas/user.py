from pydantic import BaseModel


class UserRegister(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    total_points: int
    available_points: int

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str
