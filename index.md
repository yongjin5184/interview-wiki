---
okf_version: "0.1"
---

# Interview Wiki — 카탈로그

## 시스템 디자인

* [선착순 티켓 예매 시스템](/wiki/system-design/ticket-booking.md) - 10만 동접·5만 장 선착순 예매 — 대기열 카운터, Redis 원자 차감, TTL 만료 워커, 상태 머신, 결과적 일관성 설계
* [대규모 이커머스 재고 시스템](/wiki/system-design/inventory-system.md) - 수백만 SKU의 조회 폭주와 동시 주문을 처리하는 DB 조건부 예약, Redis projection, Outbox/CDC, 장애 격리·재고 대사 설계

## 개념

* [Redis 만료(TTL)의 내부 구조](/wiki/concepts/redis-expiration.md) - TTL은 별도 expires dict의 절대시각이며, 삭제는 lazy+active 샘플링이라 만료 시점·이벤트 전달이 보장되지 않는다
* [시스템 디자인 면접 학습 자료](/wiki/concepts/system-design-interview-resources.md) - 모든 시스템 디자인 문제에 공통으로 활용하는 개념·패턴·문제·사례·면접 자료의 탐색 허브

## 회사 / 면접 / 질문 은행

(아직 없음 — lazy 생성)

## 메타

* [README](/README.md) - 이직 준비(시스템 디자인·면접·지원 현황)를 LLM이 유지보수하는 개인 지식 번들
* [CLAUDE.md](/CLAUDE.md) - 이 위키의 구조·규약·불변식을 정의하는 정본
