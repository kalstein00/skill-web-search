# Domain docs

## 구성과 탐색

단일 컨텍스트 구성: 루트 `CONTEXT.md`와 `docs/adr/`를 사용한다.

코드베이스 탐색 전에 `CONTEXT.md`와 관련 ADR을 읽는다.
향후 루트 `CONTEXT-MAP.md`가 생기면 그 지도를 따라 관련 컨텍스트의
`CONTEXT.md`와 `src/<context>/docs/adr/`도 읽는다.

파일이 없으면 그대로 진행한다. 도메인 용어나 결정이 구체화될 때
domain-modeling 스킬로 문서를 만든다.

## 용어와 결정

이슈, 설계, 가설, 테스트에서 도메인 개념을 지칭할 때는
`CONTEXT.md`에 정의된 용어를 사용한다.
필요한 용어가 없으면 기존 개념인지 확인하고 실제 공백을 기록한다.

기존 ADR과 충돌하는 제안에는 해당 ADR과 재검토 이유를 명시한다.
