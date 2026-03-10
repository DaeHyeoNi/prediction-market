아래 문서를 참고하여서 지금 구현에 문제가 없는지 확인하고
호가가 선택하는 포지션에 따라서 오더북이 반전되어 보여야하고
그리고 나는 팔 수 있는 수량이 없는데 Sell Order가 보이는게 이상해


# Prediction Market API

Base URL: `http://localhost:8000`

## 인증

로그인 후 발급된 토큰을 모든 인증 필요 요청에 포함합니다.

```
Authorization: Bearer <access_token>
```

토큰 유효시간: 30분

---

## Enum 값 참조

| 타입 | 값 |
|------|----|
| `MarketStatus` | `OPEN` \| `CLOSED` \| `RESOLVED` |
| `MarketResult` | `YES` \| `NO` |
| `PositionSide` | `YES` \| `NO` |
| `OrderType` | `Bid` \| `Ask` |
| `OrderStatus` | `Pending` \| `Open` \| `Partial` \| `Filled` \| `Cancelled` |

---

## Users

### POST /users/register

회원가입. 초기 포인트 1,000,000 지급.

**Request**
```json
{
  "username": "alice",
  "password": "secret123"
}
```

**Response** `201 Created`
```json
{
  "id": 1,
  "username": "alice",
  "total_points": 1000000,
  "available_points": 1000000
}
```

**Errors**
- `400` — 이미 존재하는 username

---

### POST /users/login

로그인. `application/x-www-form-urlencoded` 형식으로 전송.

**Request** (form-encoded)
```
username=alice&password=secret123
```

**Response** `200 OK`
```json
{
  "access_token": "eyJhbGci...",
  "token_type": "bearer"
}
```

**Errors**
- `401` — 잘못된 인증 정보

---

### GET /users/me

내 계정 정보 조회.

**Auth** 필요

**Response** `200 OK`
```json
{
  "id": 1,
  "username": "alice",
  "total_points": 1000000,
  "available_points": 950000
}
```

> `total_points`: 실제 보유 포인트 (체결 시 차감)
> `available_points`: 즉시 사용 가능한 포인트 (BID 주문 시 선차감)

---

## Markets

### GET /markets

마켓 목록 조회.

**Query Parameters**

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `status` | `MarketStatus` | — | 상태 필터 (선택) |
| `offset` | int | `0` | 페이지 오프셋 |
| `limit` | int | `20` | 페이지 크기 (최대 100) |

**Response** `200 OK`
```json
[
  {
    "id": 1,
    "title": "Will BTC exceed $100k by end of 2025?",
    "description": "Based on Binance spot price at 23:59 UTC on Dec 31, 2025.",
    "closes_at": "2025-12-31T23:59:00Z",
    "status": "OPEN",
    "result": null,
    "created_by": 1,
    "created_at": "2025-01-01T00:00:00Z",
    "resolved_at": null
  }
]
```

---

### POST /markets

새 마켓 생성.

**Auth** 필요

**Request**
```json
{
  "title": "Will BTC exceed $100k by end of 2025?",
  "description": "Based on Binance spot price at 23:59 UTC on Dec 31, 2025.",
  "closes_at": "2025-12-31T23:59:00Z"
}
```

**Response** `201 Created`
```json
{
  "id": 1,
  "title": "Will BTC exceed $100k by end of 2025?",
  "description": "Based on Binance spot price at 23:59 UTC on Dec 31, 2025.",
  "closes_at": "2025-12-31T23:59:00Z",
  "status": "OPEN",
  "result": null,
  "created_by": 1,
  "created_at": "2025-01-01T00:00:00Z",
  "resolved_at": null
}
```

---

### GET /markets/{market_id}

마켓 단건 조회.

