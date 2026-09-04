# 연대기

## 2026-09-04

* **Update**: /wiki/assets/inventory-system/eli5-inventory-system.html 및 /wiki/system-design/inventory-system.md — 완성 그림 보강: 입고·조정(WMS) 박스와 RECEIVE/ADJUST 화살표 추가, reserve 라벨을 reserve/confirm/release(멱등키)로 확장, DB 박스에 sku_id shard·(sku, fc) 풀 표기, hot SKU 박스를 확장 레인(hot SKU·FC 할당·파티션 이벤트 원장)으로 일반화. 화살표 번호 12개로 재정렬, 4절 ASCII·대응 표·5단계 문구 동기화
* **Update**: /wiki/system-design/inventory-system.md — 검토 반영: Redis admission Lua의 cache miss를 거절→통과(fail open)로 수정, 선차감 보상 INCR 제거(절대값 덮어쓰기만), READ COMMITTED 격리 수준 전제 명시, IN_PROGRESS 도달 불가 주석 정정, 품절 결과의 멱등 계약 추가, stock_movement를 on_hand/reserved delta로 분리, outbox published_at 추가, 14절 대안 비교를 표로 전환
* **Update**: /wiki/assets/inventory-system/eli5-inventory-system.html — 완성 그림(장면 12) 화살표 11개에 번호표와 1:1 기능·보장 설명 리스트 추가, version 갱신 화살표가 Inventory Command 박스를 관통하던 경로 우회
* **Update**: /wiki/system-design/inventory-system.md 및 /wiki/assets/inventory-system/eli5-inventory-system.html — 문제 해체, 요구사항 도출, 5단계 아키텍처 드로잉 학습 흐름 추가
* **Refile**: 시스템 디자인 외부 자료를 재고 문서에서 /wiki/concepts/system-design-interview-resources.md 공통 학습 허브로 분리
* **Update**: /wiki/system-design/inventory-system.md — 외부 시스템 디자인 자료 모음과 재고 설계 연계 학습 경로 추가
* **Creation**: /wiki/system-design/inventory-system.md — 대규모 이커머스 재고 시스템 설계·장애 시나리오·대사·L6 모의 면접 자료
* **Structure**: 위키 초기화 — Karpathy LLM Wiki 패턴 기반 스키마(CLAUDE.md)·index·log 생성
* **Creation**: /wiki/system-design/ticket-booking.md — 선착순 티켓 예매 시스템 설계 (Claude 세션 문답 정리)
* **Creation**: /wiki/concepts/redis-expiration.md — Redis TTL 내부 구조·keyspace notification 함정
* **Creation**: /wiki/assets/ticket-booking/eli5-ticket-system.html — ELI5 시각화 13장면
* **Structure**: .gitattributes 추가 — index.md/log.md union 머지 (협업 대비 동시 편집 충돌 제거)
