---
type: System Design
title: 대규모 이커머스 재고 시스템
description: 수백만 SKU의 조회 폭주와 동시 주문을 처리하는 DB 조건부 예약, Redis projection, Outbox/CDC, 장애 격리·재고 대사 설계
timestamp: 2026-09-04T20:01:01+09:00
tags: [inventory, redis, concurrency, outbox, reconciliation, consistency]
books:
  - "Alex Xu 2권 7장 (호텔 예약) — 재고 예약·중복 예약 방지·동시성 제어"
  - "Alex Xu 2권 11장 (결제 시스템) — 멱등성·exactly-once 효과·대사"
  - "Alex Xu 2권 4장 (분산 메시지 큐) — 이벤트 전달·중복 처리·파티셔닝"
  - "DDIA 7장 (트랜잭션) — 격리 수준·원자성·직렬화"
  - "DDIA 11장 (스트림 처리) — CDC·파생 뷰·이벤트 재처리"
---

# 대규모 이커머스 재고 시스템

시각 자료: [문제 해체부터 전체 아키텍처까지 ELI5 그림 12장 + 대안 그림(Redis 선차감·write-behind) 1장](/wiki/assets/inventory-system/eli5-inventory-system.html) (브라우저로 열기)

> 면접의 핵심은 “Redis에서 숫자를 빨리 줄이는 법”이 아니다. **어떤 값이 판매 가능 여부를 최종 결정하고, 부분 장애·재시도·이벤트 중복에서도 어떤 불변식을 지킬 것인가**를 설명하는 문제다.

관련 설계인 [선착순 티켓 예매 시스템](/wiki/system-design/ticket-booking.md)이 한 이벤트의 순간 폭주·대기열·TTL에 집중한다면, 이 문서는 수백만 SKU의 상시 읽기와 입고·예약·출고·반품으로 이어지는 재고 수명주기에 집중한다.

시스템 디자인 전반의 강의·책·문제·사례는 공통 허브인 [시스템 디자인 면접 학습 자료](/wiki/concepts/system-design-interview-resources.md)에서 관리한다.

## 1. 요구사항과 범위

### 문제 한 줄을 바로 설계하지 말고 해체한다

면접에서 처음 받는 문장:

> “수백만 개의 상품을 관리하는 이커머스 재고 시스템을 설계해주세요.”

문장 속 명사·동사·수식어를 표시하면 첫 질문이 나온다.

| 문제의 단어 | 숨은 질문 | 설계에 미치는 영향 |
|---|---|---|
| `상품` | Product인가 SKU인가? 옵션·창고·판매자 단위인가? | 재고 키와 DB primary key 결정 |
| `관리` | 조회만인가, 예약·확정·취소·입고·반품도 포함하는가? | API와 상태 머신 결정 |
| `이커머스` | 장바구니에서 잡는가, 주문/결제 시 잡는가? | 예약 시점과 TTL 결정 |
| `수백만` | 전체/활성 SKU 수와 읽기 QPS는? | Redis working set과 DB shard 결정 |
| `재고` | 초과 판매를 절대 금지하는가? 품절 표시 지연은 허용하는가? | strong/eventual consistency 경계 결정 |

이 단계에서는 Redis·Kafka 같은 제품명을 말하지 않는다. 먼저 **무엇을 해야 하는지**, **무엇이 절대 깨지면 안 되는지**, **어디까지 늦어도 되는지**를 확정한다.

### 5분 요구사항 인터뷰

질문은 네 바구니만 기억하면 된다.

```text
① 범위      무엇을 재고로 보고 언제 확보·반환하는가?
② 규모      SKU 수, 읽기 QPS, 주문 TPS, hot SKU 집중도는?
③ 정확성    초과 판매 허용 여부와 화면 stale 허용 시간은?
④ 장애      DB/Redis 장애 때 조회와 주문을 각각 계속할 것인가?
```

이 문제에서는 면접관 답이 없을 때 다음처럼 가정하고 소리 내어 확인한다.

| 내가 물을 질문 | 이 설계에서 둘 가정 | 여기서 파생되는 요구사항 |
|---|---|---|
| 재고 단위는? | SKU별 논리 재고 풀 | Product와 SKU 분리 |
| 재고는 언제 잡나? | 주문/결제 진입 시 15분 예약 | 예약·확정·만료 상태 필요 |
| 초과 판매 가능한가? | 불가 | 주문 경로 strong consistency |
| 화면은 항상 정확해야 하나? | 수 초 stale 허용 | 조회 cache 가능 |
| 트래픽 형태는? | 읽기 50만 QPS, 쓰기 피크 5만 TPS, 일부 hot SKU | read/write 분리와 hot-key 대안 필요 |
| DB 장애에도 주문할까? | 정합성 우선, 새 주문 중단 | fail closed와 동기 복제 필요 |
| 입고·반품도 포함할까? | 포함하되 창고 배정은 확장 범위 | movement 원장 필요 |

### 기능과 비기능을 나누는 공식

- **기능 요구사항**: 사용자나 시스템이 하는 동사 — 조회한다, 예약한다, 확정한다, 반환한다, 조정한다.
- **비기능 요구사항**: 그 기능을 얼마나 잘 해야 하는지 — 빠르게, 정확하게, 동시에, 장애에도, 수백만 규모로.
- **불변식**: 어떤 장애에도 거짓이 되면 안 되는 식 — `ATP >= 0`, 같은 주문은 한 번만 차감.

문제 문장을 읽고 아래 빈칸을 먼저 채우면, 뒤의 아키텍처 박스가 자연스럽게 나온다.

```text
사용자는 __________할 수 있다.                 → 기능
피크 __________ QPS/TPS를 처리한다.             → 규모
__________은(는) 절대 깨지면 안 된다.           → 불변식
__________ 화면은 최대 __________까지 늦어도 된다. → eventual 허용 범위
__________ 장애 때 __________은 멈춘다/계속한다.   → 가용성 정책
```

### 기능 요구사항

- 수백만 개 상품의 재고를 빠르게 조회한다.
- 동시에 여러 사용자가 같은 상품을 주문해도 초과 판매하지 않는다.
- 주문 과정에서 재고를 예약하고, 주문 확정·취소·타임아웃에 따라 확정 또는 반환한다.
- 재고가 0이 되면 상품 상세·목록 화면에 빠르게 품절을 반영한다.
- 물류 입고·반품·관리자 조정으로 실재고를 변경할 수 있다.
- DB, Redis, 메시지 브로커의 부분 장애 후에도 복구·대사가 가능해야 한다.

