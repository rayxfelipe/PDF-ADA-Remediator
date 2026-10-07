from __future__ import annotations

import html


APP_STYLES = """
:root {
  --color-primary: #1a4d8f;
  --color-primary-dark: #0d2740;
  --color-accent: #0b6e4f;
  --color-bg: #f5f7fa;
  --color-surface: #fff;
  --color-text: #1c1c1c;
  --color-muted: #5a5f66;
  --color-border: #d5dbe3;
  --color-error: #b3261e;
  --color-warning: #8a5700;
  --color-manual: #5f3b91;
  --focus-ring: #ffb703;
  --radius: 10px;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
[hidden] { display: none !important; }
body {
  margin: 0;
  background: var(--color-bg);
  color: var(--color-text);
  font: 16px/1.5 "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
a { color: var(--color-primary); }
.container { width: min(1120px, calc(100% - 3rem)); margin: 0 auto; }
.skip-link { position: absolute; left: -999px; top: 0; background: #fff; padding: .75rem 1rem; z-index: 100; }
.skip-link:focus { left: 1rem; top: 1rem; }
.app-header { padding: 2rem 0; color: #fff; background: var(--color-primary); }
.app-header h1 { margin: 0 0 .25rem; font-size: clamp(1.7rem, 4vw, 2.15rem); line-height: 1.15; }
.tagline { margin: 0; opacity: .9; }
main.container { padding-top: 2rem; padding-bottom: 3rem; }
.upload-card, .status-card, .report-card, .finding {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
}
.upload-card { max-width: 860px; margin: 0 auto; padding: 1.75rem; }
.upload-card h2 { margin-top: 0; }
.hint, .file, code { color: var(--color-muted); overflow-wrap: anywhere; }
.dropzone {
  position: relative;
  padding: 2.5rem 1.5rem;
  text-align: center;
  cursor: pointer;
  border: 2px dashed var(--color-border);
  border-radius: var(--radius);
  transition: border-color .15s ease, background-color .15s ease;
}
.dropzone:hover, .dropzone.dragover { border-color: var(--color-primary); background: #eef3fb; }
.dropzone input[type="file"] { position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer; }
.dropzone:focus-visible, button:focus-visible, .button:focus-visible, .report-nav a:focus-visible {
  outline: 3px solid var(--focus-ring);
  outline-offset: 2px;
}
.link-text { color: var(--color-primary); font-weight: 650; text-decoration: underline; }
.file-name { min-height: 1.25rem; margin: .75rem 0 0; font-weight: 650; }
.button, button {
  display: inline-block;
  padding: .72rem 1.35rem;
  border: 2px solid transparent;
  border-radius: 8px;
  background: var(--color-accent);
  color: #fff;
  font: inherit;
  font-weight: 650;
  text-decoration: none;
  cursor: pointer;
}
button { margin-top: 1.25rem; }
.button:hover, button:not(:disabled):hover { background: #08573e; }
button:disabled { background: #9aa3ad; cursor: not-allowed; }
.button.secondary { background: #fff; color: var(--color-primary); border-color: var(--color-primary); }
.button.secondary:hover { background: #eef3fb; }
.error-message { color: var(--color-error); font-weight: 650; }
.status-card { display: flex; align-items: center; gap: 1rem; max-width: 860px; margin: 1.5rem auto 0; padding: 1.25rem 1.75rem; }
.spinner { width: 28px; height: 28px; flex: 0 0 auto; border: 3px solid var(--color-border); border-top-color: var(--color-primary); border-radius: 50%; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.audit-dashboard { overflow: hidden; background: #f4f7fb; border: 1px solid var(--color-border); border-radius: 12px; box-shadow: 0 8px 28px rgb(16 42 67 / 10%); }
.report-hero { padding: 2rem clamp(1.25rem, 4vw, 3.5rem); color: #fff; background: linear-gradient(115deg, var(--color-primary-dark), #164f80); }
.report-hero h2 { margin: .3rem 0 .4rem; font-size: clamp(1.8rem, 4vw, 2.8rem); line-height: 1.1; }
.report-eyebrow { margin: 0; color: #b9d9ff; font-size: .78rem; font-weight: 750; letter-spacing: .12em; text-transform: uppercase; }
.report-hero .file { margin: 0; color: #e3efff; }
.report-nav { position: sticky; top: 0; z-index: 10; display: flex; gap: .4rem; overflow-x: auto; padding: 0 clamp(1.25rem, 4vw, 3.5rem); white-space: nowrap; background: #fff; border-bottom: 1px solid #d8e0ea; }
.report-nav a { padding: .85rem .75rem; color: #334e68; font-weight: 650; text-decoration: none; }
.report-nav a:hover { background: #eaf2ff; }
.report-content { padding: clamp(1.25rem, 4vw, 3.5rem); }
.report-section { margin-top: 1.75rem; scroll-margin-top: 4rem; }
.report-section:first-child { margin-top: 0; }
.report-section > h3 { margin: 0 0 .85rem; color: #172b4d; font-size: 1.45rem; }
.report-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 1rem; }
.report-card { padding: 1.25rem; box-shadow: 0 4px 15px rgb(22 50 79 / 5%); }
.report-kpi { border-top: 5px solid var(--color-primary); }
.report-kpi.pass { border-top-color: #067647; }
.report-kpi.fail { border-top-color: #b42318; }
.report-kpi.warning { border-top-color: #d97706; }
.report-kpi.manual { border-top-color: #718096; }
.report-kpi strong, .report-kpi span { display: block; }
.report-kpi strong { font-size: 2rem; line-height: 1.1; }
.report-kpi span { margin-top: .25rem; color: #5f6c7b; font-weight: 650; }
.report-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
.finding { padding: 1.1rem 1.3rem; border-left: 6px solid var(--color-border); box-shadow: 0 4px 15px rgb(22 50 79 / 5%); }
.finding.pass, .finding.success, .finding.passed { border-left-color: #067647; }
.finding.fail, .finding.failed { border-left-color: #b42318; }
.finding.warning { border-left-color: #d97706; }
.finding.manual { border-left-color: var(--color-manual); }
.finding-head { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; }
.finding h4 { margin: .65rem 0 .35rem; font-size: 1.1rem; }
.finding p { margin: .38rem 0; }
.badge, .severity { display: inline-block; padding: .17rem .62rem; border-radius: 999px; font-size: .76rem; font-weight: 800; }
.badge { background: #e8edf4; }
.pass .badge, .success .badge, .passed .badge { background: #d9f3e7; color: #0f5a39; }
.fail .badge, .failed .badge { background: #fde3e1; color: #841d19; }
.warning .badge { background: #fff0cb; color: #724700; }
.manual .badge { background: #eee4fa; color: #503078; }
.severity { border: 1px solid var(--color-border); }
.check-id { color: var(--color-muted); font-size: .76rem; font-weight: 750; letter-spacing: .05em; text-transform: uppercase; }
.notice { border-left: 5px solid var(--color-warning); }
.action { border-left: 5px solid var(--color-accent); }
.action form { margin: 0; }
.action button { margin-bottom: 0; }
.metadata { margin: 0; }
.metadata > div + div { margin-top: .8rem; padding-top: .8rem; border-top: 1px solid var(--color-border); }
.metadata dt { color: #334e68; font-weight: 750; }
.metadata dd { margin: .2rem 0 0; overflow-wrap: anywhere; }
.report-actions { display: flex; flex-wrap: wrap; gap: .75rem; margin-top: 1rem; }
.app-footer { padding: 1.5rem 0; color: var(--color-muted); background: #fff; border-top: 1px solid var(--color-border); }
.app-footer p { margin: 0; }
@media (max-width: 760px) {
  .container { width: min(100% - 2rem, 1120px); }
  .report-grid { grid-template-columns: 1fr; }
  .report-content { padding: 1.25rem; }
}
@media print {
  body { background: #fff; }
  .skip-link, .app-header, .report-nav, .report-actions, .action, .app-footer { display: none; }
  main.container { width: 100%; padding: 0; }
  .audit-dashboard, .report-card, .finding { border-color: #aaa; box-shadow: none; break-inside: avoid; }
}
"""


def app_header(title: str, tagline: str) -> str:
    return (
        '<a class="skip-link" href="#main-content">Skip to main content</a>'
        '<header class="app-header"><div class="container">'
        f"<h1>{html.escape(title)}</h1><p class=\"tagline\">{html.escape(tagline)}</p>"
        "</div></header>"
    )


def app_footer() -> str:
    return (
        '<footer class="app-footer"><div class="container">'
        "<p>Deterministic PDF accessibility screening and remediation.</p>"
        "</div></footer>"
    )
