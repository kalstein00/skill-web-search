# Issue tracker: GitHub

이슈와 명세는 이 저장소의 GitHub Issues에서 관리한다.
저장소는 `git remote -v`로 확인하고, 작업에는 `gh` CLI를 사용한다.

## 기본 작업

- 생성: `gh issue create --title "..." --body-file <path>`
- 조회: `gh issue view <number> --comments`
- 라벨 포함 조회: `gh issue view <number> --json title,body,labels,comments`
- 목록: `gh issue list --state open`
- 댓글: `gh issue comment <number> --body-file <path>`
- 라벨 추가/제거: `gh issue edit <number> --add-label "..." --remove-label "..."`
- 종료: `gh issue close <number>`

여러 줄 본문은 실제 줄바꿈을 유지한 UTF-8 임시 파일에 작성하고
`--body-file`로 전달한다.

스킬의 "publish to the issue tracker"는 GitHub 이슈 생성을 뜻한다.
"fetch the relevant ticket"은 이슈 본문과 댓글 조회를 뜻한다.

## Pull requests as a triage surface

**PRs as a request surface: no.**

## Wayfinding

- Map은 `wayfinder:map` 라벨의 이슈이며 Notes, Decisions-so-far,
  Fog를 본문에 기록한다.
- Child ticket은 GitHub sub-issue로 Map에 연결한다.
  지원되지 않으면 Map의 작업 목록과 Child의 `Part of #<map>`으로 연결한다.
- Child에는 `wayfinder:<type>` 라벨을 사용한다.
  type은 research, prototype, grilling, task 중 하나다.
- 차단 관계는 GitHub native issue dependencies로 기록한다.
  지원되지 않으면 Child 본문 상단에 `Blocked by: #<number>`를 기록한다.
- Frontier는 열린 Child 중 열린 blocker와 담당자가 없는 첫 항목이며
  Map의 순서를 따른다.
- Claim은 `gh issue edit <number> --add-assignee @me`로 수행한다.
- Resolve는 결과 댓글 작성, 이슈 종료, Map의 Decisions-so-far에
  요약과 링크 추가 순서로 수행한다.