### 비기능 요구사항

- 조회: 높은 가용성, 낮은 지연. 수 초 이내의 오래된 표시는 허용한다.
- 재고 예약: 강한 정합성. 성공했다고 응답한 주문은 반드시 재고를 확보해야 한다.
- 장애 시 정합성이 가용성보다 우선한다. 정합성을 확인할 수 없으면 새 예약을 실패시킨다(`fail closed`).
- 모든 쓰기 API와 이벤트 처리는 재시도 가능하고 멱등해야 한다.
- 특정 인기 SKU에 트래픽이 집중되는 hot-key를 별도로 다룬다.

### 먼저 용어를 바로잡기

- **Product**: 고객이 보는 상품. 예: 운동화 모델
- **SKU**: 실제 재고를 차감하는 판매 단위. 예: 검정/270mm
- **재고 풀**: `sku_id + fulfillment_node_id(창고·판매자·채널)` 단위 재고

본문은 우선 SKU당 논리 재고 풀 하나로 설명한다. 멀티 창고에서는 같은 원리를 `(sku_id, node_id)`에 적용하고, 어느 창고에서 예약할지는 별도 Allocation 단계가 결정한다.

### 재고 수식과 불변식

```text
available_to_promise(ATP) = on_hand - reserved - safety_stock
```

| 값 | 의미 |
|---|---|
| `on_hand` | 입고·출고로 변하는 장부상 실재고 |
| `reserved` | 아직 출고되지는 않았지만 주문이 확보한 수량 |
| `safety_stock` | 오차·파손·동기화 지연에 대비해 판매하지 않는 수량 |
| `ATP` | 지금 새 주문에 약속할 수 있는 수량 |

반드시 지킬 불변식:

1. `on_hand >= 0`, `reserved >= 0`, `ATP >= 0`
2. 하나의 `order_id + sku_id`는 한 번만 예약·확정·해제된다.
3. 예약 성공 응답은 DB 커밋 이후에만 보낸다.
4. Redis 값은 DB보다 오래될 수 있지만 최종 주문 성공을 결정하지 않는다.
5. 재고 변경은 원인을 추적할 수 있는 movement/예약 기록을 남긴다.

## 2. 규모 추정

다음은 설계를 구체화하기 위한 **가정**이며, 면접에서는 숫자보다 계산 방식과 병목을 밝히는 것이 중요하다.

| 항목 | 가정 | 의미 |
|---|---:|---|
| 전체 SKU | 1,000만 | DB는 전체 보관, Redis는 활성 working set 우선 |
| 일일 활성 SKU | 200만 | 캐시 크기 산정 기준 |
| 재고 조회 | 평균 10만 QPS, 피크 50만 QPS | 목록 한 화면이 여러 SKU를 조회할 수 있음 |
| 예약/해제 쓰기 | 평균 5천 TPS, 피크 5만 TPS | SKU별로 분산되지만 일부 hot SKU에 집중 |
| 예약 보관 기간 | 15분 | 결제 전 임시 확보 시간 |
| 재고 이벤트 | 쓰기 1건당 1~3개 | 캐시·검색·품절 표시의 파생 이벤트 |

- 캐시 엔트리 하나를 오버헤드 포함 150~300B로 가정하면 활성 SKU 200만 개는 약 300~600MB의 원시 추정치다. 복제·샤딩·여유 공간을 별도로 잡는다.
- 평균 QPS로만 설계하면 안 된다. 전체 쓰기량보다 **한정판 SKU 한 행에 몰리는 초당 쓰기 수**가 먼저 병목이 된다.
- 파티션 키는 기본적으로 `sku_id`다. 같은 SKU의 순서를 한 소유자에게 모을 수 있고 SKU 간 수평 확장이 가능하다.

## 3. 일관성 경계

| 경로 | 요구 일관성 | 이유 |
|---|---|---|
| 상품 목록의 `재고 있음/품절` | 결과적 일관성 | 오래된 표시는 주문 단계에서 다시 검증 가능 |
| 상품 상세의 수량·품절 | 결과적 일관성 + 짧은 지연 | UX 정보이며 판매 약속은 아님 |
| 장바구니 담기 | 결과적 일관성 | 재고를 확보하지 않음 |
| 주문/결제 진입의 재고 예약 | 강한 정합성 | 초과 판매 방지 지점 |
| 주문 취소·예약 만료 반환 | DB 상태 머신 + 멱등 처리 | 중복 반환 방지 |
| 분석·검색 인덱스 | 결과적 일관성 | 파생 데이터 |

면접에서 먼저 말할 문장:

> “화면의 재고 표시는 stale할 수 있지만, checkout에서 DB가 다시 검증합니다. 따라서 stale cache는 가끔 주문 실패를 만들 수는 있어도 초과 판매를 만들지는 못합니다.”

## 4. 최종 아키텍처

### 요구사항을 박스와 화살표로 바꾸는 5단계

완성 그림을 외우지 말고 정확성에 필요한 최소 그림부터 한 겹씩 추가한다.

```text
1단계 · 핵심 쓰기:  사용자 → Inventory Service → DB
                     “정확한 예약”을 먼저 완성

2단계 · 읽기 분리:  사용자 → Query API → Redis ⇢ cache miss → DB
                     “빈번한 조회”를 DB에서 분리

3단계 · 갱신 연결:  DB transaction → Outbox → Event Bus → Redis/UI
                     DB↔Redis dual write gap 제거

4단계 · 복구 추가:  만료 워커·대사 워커 → DB, DB snapshot → Redis 재구축
                     장애 후 돌아오는 길 표시

5단계 · 병목 확장:  DB를 sku_id로 shard, 정말 뜨거운 SKU만 queue/quota 검토
                     멀티 창고면 물류센터(FC)별 (sku, fc) 풀 + FC 할당, 한 행의 한계를 넘으면 파티션 이벤트 원장
                     요구된 규모만큼만 복잡도 추가 — 그림에는 "확장 레인" 박스 하나로만 표시
```

각 화살표에는 명사가 아니라 동사를 쓴다. `DB`만 적는 대신 `조건부 예약`, `outbox 발행`, `version이 클 때 갱신`, `만료 반환`이라고 적어야 면접관이 정합성 경계를 볼 수 있다.

