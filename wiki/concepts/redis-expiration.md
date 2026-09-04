---
type: Concept
title: Redis 만료(TTL)의 내부 구조
description: TTL은 별도 expires dict의 절대시각이며, 삭제는 lazy+active 샘플링이라 만료 시점·이벤트 전달이 보장되지 않는다
timestamp: 2026-09-04T12:00:00+09:00
tags: [redis, ttl, expiration, keyspace-notification]
---

# Redis 만료(TTL)의 내부 구조

[선착순 티켓 예매 시스템](/wiki/system-design/ticket-booking.md)의 HOLD 만료 설계 근거가 되는 개념.

## 물리 저장: 값과 알람의 분리

```
        SET hold:ticket:1 10245 NX EX 1800
                     │
        SipHash("hold:ticket:1") % 버킷 수
                     ▼
 ① 메인 dict (값)                    ② expires dict (TTL)
 dictEntry                          "hold:ticket:1" →
 ├ key: SDS "hold:ticket:1"  ←키 공유→  만료 절대시각 (unix ms)
 └ val: 10245 (int 인코딩)
```

- Redis DB 하나 = 거대한 해시테이블(`dict`). 작은 정수 값은 int 인코딩으로 포인터 자리에 저장
- **TTL은 값 옆이 아니라 별도 `expires` dict에 "키 → 만료 절대시각(unix ms)"으로 저장** — "1800초 남음" 카운트다운이 아니라 "몇 시에 죽는다"는 시각 하나
- 분리 덕분에 TTL 유무가 GET 성능에 영향 없음
- 전부 RAM. 디스크는 RDB 스냅샷/AOF 로그만

## 삭제의 두 방식 (그래서 시점 보장이 없다)

1. **lazy**: 키 접근 시 만료시각과 현재시각 비교 → 지났으면 그 자리에서 삭제. 만료시각이 지난 키는 물리 삭제 전이라도 접근 시 nil (논리적 정합성은 즉시)
2. **active**: 백그라운드가 0.1초마다 expires dict에서 ~20개 샘플링해 삭제

접근이 없고 TTL 키가 많으면 물리 삭제가 상당히 지연될 수 있다 (공식 문서 명시).

## Keyspace Notification (expired 이벤트)

- 설정: `CONFIG SET notify-keyspace-events Ex` → 구독: `SUBSCRIBE __keyevent@0__:expired` → 메시지로 키 이름 수신
- **함정 3가지** (공식 문서):
  1. Pub/Sub은 fire-and-forget — 구독자가 끊겼다 재접속하면 그 사이 이벤트 전부 유실, 재전송 없음
  2. 이벤트는 TTL이 0이 되는 순간이 아니라 **실제 삭제 순간**에 발행 — lazy/샘플링 때문에 지연 가능
  3. 클러스터에서는 노드별 발행 — 모든 노드에 각각 구독 필요

→ 설계 결론: expired 이벤트는 지연 단축용 최적화로만 쓰고, 정합성은 DB 만료시각 기반 배치 스캔이 책임진다. 유실 없는 폴링이 필요하면 만료시각을 score로 둔 Sorted Set을 1초 주기로 `ZRANGEBYSCORE` (처리 성공 후 ZREM — 워커가 죽어도 다음 턴에 재시도).

## 면접 한 줄

"Redis TTL은 값의 속성이 아니라 별도 expires 해시테이블의 절대시각입니다. 그래서 수만 키에 TTL을 걸어도 조회 비용이 동일하고, 삭제가 lazy+샘플링이라 만료 시점과 expired 이벤트 전달이 보장되지 않는 것까지가 한 세트입니다."

# Citations

[1] [Redis keyspace notifications 공식 문서](https://redis.io/docs/latest/develop/pubsub/keyspace-notifications/)