**Response** `200 OK` — [MarketResponse](#post-markets) 동일 구조

**Errors**
- `404` — 마켓 없음

---

### GET /markets/{market_id}/orderbook

호가창 조회. YES/NO가 `YES_PRICE + NO_PRICE = 100` 관계로 통합된 단일 뷰.

> YES BID + NO ASK 미러 주문이 합산됩니다. 예: NO ASK(30) → YES BID(70)으로 표시

**Response** `200 OK`
```json
{
  "market_id": 1,
  "yes_bids": [
    { "price": 72, "quantity": 50 },
    { "price": 70, "quantity": 100 }
  ],
  "yes_asks": [
    { "price": 75, "quantity": 30 },
    { "price": 80, "quantity": 20 }
  ]
}
```

> `yes_bids`: 높은 가격순 정렬
> `yes_asks`: 낮은 가격순 정렬

---

### GET /markets/{market_id}/trades

체결 내역 조회. 최신순.

**Query Parameters**

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `offset` | int | `0` | 페이지 오프셋 |
| `limit` | int | `50` | 페이지 크기 (최대 200) |

**Response** `200 OK`
```json
[
  {
    "id": 101,
    "market_id": 1,
    "maker_order_id": 5,
    "taker_order_id": 9,
    "position": "YES",
    "price": 70,
    "quantity": 10,
    "created_at": "2025-06-01T12:00:00Z"
  }
]
```

> `position`, `price`는 taker 기준입니다.

---

## Orders

### POST /orders

주문 제출. 비동기 처리 (`202 Accepted` 즉시 반환, 실제 체결은 큐 워커가 처리).

**Auth** 필요

**Request**
```json
{
  "market_id": 1,
  "position": "YES",
  "order_type": "Bid",
  "price": 70,
  "quantity": 10
}
```

| 필드 | 타입 | 제약 |
|------|------|------|
| `market_id` | int | OPEN 상태 마켓만 가능 |
| `position` | `PositionSide` | `YES` \| `NO` |
| `order_type` | `OrderType` | `Bid` \| `Ask` |
| `price` | int | 1–99 |
| `quantity` | int | 양수 |

**Response** `202 Accepted`
```json
{
  "id": 42,
  "user_id": 1,
  "market_id": 1,
  "position": "YES",
  "order_type": "Bid",
  "price": 70,
  "quantity": 10,
  "remaining_quantity": 10,
  "status": "Open",
  "locked_points": 700,
  "created_at": "2025-06-01T12:00:00Z",
  "updated_at": "2025-06-01T12:00:00Z"
}
```

**Errors**
- `400` — 마켓이 OPEN 상태가 아님
- `400` — 마켓 종료 시각 초과
- `400` — BID 주문 시 `available_points` 부족 (`price × quantity`)
- `400` — ASK 주문 시 보유 포지션 수량 부족 (공매도 불가)
- `404` — 마켓 없음

> **BID 주문**: 제출 즉시 `price × quantity` 포인트가 `available_points`에서 선차감됩니다.
> **ASK 주문**: 해당 포지션을 실제 보유하고 있어야 합니다.

---

### GET /orders

내 주문 목록 조회. 최신순, 최대 100건.

**Auth** 필요

**Response** `200 OK` — [OrderResponse](#post-orders) 배열

---

### DELETE /orders/{order_id}

주문 취소. 큐를 통해 처리되므로 즉시 취소되지 않을 수 있습니다.

**Auth** 필요

**Response** `204 No Content`

**Errors**
- `400` — 취소 불가 상태 (`Filled`, `Cancelled`)
- `404` — 주문 없음 또는 타인 주문

> BID 주문 취소 시 `locked_points`가 `available_points`로 반환됩니다.

---

## Positions

### GET /positions

내 보유 포지션 목록 조회. `quantity > 0`인 항목만 반환.

**Auth** 필요

**Response** `200 OK`
```json
[
  {
    "id": 7,
    "user_id": 1,
    "market_id": 1,
    "position": "YES",
    "quantity": 15,
    "avg_price": 68
  }
]
```

> `avg_price`: 매수 체결가의 가중평균. 매도 시 변경되지 않습니다.

---

## Admin

### POST /admin/markets/{market_id}/resolve

마켓 결과 확정. Celery `settle_market` 태스크를 비동기로 실행합니다.

**Auth** 필요

**Request**
```json
{
  "result": "YES"
}
```

**Response** `200 OK`
```json
{
  "message": "Settlement initiated",
  "market_id": 1
}
```

**Errors**
- `400` — 이미 RESOLVED된 마켓
- `404` — 마켓 없음

> 정산 처리: 승리 포지션 보유자에게 `quantity × 100` 포인트 지급. 잔여 주문 일괄 취소. 500건 단위 청크로 처리되며 멱등성을 보장합니다.

---

## 포인트 흐름 요약

| 이벤트 | `total_points` | `available_points` |
|--------|---------------|-------------------|
| BID 주문 제출 | 변동 없음 | `- price × qty` |
| BID 체결 | `- trade_price × fill` | `+ (bid_price - trade_price) × fill` (초과분 환급) |
| ASK 체결 | `+ trade_price × fill` | `+ trade_price × fill` |
| 주문 취소 | 변동 없음 | `+ locked_points` 반환 |
| 마켓 정산 (승리) | `+ quantity × 100` | `+ quantity × 100` |