요구사항과 박스의 대응:

| 요구사항 | 그림에 추가할 구성요소 |
|---|---|
| 재고 조회가 매우 빈번 | Query API + Redis + 제한된 DB fallback |
| 주문 차감이 정확 | Command Service + DB 조건부 UPDATE |
| 예약 확정·취소·만료 | 같은 Command의 confirm/release API, `WHERE status='RESERVED'` 조건부 전이 |
| 입고·반품·관리자 조정 | WMS → 같은 Command 경로 → RECEIVE/ADJUST movement (DB 직접 수정 금지) |
| 동일 SKU 동시 구매 | SKU 행 직렬화, 멱등 키, 예약 상태 머신 |
| 품절을 빠르게 반영 | Outbox/CDC + Event Bus + Redis/Product cache updater |
| Redis 장애 | cache bypass, circuit breaker, DB에서 재구축 |
| DB 장애에도 정합성 유지 | 동기 replica/quorum, fencing, 예약 fail closed |
| 장기 drift 탐지 | movement 원장 + reconciliation worker |

```text
                         ┌────────────── 조회 경로 ──────────────┐
사용자 ─▶ CDN/BFF ───────▶ Inventory Query API ──▶ Redis Cluster │
   │                     └──── cache miss ───────▶ DB Read 경로  │
   │                                                          │
   │ 주문(멱등 키)                                             │ 품절/재입고
   ▼                                                          ▼
Order Service ──reserve / confirm / release──▶ Inventory Command Service      SSE/Push/검색·상품 캐시
WMS·관리자 ────RECEIVE / ADJUST──────────────▶        │
                                                      │ 단일 로컬 트랜잭션
                                                      ▼
                   Inventory DB Primary (sku_id shard · (sku, fc) 재고 풀)
                   ├ inventory_balance  ← 현재 판단용 정본
                   ├ inventory_reservation
                   ├ stock_movement     ← 감사·대사용 이력
                   └ outbox_event       ← 같은 트랜잭션에 기록
                                │
                         WAL/CDC 또는 Outbox relay
                                ▼
                         Durable Event Bus
                         ├ Redis projection updater
                         ├ Product/Search 품절 updater
                         ├ Notification
                         └ Reconciliation pipeline

예약 만료 워커 ─▶ DB 조건부 상태 전이 ─▶ reserved 반환 + outbox
대사 워커 ─────▶ DB snapshot/ledger/order/Redis 비교 ─▶ 자동 수선 또는 알림
```

핵심 원칙:

- **DB가 명령(write model)의 정본**, Redis가 조회(read model)의 파생 뷰다.
- DB 변경과 이벤트 발행 의도를 `outbox_event`에 한 트랜잭션으로 기록한다.
- Redis와 브로커가 죽어도 DB의 예약 정합성은 유지된다.
- DB 정합성을 확인할 수 없으면 새 예약은 성공시키지 않는다.
- DB의 성공 응답은 WAL이 동기 replica/quorum에 내구화된 뒤에만 보낸다. failover 시에는 fencing으로 이전 primary의 쓰기를 차단하며, quorum을 만들 수 없으면 쓰기를 멈춘다.

## 5. 데이터 모델

```sql
CREATE TABLE inventory_balance (
    sku_id          BIGINT PRIMARY KEY,
    on_hand         INT NOT NULL CHECK (on_hand >= 0),
    reserved        INT NOT NULL CHECK (reserved >= 0),
    safety_stock    INT NOT NULL DEFAULT 0,
    version         BIGINT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL,
    CHECK (on_hand - reserved - safety_stock >= 0)
);

CREATE TABLE inventory_request (
    idempotency_key VARCHAR(128) PRIMARY KEY,
    request_hash    VARCHAR(64) NOT NULL,
    result_code     VARCHAR(24),          -- NULL/SUCCESS/OUT_OF_STOCK
    reservation_id UUID,
    created_at      TIMESTAMPTZ NOT NULL
);

CREATE TABLE inventory_reservation (
    reservation_id UUID PRIMARY KEY,
    order_id       UUID NOT NULL,
    sku_id         BIGINT NOT NULL,
    quantity       INT NOT NULL CHECK (quantity > 0),
    status         VARCHAR(16) NOT NULL, -- RESERVED/COMMITTED/RELEASED/EXPIRED
    expires_at     TIMESTAMPTZ NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL,
    UNIQUE (order_id, sku_id)
);

CREATE TABLE stock_movement (
    movement_id    UUID PRIMARY KEY,
    sku_id         BIGINT NOT NULL,
    movement_type  VARCHAR(24) NOT NULL, -- RECEIVE/RESERVE/COMMIT/RELEASE/ADJUST
    on_hand_delta  INT NOT NULL,         -- on_hand 변화량
    reserved_delta INT NOT NULL,         -- reserved 변화량
    reference_id   UUID NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL,
    UNIQUE (movement_type, reference_id, sku_id)
);

CREATE TABLE outbox_event (
    event_id       UUID PRIMARY KEY,
    aggregate_id   BIGINT NOT NULL,      -- sku_id
    aggregate_ver  BIGINT NOT NULL,
    event_type     VARCHAR(32) NOT NULL,
    payload        JSONB NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL,
    published_at   TIMESTAMPTZ           -- polling relay가 발행 후 기록. CDC relay는 사용하지 않음
);
```

- `inventory_balance`는 온라인 명령이 판단하는 현재 상태다.
- `inventory_request`는 성공뿐 아니라 품절 응답도 멱등하게 만들며, 같은 키에 다른 payload가 오면 거절할 수 있게 `request_hash`를 보관한다.
- `reservation`과 `movement`는 왜 그 값이 되었는지 설명하고 재구성·대사하는 기록이다.
- `stock_movement`는 `on_hand`와 `reserved` 두 잔액의 변화량을 분리해 기록한다. 그래야 `SUM(on_hand_delta) = on_hand`, `SUM(reserved_delta) = reserved`로 대사할 수 있다.

| movement_type | on_hand_delta | reserved_delta | 발생 시점 |
|---|---:|---:|---|
| RECEIVE | +q | 0 | 입고·반품 |
| RESERVE | 0 | +q | 예약 성공 |
| COMMIT | −q | −q | 결제 확정·출고 |
| RELEASE | 0 | −q | 취소·만료 |
| ADJUST | ±q | 0 | 관리자 조정·보상 |
- request·balance·reservation·movement·outbox를 **같은 DB 트랜잭션**에서 변경한다.
- 대용량 이력은 `created_at`과 `sku_id` 기준 파티셔닝·보존 정책을 둔다.

