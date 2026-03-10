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


class UserMeResponse(BaseModel):
    id: int
    username: str
    total_points: int
    available_points: int
    locked_points: int        # 미체결 BID에 묶인 포인트 (= total - available)
    portfolio_value: int      # 보유 포지션의 현재 시장가 합계
    total_wealth: int         # total_points + portfolio_value

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str
