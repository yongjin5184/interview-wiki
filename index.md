---
okf_version: "0.1"
---

# Interview Wiki — 카탈로그

## 시스템 디자인

* [선착순 티켓 예매 시스템](/wiki/system-design/ticket-booking.md) - 10만 동접·5만 장 선착순 예매 — 대기열 카운터, Redis 원자 차감, TTL 만료 워커, 상태 머신, 결과적 일관성 설계

## 개념

* [Redis 만료(TTL)의 내부 구조](/wiki/concepts/redis-expiration.md) - TTL은 별도 expires dict의 절대시각이며, 삭제는 lazy+active 샘플링이라 만료 시점·이벤트 전달이 보장되지 않는다

## 회사 / 면접 / 질문 은행

(아직 없음 — lazy 생성)

## 메타

* [README](/README.md) - 이직 준비(시스템 디자인·면접·지원 현황)를 LLM이 유지보수하는 개인 지식 번들
* [CLAUDE.md](/CLAUDE.md) - 이 위키의 구조·규약·불변식을 정의하는 정본