## 6. 정확한 재고 예약

### API

```http
POST /v1/inventory/reservations
Idempotency-Key: order-8f...-sku-123

{
  "reservationId": "...",
  "orderId": "...",
  "skuId": 123,
  "quantity": 2
}
```

### 채택: DB 조건부 UPDATE (의사 SQL)

```sql
BEGIN;

INSERT INTO inventory_request (idempotency_key, request_hash, created_at)
VALUES (:key, :request_hash, now())
ON CONFLICT DO NOTHING
RETURNING idempotency_key;

-- INSERT 결과가 없으면 이미 완결된 request다. 저장된 request_hash를 비교하고 result_code를 그대로 반환한다.
-- request INSERT와 result_code 갱신이 한 트랜잭션이므로 다른 세션은 result_code가 NULL인 행을 볼 수 없다.
-- 동시 재시도는 미커밋 unique 충돌에서 대기한 뒤 완결된 결과를 읽는다.
-- 아래 단계는 새 request를 INSERT한 요청만 실행한다.

UPDATE inventory_balance
   SET reserved   = reserved + :quantity,
       version    = version + 1,
       updated_at = now()
 WHERE sku_id = :sku_id
   AND on_hand - reserved - safety_stock >= :quantity
RETURNING on_hand - reserved - safety_stock AS remaining, version;

-- [분기 A] affected rows = 0이면 다음 결과만 기록하고 COMMIT/RETURN한다.
UPDATE inventory_request
   SET result_code = 'OUT_OF_STOCK'
 WHERE idempotency_key = :key;

-- [분기 B] affected rows = 1이면 아래 예약·movement·outbox를 기록한다.
INSERT INTO inventory_reservation (..., status, expires_at)
VALUES (..., 'RESERVED', :absolute_expiry);

INSERT INTO stock_movement (..., movement_type, on_hand_delta, reserved_delta, reference_id)
VALUES (..., 'RESERVE', 0, :quantity, :reservation_id);

INSERT INTO outbox_event (...);

UPDATE inventory_request
   SET result_code = 'SUCCESS', reservation_id = :reservation_id
 WHERE idempotency_key = :key;
COMMIT;
```

동시에 두 트랜잭션이 같은 SKU를 갱신하면 DB가 해당 행의 쓰기를 직렬화하고, 대기하던 UPDATE는 최신 행에 `WHERE` 조건을 다시 평가한다. 따라서 “읽기 → 애플리케이션 계산 → 쓰기”의 lost update 없이 `ATP`가 음수가 되지 않는다.

이 “대기 후 재평가”는 PostgreSQL **READ COMMITTED** 격리 수준의 동작이다. REPEATABLE READ·SERIALIZABLE에서는 대기하던 UPDATE가 재평가 대신 직렬화 실패(SQLSTATE `40001`)를 받으므로 애플리케이션이 같은 멱등 키로 재시도해야 한다. 예약 트랜잭션은 READ COMMITTED로 실행한다고 명시한다.

#### 멱등 키와 품절 결과

`OUT_OF_STOCK`도 그 멱등 키의 **종결 결과**다. 예약이 반환돼 재고가 돌아온 뒤 같은 키로 재시도해도 저장된 `OUT_OF_STOCK`을 그대로 받는다. 다시 시도하려면 클라이언트가 새 시도 ID로 새 `Idempotency-Key`를 써야 하며, 이 계약을 API 문서에 명시한다. 성공만 멱등 저장하고 품절은 매번 재평가하는 대안도 가능하지만, 그러면 “DB 커밋 후 응답 유실” 재시도에서 품절 응답의 재현성이 사라진다.

#### 여러 SKU를 한 주문에서 예약한다면

- 한 DB shard 안이면 모든 SKU를 `sku_id` 오름차순으로 갱신해 데드락 가능성을 줄이고 한 트랜잭션으로 all-or-nothing 처리한다.
- 여러 shard에 걸치면 글로벌 2PC 대신 Saga를 사용한다. 각 shard 예약 성공 후 하나가 실패하면 앞선 예약을 멱등하게 해제한다.
- UX 정책에 따라 부분 성공을 허용할 수도 있지만 API 계약에서 명시해야 한다.

### 예약 상태 머신

```text
                    결제/주문 확정
             ┌────────────────────────▶ COMMITTED
             │                           on_hand -= qty
             │                           reserved -= qty
AVAILABLE ─▶ RESERVED
             │  ├──사용자 취소────────▶ RELEASED
             │  └──expires_at 경과────▶ EXPIRED
             │                           reserved -= qty
             └──── 모든 전이는 WHERE status='RESERVED' 조건부 UPDATE
```

- `COMMIT`, `RELEASE`, `EXPIRE`가 경합해도 한 전이만 affected rows=1이다.
- `reserved` 반환은 상태 전이에 성공한 트랜잭션만 수행하므로 두 번 반환하지 않는다.
- 워커의 시간은 트리거일 뿐이다. 만료 여부의 기준은 DB에 박제한 `expires_at`이다.

### DB 장애와 모호한 성공

DB 커밋 직후 응답이 끊기면 클라이언트는 성공인지 실패인지 모른다. 무조건 다시 차감하지 말고 동일한 멱등 키로 재시도한다. 서버는 `inventory_request`를 조회해 성공과 품절을 포함한 기존 결과를 반환한다. 같은 키인데 `request_hash`가 다르면 잘못된 키 재사용이므로 거절한다.

## 7. Redis 캐시 구조와 역할

### 키 구조

```text
Key:   inv:{skuId}
Type:  HASH
Field: atp         17
       version     928341
       status      IN_STOCK       # IN_STOCK / LOW / OUT_OF_STOCK
       updated_at  1788490510000
TTL:   30~120초 + jitter          # 이벤트 유실의 안전망
```

- `{skuId}` hash tag는 같은 SKU의 보조 키를 같은 Redis Cluster slot에 둬 Lua 실행을 가능하게 한다.
- `version`은 out-of-order 이벤트가 새 값을 옛 값으로 덮는 것을 방지한다.
- 전체 SKU를 반드시 상주시킬 필요는 없다. 활성 working set을 cache-aside로 적재한다.
- 목록 조회는 pipeline/MGET 성격의 배치 API로 N+1 네트워크 왕복을 피한다.
- hot key는 replica로 읽기를 분산할 수 있지만 한 키의 쓰기 처리량은 shard 추가만으로 늘지 않는다.

