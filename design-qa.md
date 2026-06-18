# Design QA

- source visual truth path: Browser Comment 1 attached customer-detail screenshot and attached `累计/计划/有效 14 / 0 / 14` reference image (conversation artifacts; no filesystem path exposed)
- implementation screenshot path: `/Users/w/ruijie/AI_cdp_git/ruijie-cdp/.codex-customer-950-followup-status.png`
- viewport: 1366 × 1151
- state: customer 950, overview tab, statistics request completed

## Full-view comparison evidence

The new statistic is placed inside the existing “跟进状态” card between “最近互动” and “偏好渠道”. The two-column detail grid, card padding, typography hierarchy, borders, colors, and surrounding content remain aligned with the source screen.

## Focused region comparison evidence

A separate crop was not needed because the full-view screenshot renders the complete card and the new `3 / 0 / 19` value legibly at the reference viewport.

## Findings

- No actionable P0/P1/P2 differences.
- Typography uses the existing small muted label and emphasized value styles.
- Spacing follows the card’s existing vertical rhythm.
- Colors and borders reuse existing design tokens.
- No image assets were added or changed.
- Copy matches the supplied `累计/计划/有效` reference.

## Patches made

- Added the by-name customer statistics request.
- Mapped the by-name API's total interactions to both “累计” and “有效”, with “计划” fixed at `0`.
- Added the statistic row without changing the surrounding card layout.
- Kept the statistics request non-blocking so an API timeout does not delay the customer detail screen.

final result: passed
