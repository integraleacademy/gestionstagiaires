from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
GLOBAL_PARTIAL = (ROOT / "templates" / "_mail_sent_badge.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "responsive.css").read_text(encoding="utf-8")
JS = (ROOT / "static" / "responsive.js").read_text(encoding="utf-8")


def test_mobile_viewport_and_global_assets_are_enabled():
    assert 'name="viewport" content="width=device-width,initial-scale=1"' in BASE
    assert "responsive.css" in GLOBAL_PARTIAL
    assert "responsive.js" in GLOBAL_PARTIAL
    assert "20260823-responsive-platform" in GLOBAL_PARTIAL


def test_mobile_shell_forms_and_actions_have_global_breakpoints():
    assert "@media (max-width: 980px)" in CSS
    assert "@media (max-width: 720px)" in CSS
    assert ".main-content" in CSS
    assert ".topbar-inner" in CSS
    assert ".form-grid" in CSS
    assert ".btn-row" in CSS
    assert "grid-template-columns:minmax(0,1fr) !important" in CSS
    assert "min-height:44px" in CSS


def test_wide_tables_scroll_locally_and_phone_sticky_columns_are_released():
    assert ".responsive-table-scroll" in CSS
    assert "overflow-x:auto" in CSS
    assert "-webkit-overflow-scrolling:touch" in CSS
    assert "#traineesTable .col-last-name" in CSS
    assert "position:static !important" in CSS
    assert "wrapResponsiveTables" in JS
    assert ".table-wrap, .partners-table-wrap, .comparison-card, .responsive-table-scroll" in JS
    assert "Tableau défilable horizontalement" in JS


def test_mobile_modals_remain_inside_the_viewport():
    assert ".modal-backdrop" in CSS
    assert ".billing-modal-overlay" in CSS
    assert ".app-modal-backdrop" in CSS
    assert "max-height:calc(100dvh - 16px) !important" in CSS
    assert ".modal-foot" in CSS
    assert "flex-direction:column-reverse" in CSS


def test_sidebar_can_be_closed_with_escape_and_state_is_cleaned():
    assert "function closeMobileSidebar" in JS
    assert "sidebar.classList.remove('is-open')" in JS
    assert "overlay?.classList.remove('is-open')" in JS
    assert "document.body.classList.remove('partner-sidebar-open')" in JS
    assert "event.key === 'Escape'" in JS
    assert "aria-expanded', 'false'" in JS