### 캐시 갱신

```text
DB transaction commit
  → outbox relay/CDC
  → event {skuId, atp, version}
  → Redis Lua: incoming.version > cached.version 일 때만 HSET
```

이벤트 전달은 at-least-once로 보고 consumer는 `event_id` 또는 `version`으로 멱등 처리한다. cache miss를 DB에서 채우는 경로도 version을 비교해야 조회 도중 도착한 최신 이벤트를 과거 snapshot이 덮지 않는다. TTL은 주 갱신 수단이 아니라 이벤트 유실·장기 drift의 안전망이다.

### DB와 Redis의 책임 분리

| 질문 | DB | Redis |
|---|---|---|
| 주문을 받아도 되는가? | **최종 결정** | 빠른 사전 거절만 가능 |
| 초과 판매 방지 | 조건부 UPDATE/트랜잭션 | 책임지지 않음 |
| 상품 화면 조회 | miss·장애 시 원본 | **주 조회 경로** |
| 예약·반환 이력 | 보존 | 보존하지 않음 |
| 장애 복구 기준 | **정본** | DB에서 재생성 |
| 오래된 값 허용 | 명령 경로는 불허 | 짧은 stale 허용 |

## 8. Atomic Increment/Decrement를 어디에 쓸까

### 단순 `GET` 후 애플리케이션 계산은 안 된다

```text
GET inv:123 → 1        # 사용자 A, B 모두 1을 읽음
SET inv:123 0          # A: 성공으로 판단
SET inv:123 0          # B: 성공으로 판단 → 둘 다 샀지만 한 번만 감소
```

`DECRBY` 명령 자체는 원자적이며 반환값이 음수인 요청을 거절할 수 있다. 그러나 “음수면 보상 INCR” 방식은 두 명령 사이에 프로세스가 죽을 수 있고, “충분한지 검사 → 차감 → 멱등 기록”도 여러 단계다. Redis에서 수행한다면 Lua/Function 한 번으로 묶어야 한다.

```lua
-- KEYS[1] = inv:{skuId}, KEYS[2] = admission:{skuId}:{requestId}
-- ARGV[1] = quantity, ARGV[2] = ttl
-- 반환: 1 = 통과, 0 = 품절 거절, 2 = projection 없음(판단 불가 → DB로 통과)
if redis.call('EXISTS', KEYS[2]) == 1 then
  return 1 -- 같은 요청은 이미 통과
end

local raw = redis.call('HGET', KEYS[1], 'atp')
if not raw then
  return 2 -- 키가 없으면 거절하지 않는다. cache-aside로 채우고 DB가 판정
end

local stock = tonumber(raw)
local qty = tonumber(ARGV[1])
if stock < qty then
  return 0
end

redis.call('HINCRBY', KEYS[1], 'atp', -qty)
redis.call('SET', KEYS[2], qty, 'EX', ARGV[2])
return 1
```

키가 없을 때 `-1`로 취급해 거절하면 TTL 만료·콜드 캐시·failover 직후에 DB에 재고가 있어도 그 SKU의 모든 주문이 DB에 닿기 전에 막힌다. admission은 최적화이므로 **판단할 수 없으면 통과(fail open)**, 최종 판정은 DB가 한다. Redis 자체가 응답하지 않을 때도 같다.

### 채택안에서 Redis 차감은 admission control

1. Redis가 명백히 품절이면 DB에 도달하기 전에 빠르게 거절한다.
2. Redis가 통과시켰거나 판단할 수 없으면 DB 조건부 UPDATE가 최종 검증한다.
3. DB 예약에 실패한 요청의 선차감은 **보상 INCR로 되돌리지 않는다**. 다음 outbox 이벤트가 절대값 `atp`와 `version`으로 덮어써 교정하고, 이벤트가 오지 않으면 TTL 만료 후 DB에서 다시 채운다. 보상 INCR와 절대값 덮어쓰기를 함께 쓰면 이벤트가 먼저 맞춘 값에 INCR가 더해져 화면 재고가 과대 표시된다.
4. 사용자에게 성공을 응답하는 시점은 Redis가 아니라 DB 커밋 이후다.

Redis만으로 최종 차감을 결정하지 않는 이유:

- 기본 복제는 비동기라 마스터 장애·failover 시 이미 응답한 쓰기가 유실될 수 있다.
- Redis 차감 성공 후 DB 기록 전 프로세스가 죽으면 차감만 남는다.
- DB 성공 후 Redis 응답이 유실되면 무작정 보상할 때 실제 판매분을 되살릴 수 있다.
- `WAIT`는 위험을 줄이지만 Redis를 강한 정합성의 CP 시스템으로 바꾸지는 않는다.

즉 Redis 원자 차감은 **동시성 문제 하나**를 해결할 뿐, 두 저장소의 원자성·내구성·재시도 문제까지 해결하지 않는다.

## 9. 품절을 화면에 빠르게 반영하기

```text
DB 예약 커밋(atp=0)
  → InventoryChanged outbox event
  → Redis projection atp=0
  → Product/Search cache의 purchasable=false 무효화
  → 상품 상세 구독자에게 SSE/WebSocket "SOLD_OUT"
```

- 일반 상품 목록은 이벤트 무효화 + 짧은 TTL이면 충분하다.
- 트래픽이 몰리는 한정 판매 상세 화면만 SSE/WebSocket을 사용한다. 모든 상품에 실시간 연결을 유지할 필요는 없다.
- 클라이언트는 예약 API에서 `OUT_OF_STOCK`을 받으면 캐시 TTL을 기다리지 않고 즉시 품절 UI로 바꾼다.
- “1개 남음” 같은 숫자는 빠르게 흔들릴 수 있으므로 정확한 수량 대신 `IN_STOCK/LOW/OUT_OF_STOCK` 등급만 노출하는 정책도 가능하다.
- 화면이 잠시 `IN_STOCK`인데 checkout이 실패하는 false positive는 허용한다. 반대 방향의 stale 값은 판매 기회를 늦추지만 초과 판매는 만들지 않는다.

## 10. 장애 시나리오

