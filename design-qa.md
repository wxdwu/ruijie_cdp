# Design QA

- source visual truth path: Browser Comment 1 attached customer-list screenshot; light-theme palette source is `doc/ruijie-cdp-mvp-attribution-abm360-prototype_v10_full_Version2(1)_sample_based.html`
- implementation screenshot path: in-app browser live render at `http://localhost:3000/customers` (the screenshot capture endpoint timed out)
- viewport: browser viewport width 1404px; desktop state
- state: dark and light themes; customer list, campaign board, AI chat, and review queue routes

## Full-view comparison evidence

The global header preserves its existing height and layout. The theme button sits in the right action group before “通知” and “新建”. Dark mode retains the existing variables. Light mode uses the reference HTML’s warm cream-to-light-blue background, translucent white panels, cool gray borders, dark navy text, and blue brand color.

## Focused region comparison evidence

The in-app browser DOM and computed styles confirmed:

- dark mode: panel `rgba(12, 17, 28, 0.84)`, text `#edf2fb`
- light mode: panel `rgba(255, 255, 255, 0.84)`, text `#122033`
- customer header button label changes between “切换浅色主题” and “切换深色主题”
- the same button is present on `/customers`, `/campaign`, `/ai-chat`, and `/review`
- review-queue light mode contains no remaining large dark-background elements

## Findings

- No actionable P0/P1/P2 findings.
- Typography and spacing remain consistent with the current application.
- Light colors and background effects match the supplied reference variables.
- Existing visible assets and navigation icons are unchanged.
- Theme choice persists across route navigation and page reload.

## Patches made

- Added a persistent global theme state using `data-theme` and `localStorage`.
- Added the global header theme toggle.
- Added reference-derived light-theme variables and background gradients.
- Added compatibility variables for campaign and AI components.
- Added light-mode overrides for legacy hard-coded review-queue surfaces.
- Changed funnel-stage labels and values to dark text in light mode while preserving white text in dark mode.
- Increased light-mode contrast for the business-funnel chart labels, axes, legends, grid lines, and panel subtitles.
- Applied the same darker light-mode chart text treatment to the budget mix and output-versus-peers panels.

final result: passed
