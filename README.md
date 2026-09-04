---
type: Meta
title: Interview LLM Wiki
description: 이직 준비(시스템 디자인·면접·지원 현황)를 LLM이 유지보수하는 개인 지식 번들
timestamp: 2026-09-04T12:00:00+09:00
---

# Interview LLM Wiki

Karpathy의 [LLM Wiki 패턴](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)을 따르는 개인 지식 저장소입니다.
Claude가 위키 본문을 전담 관리하고, 사람은 공부하고 질문합니다.

## 무엇이 들어있나

- **시스템 디자인 연습** — 설계 문제별 아키텍처, 트레이드오프, 꼬리 질문 대비
- **개념 정리** — 면접에서 깊이 파고드는 기술 개념 (Redis 내부 구조 등)
- **지원 현황·면접 복기** — 회사별 진행 상태, 면접 후기와 배운 것
- **예상 질문 은행** — 질문과 준비된 답변

## 읽는 법

1. [index.md](/index.md)에서 시작 — 전체 페이지 카탈로그
2. [log.md](/log.md) — 최근에 무엇이 바뀌었는지
3. 각 페이지 frontmatter의 `timestamp`로 정보의 신선도 확인

## 구조

```
index.md / log.md      # 예약 파일: 카탈로그 / 연대기
wiki/system-design/    # 설계 문제별 문서
wiki/concepts/         # 기술 개념 정리
wiki/companies/        # 회사별 지원 현황 (lazy 생성)
wiki/interviews/       # 면접 복기 (lazy 생성)
wiki/questions/        # 예상 질문 은행 (lazy 생성)
wiki/assets/<슬러그>/   # 첨부 (HTML 시각화 등)
raw/                   # 불변 원본 스냅샷 (JD 공고 등)
CLAUDE.md              # 규약 정본
```