| 장애 | 사용자 동작 | 정합성이 안전한 이유 | 복구 |
|---|---|---|---|
| Redis 전체 장애 | 조회는 제한된 DB fallback, 예약은 DB로 진행 | Redis는 정본이 아님 | circuit breaker, 요청 병합, 로컬 짧은 캐시로 DB 보호 후 재가열 |
| Redis stale/이벤트 역전 | 표시가 늦거나 checkout 실패 | DB가 최종 검증 | version 비교, TTL, DB snapshot으로 수선 |
| DB Primary 장애 | 조회는 캐시로 지속, **새 예약은 중단** | 확인되지 않은 판매를 성공 처리하지 않음 | 동기 replica 승격 후 멱등 재시도 |
| DB 커밋 후 응답 유실 | 클라이언트가 같은 키로 재시도 | request PK와 저장된 결과로 이중 차감 방지 | 기존 성공/품절 결과 반환 |
| 브로커 장애 | 화면 갱신 지연, 예약은 계속 가능 | outbox가 DB에 남아 있음 | relay 재처리, lag 알람, TTL fallback |
| Consumer 중복 전달 | 동일 이벤트 재수신 | event/version 멱등 처리 | 처리 위치 재개 |
| Consumer 순서 역전 | 과거 재고 이벤트가 늦게 도착 | 큰 version만 적용 | 오래된 이벤트 폐기 |
| 만료 워커 중단 | 예약 반환이 늦어져 덜 판매 | 재고를 성급히 복원하지 않음 | DB 인덱스 스캔 재개 |
| Inventory Service crash | 요청 결과가 모호할 수 있음 | DB transaction 원자성 + 멱등 키 | 동일 키 재시도 |
| 네트워크 분할 | DB quorum에 접근 못한 쪽은 쓰기 중단 | split brain 판매 방지 | quorum 복구 후 재시도·대사 |

요구사항이 “DB 장애에도 정합성이 깨지면 안 됨”이라면 가용성을 일부 포기한다. 동기 복제된 DB quorum이 새 정본을 확정할 수 없을 때 Redis 재고만 믿고 판매를 계속하는 것은 요구사항 위반이다.

## 11. Eventual Consistency를 안전하게 만드는 법

### 위험한 dual write

```text
DB UPDATE 성공 → 프로세스 crash → Redis 갱신 누락
Redis 갱신 성공 → DB UPDATE 실패 → 존재하지 않는 예약 표시
```

DB와 Redis를 애플리케이션이 차례로 쓰는 것만으로는 원자성을 만들 수 없다.

### Transactional Outbox

1. inventory 변경과 outbox 이벤트를 한 DB 트랜잭션에 저장한다.
2. relay가 WAL/CDC 또는 polling으로 outbox를 durable broker에 발행한다.
3. relay가 발행 후 죽을 수 있으므로 중복 발행을 정상 상황으로 본다.
4. consumer는 `event_id`와 SKU `version`으로 중복·역전을 무해하게 만든다.
5. Redis는 언제든 DB snapshot + 이후 이벤트 replay로 재구축할 수 있다.

허용하는 불일치 창은 “DB는 이미 0, Redis는 아직 1” 같은 **표시 지연**이다. 이때 새 요청이 들어와도 DB 조건부 UPDATE가 실패하므로 초과 판매하지 않는다.

## 12. 재고 대사 프로세스

대사는 단순히 `DB 값 = Redis 값`을 한 번 비교하는 작업이 아니다. 정상적인 이벤트 지연과 실제 불일치를 구분하고, 정본과 파생 뷰를 서로 다른 방식으로 수선해야 한다.

### 3단계 대사

```text
① DB 내부 불변식
inventory_balance.reserved
  ↔ SUM(active inventory_reservation.quantity)
  ↔ SUM(stock_movement.reserved_delta)
inventory_balance.on_hand
  ↔ SUM(stock_movement.on_hand_delta)

② 서비스 간 업무 상태
RESERVED ↔ Order=PENDING/PAYING
COMMITTED ↔ Order=CONFIRMED
RELEASED/EXPIRED ↔ 취소·만료 이벤트

③ 파생 뷰
DB {atp, version} ↔ Redis {atp, version}
                 ↔ Product/Search purchasable 상태
```

### 실행 절차

1. shard와 `sku_id` 범위로 작업을 나눠 checkpoint를 기록한다.
2. 같은 시점을 비교하도록 DB snapshot/LSN 또는 이벤트 watermark를 잡는다.
3. 우선 hot SKU와 `ATP <= 임계값`을 수 분 간격으로 검사하고 전체 스캔은 시간·일 단위로 수행한다. 주기는 비즈니스 SLO에 맞춘다.
4. 불일치를 `CACHE_LAG`, `MISSING_EVENT`, `DUPLICATE_TRANSITION`, `ORPHAN_RESERVATION`, `LEDGER_MISMATCH` 등으로 분류한다.
5. Redis·검색 같은 파생 뷰는 DB의 더 큰 version으로 자동 덮어쓴다.
6. DB 내부 불일치는 현재 값을 조용히 UPDATE하지 않는다. 원인·승인자를 남기는 **보상 movement**로 수정한다.
7. 수선 작업 자체에도 `reconciliation_run_id + sku_id + reason` 멱등 키를 둔다.

### 관측 지표

- `inventory_negative_total` — 항상 0이어야 하는 핵심 불변식
- 예약 성공/품절 거절/DB conflict 비율
- SKU별 row-lock wait와 p95/p99 예약 지연
- outbox oldest age, broker consumer lag, Redis version lag
- 만료 시간이 지났는데 `RESERVED`인 건수와 최고 age
- DB ↔ Redis, balance ↔ reservation/ledger 불일치 건수
- 보상 처리량과 수동 검토 backlog

## 13. Hot SKU 확장 전략

수백만 SKU로의 수평 확장과 하나의 SKU로 몰리는 확장은 다른 문제다. 기본 DB shard를 늘려도 한 SKU는 여전히 한 행이다.

| 전략 | 장점 | 비용/한계 | 적합한 경우 |
|---|---|---|---|
| DB 조건부 UPDATE (기본) | 단순, 동기 응답, 정합성 명확 | 한 SKU 행 lock 병목 | 일반 이커머스 |
| Redis admission + DB UPDATE | 품절 뒤 DB로 가는 실패 요청 제거 | 성공 쓰기 병목은 그대로 | 품절 직전 읽기·실패 폭주 |
| SKU별 durable queue + single writer | 경합 제거, 순서 명확, replay 가능 | 비동기 결과, 한 파티션 처리량 상한 | 한정판·선착순, 비동기 UX 허용 |
| 재고 quota/escrow 분할 | 여러 cell이 병렬로 자기 quota 차감, 총합 초과 판매 없음 | quota 재분배·잔여 파편화·운영 복잡도 | 초고속 글로벌 판매 |

