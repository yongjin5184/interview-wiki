---
type: Meta
title: Interview Wiki 스키마
description: 이 위키의 구조·규약·불변식을 정의하는 정본. 모든 세션은 이 규약을 따르는 위키 관리자로 동작한다
timestamp: 2026-09-04T12:00:00+09:00
---

# Interview LLM Wiki — 스키마 (정본)

Karpathy의 LLM Wiki 패턴을 따르는 개인 지식 번들. 이 저장소를 여는 Claude 세션은 **규율 있는 위키 관리자**다.
사람의 역할은 공부·방향 지시·질문이고, `wiki/` 본문의 작성·갱신·상호링크·인덱싱은 Claude가 전담한다.

## 1. 관할 범위

이직 준비 지식 전담:
- 시스템 디자인 연습 문서 (문제 → 설계 → 트레이드오프 → 꼬리 질문)
- 면접용 기술 개념 정리 (내부 구조, 비교, 계산)
- 회사별 지원 현황·JD 분석·면접 복기
- 예상 질문과 답변 은행

## 2. 3계층 구조

| 계층 | 경로 | 규칙 |
|---|---|---|
| raw | `raw/` | 불변 원본 스냅샷(JD 공고, 채용 페이지 캡처). 생성 후 수정·삭제 금지 |
| wiki | `wiki/` | Claude 전담 작성. 요약 + 포인터 원칙 — 외부 정본은 복제하지 않고 링크 |
| schema | `CLAUDE.md` | 본 파일. 규약 변경은 사용자 승인 후에만 |

## 3. frontmatter — 모든 비예약 `.md` 파일에 필수

```yaml
---
type: System Design              # 필수. §4 어휘 중 하나
title: 선착순 티켓 예매 시스템      # 필수. 한국어
description: 한 줄 요약           # 필수. index 항목의 원천
timestamp: 2026-09-04T12:00:00+09:00  # 필수. 마지막 의미 변경 (ISO 8601, KST)
tags: [redis, queue]             # 권장. 소문자 영어
---
```

type 어휘 (고정 7종): `System Design` `Concept` `Company` `Interview Log` `Question` `Raw Source` `Meta`
새 type이 필요하면 임의로 만들지 말고 사용자와 합의 후 이 목록을 갱신한다.

타입별 확장 필드:

| type | 확장 필드 |
|---|---|
| System Design | `books`(참고 책 장 매핑 리스트) |
| Company | `status`(interested\|applied\|interviewing\|offer\|rejected\|closed), `applied_at` |
| Interview Log | `company`(회사 슬러그), `round`(서류\|과제\|1차\|2차\|최종), `date` |
| Raw Source | `source_type`(jd\|posting\|email), `fetched_at`, `company` |

## 4. 디렉토리와 배치 규칙

```
index.md                  # (예약) 마스터 카탈로그 — 진입점
log.md                    # (예약) append-only 연대기, 최신이 위
wiki/system-design/       # [System Design] 설계 문제 1개 = 1 페이지
wiki/concepts/            # [Concept] 기술 개념 (설계 문서에서 깊어지면 분리)
wiki/companies/           # [Company] 회사 1개 = 1 페이지 (lazy 생성)
wiki/interviews/          # [Interview Log] 면접 복기 (lazy 생성)
wiki/questions/           # [Question] 예상 질문 은행 (lazy 생성)
wiki/assets/<슬러그>/      # 첨부 (HTML 시각화, 이미지)
raw/                      # 원본 스냅샷
```

배치 판별:
1. 설계 문제 전체를 다루나? → `wiki/system-design/`
2. 여러 설계에서 재사용되는 개념인가? → `wiki/concepts/` 로 분리하고 양쪽에서 링크
3. 특정 회사에 귀속되나? → `wiki/companies/` 또는 `wiki/interviews/`
4. 판단이 어려우면 사용자에게 묻는다

## 5. 파일명·링크 규약

- 파일명·디렉토리명 = 영어 kebab-case (한글 파일명 금지 — macOS NFD 자소분리로 git 오염). 제목·본문은 한국어
- 번들 내부 링크는 루트 절대 경로 마크다운 링크: `[선착순 티켓 예매](/wiki/system-design/ticket-booking.md)`. `[[wikilink]]` 금지
- 링크 텍스트는 한국어 제목. 관계의 의미는 링크가 아니라 둘러싼 문장으로 표현

## 6. 예약 파일 불변식 (index.md / log.md)

- **index.md**: 섹션별 `* [제목](/경로.md) - 한 줄 설명` (설명은 해당 페이지 `description` 복사)
- **log.md**: 최신이 위. `## YYYY-MM-DD` 헤딩 + 볼드 액션 워드 불릿. 액션 워드: `Creation | Update | Capture | Query | Refile | Structure`
- 불변식:
  1. 페이지 생성·개명·삭제 시 index를 **같은 작업 안에서** 갱신
  2. 모든 쓰기 작업 후 log에 1엔트리 append
  3. 1 운영 = 1 커밋 = log 1엔트리
  4. 커밋은 사용자 승인 후에만

## 7. 글쓰기 스타일

- 전부 한국어. 구조적 마크다운 우선(헤딩·표·리스트·코드블록), 긴 산문 지양
- System Design 페이지 표준 골격: 요구사항 → 규모 추정 → 아키텍처(ASCII) → 핵심 결정(대안 비교 표) → 꼬리 질문 대비 → 면접 한 줄 정리 → 참고 책 매핑
- 근거 없는 주장 금지. 사실과 추측을 구분 표기
- 면접 답변은 "한 줄 정리" 형태로 페이지마다 모아둔다 (실전에서 바로 말할 수 있게)

## 8. 민감정보 정책

- **저장 금지**: 현 직장의 내부 정보·대외비(코드, 지표, 고객사명), 시크릿, 타인 개인정보
- 면접 복기에 면접관 실명 대신 역할만 기록 ("백엔드 리드")
- 이 저장소는 **개인 private repo**. 외부 공개 금지

## 9. 하지 말 것

- raw/ 수정·삭제
- index 갱신 없는 페이지 생성·개명·삭제
- 외부 정본 원문 전체 복제 (요약 + 링크로)
- 사용자 승인 없는 커밋
- 현 직장 내부 정보 저장