### quota/escrow 예시

재고 10,000개를 주문 cell A/B/C/D에 각 2,500개씩 선할당한다. 각 cell은 자기 DB에서만 강하게 차감하므로 합계 10,000을 넘을 수 없다. A가 품절인데 B에 남는 false sold-out은 허용하고, 백그라운드가 안전하게 quota를 이동한다. 이는 가용 재고를 조금 덜 파는 대신 초과 판매를 막는 방향의 불일치다.

한정판 트래픽이 실제 요구사항이 아니라면 처음부터 queue·quota를 도입하지 않는다. 먼저 SKU별 lock wait·TPS를 측정한 뒤 hot path만 분리한다.

## 14. 대안 비교에서 기대하는 L6 판단

### 낙관적 버전 CAS vs 조건부 수량 UPDATE

```sql
-- 버전 CAS
UPDATE inventory_balance
SET reserved = reserved + :q, version = version + 1
WHERE sku_id = :sku AND version = :read_version;
```

| 방식 | 장점 | 한계 | 적합한 경우 |
|---|---|---|---|
| version CAS | 읽은 값 기준으로 어떤 규칙이든 검증 가능 | 다른 변경이면 모두 재시도 → 경합 높을 때 retry storm | 경합이 낮고 여러 필드 규칙이 얽힌 갱신 |
| 수량 조건부 UPDATE (채택) | 최신 행에서 수량만 충분하면 진행, 왕복 1회, 실패 판정이 affected rows로 명확 | 단일 행·단일 조건에 적합 | 이 문제의 SKU 예약 |
| `SELECT ... FOR UPDATE` | 여러 행·allocation 우선순위 규칙을 애플리케이션에서 표현하기 쉬움 | 잠금 보유 시간과 왕복 횟수 증가 | 멀티 창고 allocation 단계 |

### 정본을 어디에 둘 것인가

| 방식 | 장점 | 한계 | 결론 |
|---|---|---|---|
| DB 정본 + Redis projection (채택) | 예약 정합성·내구성이 DB 트랜잭션 하나로 보장, Redis는 언제든 재생성 | 쓰기 경로가 DB 한 행 처리량에 묶임 | 판매 재고처럼 유실 불가 값 |
| Redis 정본 + write-behind DB | 매우 낮은 쓰기 지연, 높은 처리량 | failover 시 acknowledged write 유실, 비동기 DB 반영 사이의 복구·두 저장소 원자성 문제 | 분석 카운터처럼 일부 유실 가능한 값 |

### `exactly once`라는 표현

네트워크에서 요청·이벤트가 정확히 한 번만 전달된다고 가정하지 않는다. at-least-once 전달을 허용하고, DB의 unique constraint·조건부 상태 전이·event version으로 **업무 효과가 한 번만 발생**하게 만든다.

## 15. 40분 모의 면접 진행법

### 0~5분: 범위와 불변식

- Product와 SKU를 구분한다.
- 재고 예약 시점과 만료 정책, 멀티 창고 포함 여부를 질문한다.
- 화면은 eventual, checkout은 strong이라는 일관성 경계를 선언한다.

### 5~10분: 규모 추정

- 읽기:쓰기 비율, peak QPS/TPS, 활성 SKU 수를 가정한다.
- 평균이 아니라 hot SKU 집중도를 병목으로 찾는다.

### 10~20분: 정상 흐름

- Redis 조회 → DB 조건부 예약 → outbox → cache 갱신을 그린다.
- 데이터 모델과 상태 머신, 멱등 키를 설명한다.

### 20~30분: 장애 주입

- “DB 커밋 직후 응답이 끊겼다면?”
- “Redis failover로 DECR이 사라졌다면?”
- “outbox consumer가 이벤트를 역순으로 받았다면?”
- 각 질문에 불변식, 탐지, 복구 순서로 답한다.

### 30~40분: 확장과 운영

- 일반 SKU와 hot SKU 전략을 분리한다.
- 대사 watermark, 자동 수선 범위, 핵심 알람을 설명한다.
- 요구하지 않은 복잡도를 왜 처음부터 넣지 않는지도 말한다.

## 16. 꼬리 질문 대비

### Q1. Redis `DECR`가 원자적인데 왜 DB UPDATE가 또 필요한가?

원자성의 범위가 Redis 한 인스턴스의 한 명령뿐이기 때문이다. failover 내구성과 Redis↔DB 사이의 부분 실패, 요청 재시도까지 포함한 업무 트랜잭션은 해결하지 못한다.

### Q2. 캐시에 1개가 남았는데 실제 DB는 0이면 사용자 경험이 나쁘지 않은가?

맞다. 정확성 때문에 checkout 실패는 허용하되 outbox 이벤트, version 갱신, 짧은 TTL, 클라이언트 즉시 품절 처리로 불일치 시간을 줄인다. 정확성과 표시 지연의 SLO는 분리한다.

### Q3. DB가 죽었을 때 Redis로 주문을 계속 받으면 안 되는가?

현재 요구사항에서는 안 된다. Redis failover의 acknowledged write 유실 가능성과 durable 예약 원장 부재 때문에 초과 판매 여부를 증명할 수 없다. 조회는 유지하지만 새 예약은 fail closed한다.

### Q4. DB failover 중 클라이언트가 timeout 후 재시도하면?

같은 Idempotency-Key를 사용한다. 새 primary에서 `inventory_request`의 기존 결과를 조회해 그대로 반환한다. 같은 키와 다른 payload 조합은 `request_hash` 비교로 거절한다.

### Q5. 예약 만료 워커와 결제 성공이 동시에 실행되면?

둘 다 `WHERE status='RESERVED'` 조건부 전이를 시도한다. 먼저 커밋한 하나만 성공하며, 성공한 전이만 수량을 변경한다. 늦은 결제 성공의 환불 여부는 주문/결제 정책으로 처리한다.

### Q6. 상품 하나에 주문이 10만 TPS로 몰리면?

Redis admission으로 품절 실패 요청을 먼저 줄인다. 성공 요청 자체가 DB 한 행의 한계를 넘으면 그 SKU를 durable queue의 single writer로 전환하거나, 총량을 넘지 않도록 quota/escrow를 여러 cell에 선할당한다.

### Q7. Redis와 DB 값이 다르면 어느 쪽을 고치는가?

Redis는 DB의 현재 balance/version으로 자동 재생성한다. DB balance와 reservation/ledger가 다르면 조용히 덮어쓰지 않고 원인을 조사한 뒤 감사 가능한 보상 movement를 기록한다.

### Q8. `on_hand`와 `reserved`를 굳이 분리하는 이유는?

결제 전 확보와 실제 출고를 구분하기 위해서다. 예약 취소는 `reserved`만 줄이고, 확정 출고는 `on_hand`와 `reserved`를 함께 줄인다. 그래야 주문 상태와 창고 실재고를 대사할 수 있다.

### Q9. 멀티 리전 active-active로 쓰면?

동일 재고 풀을 여러 리전에서 독립 차감하면 네트워크 분할 때 초과 판매할 수 있다. SKU/재고 풀의 단일 home region으로 쓰기를 라우팅하거나, 리전별 escrow quota를 선할당한다. 글로벌 수량 표시는 eventual하게 합산한다.

### Q10. DB replica에서 재고를 읽어 예약을 판단하면?

복제 지연 때문에 과거 수량을 볼 수 있다. 조회 표시는 replica/Redis에서 해도 되지만 조건부 예약은 해당 shard의 write leader에서 실행한다.

## 17. 직접 풀어볼 장애 타임라인

각 문제에서 먼저 “사용자 응답”, “DB”, “Redis”, “보상 작업” 네 칸을 그려 답한다.

1. Redis admission에서 1개 차감한 직후 Inventory Service가 죽었다.
2. DB 예약은 커밋됐지만 outbox relay가 20분 중단됐다.
3. `version=12` 이벤트 처리 후 `version=11` 이벤트가 도착했다.
4. 결제 성공과 예약 만료가 같은 밀리초에 실행됐다.
5. 주문 취소 이벤트가 세 번 전달됐다.
6. 재고 100개를 4개 리전에 25개씩 배분했는데 한 리전만 품절됐다.
7. 대사 중에도 주문이 계속 들어와 DB와 Redis 숫자가 계속 달라진다.

합격 답변의 공통 구조:

```text
① 지켜야 할 불변식 선언
② 성공을 결정하는 정본과 원자 연산 지정
③ 부분 실패 시 사용자에게 무엇을 응답하는지 설명
④ 중복·역전·재시도를 멱등하게 만드는 키/상태/version 제시
⑤ 탐지 지표와 복구·대사 절차 제시
```

## 18. 면접 한 줄 정리 모음

- **전체**: “화면 재고는 Redis의 빠른 projection, 판매 가능 여부는 DB의 조건부 예약이 결정하며, Outbox와 대사가 두 뷰의 결과적 일관성을 닫습니다.”
- **동시성**: “`ATP >= 요청량`을 WHERE에 넣은 단일 UPDATE로 같은 SKU의 경합을 DB에서 직렬화하고 affected rows로 품절을 판정합니다.”
- **Redis 원자 연산**: “DECR는 한 Redis 안에서는 원자적이지만 failover 내구성이나 DB와의 원자성은 제공하지 않으므로 admission 최적화로만 씁니다.”
- **장애**: “Redis 장애는 느려지는 장애, DB quorum 장애는 판매를 멈추는 장애로 설계해 초과 판매보다 가용성을 양보합니다.”
- **Eventual Consistency**: “stale 화면은 허용하되 checkout에서 다시 검증해 불일치의 결과가 초과 판매가 아니라 일시적 주문 실패가 되게 합니다.”
- **멱등성**: “exactly-once 전달이 아니라 unique key와 조건부 상태 전이로 exactly-once 업무 효과를 만듭니다.”
- **대사**: “파생 캐시는 DB version으로 자동 수선하고, DB 원장의 차이는 덮어쓰기 대신 추적 가능한 보상 movement로 교정합니다.”
- **hot SKU**: “전체 SKU 샤딩과 단일 hot SKU는 별개라서, 후자는 admission, single writer, escrow quota 중 UX와 처리량에 맞게 선택합니다.”

## 19. 설계 검증 체크리스트

- [ ] 상품과 SKU, 논리 재고와 물리 재고의 범위를 합의했는가?
- [ ] 화면 조회와 주문 예약의 일관성 수준을 분리했는가?
- [ ] 초과 판매 방지 불변식을 한 문장과 한 SQL로 보일 수 있는가?
- [ ] 모든 외부 재시도에 stable idempotency key가 있는가?
- [ ] DB와 이벤트 발행 사이 dual-write gap을 닫았는가?
- [ ] 중복·역순 이벤트가 와도 cache version이 후퇴하지 않는가?
- [ ] DB 장애 때 무엇을 포기할지 명확한가?
- [ ] 예약 만료와 결제 확정 경합을 상태 머신으로 막았는가?
- [ ] hot SKU가 일반 shard 확장으로 해결되지 않음을 설명했는가?
- [ ] 대사의 비교 시점, 자동 수선 범위, 보상 이력이 있는가?

## 20. 참고 자료

### 설계 근거

1. [Redis DECR 공식 문서](https://redis.io/docs/latest/commands/decr/) — 정수 감소 명령과 O(1) 특성
2. [Redis Lua scripting 공식 문서](https://redis.io/docs/latest/develop/programmability/eval-intro/) — 서버 내부 스크립트의 원자 실행
3. [Redis replication 공식 문서](https://redis.io/docs/latest/operate/oss_and_stack/management/replication/) — 비동기 복제와 `WAIT`의 보장 한계
4. [Redis cache-aside 공식 문서](https://redis.io/docs/latest/develop/use-cases/cache-aside/) — cache miss fallback과 TTL 기반 stale 제한
5. [PostgreSQL Transaction Isolation 공식 문서](https://www.postgresql.org/docs/current/transaction-iso.html) — 동시 UPDATE 시 대기 후 WHERE 조건 재평가
6. [PostgreSQL UPDATE 공식 문서](https://www.postgresql.org/docs/current/sql-update.html) — 조건부 UPDATE와 `RETURNING`
7. [Transactional Outbox 패턴](https://microservices.io/patterns/data/transactional-outbox) — DB 변경과 메시지 발행 의도의 원자적 기록
