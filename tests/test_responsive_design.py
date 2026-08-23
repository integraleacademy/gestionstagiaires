import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
GLOBAL_PARTIAL = (ROOT / "templates" / "_mail_sent_badge.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "responsive.css").read_text(encoding="utf-8")
JS = (ROOT / "static" / "responsive.js").read_text(encoding="utf-8")
CSS_V2 = (ROOT / "static" / "responsive-v2.css").read_text(encoding="utf-8")
JS_V2 = (ROOT / "static" / "responsive-v2.js").read_text(encoding="utf-8")


def _run_node(script: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js indisponible dans cet environnement")
    completed = subprocess.run(
        [node, "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_mobile_viewport_and_global_assets_are_enabled():
    assert 'name="viewport" content="width=device-width,initial-scale=1"' in BASE
    assert "responsive.css" in GLOBAL_PARTIAL
    assert "responsive.js" in GLOBAL_PARTIAL
    assert "responsive-v2.css" in GLOBAL_PARTIAL
    assert "responsive-v2.js" in GLOBAL_PARTIAL
    assert "20260823-responsive-platform-v2" in GLOBAL_PARTIAL


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


def test_v2_adds_mobile_readability_safe_areas_and_touch_contract():
    assert "overflow-wrap:anywhere" in CSS_V2
    assert "env(safe-area-inset-bottom)" in CSS_V2
    assert "body.responsive-sidebar-lock" in CSS_V2
    assert "table.responsive-card-table" in CSS_V2
    assert "content:attr(data-label)" in CSS_V2
    assert "min-height:44px" in CSS_V2
    assert "orientation: landscape" in CSS_V2
    assert "prefers-reduced-motion: reduce" in CSS_V2


def test_v2_card_classifier_is_conservative_and_behavioral():
    result = _run_node(
        """
        const api = require('./static/responsive-v2.js');
        const base = {headerCount:4,rowCount:3,rowCellCounts:[4,4,4],excluded:false,hasEditable:false,hasComplexSpan:false,hasFooter:false};
        const cases = {
          simple: api.canCardifyShape(base),
          tooWide: api.canCardifyShape({...base, headerCount:9, rowCellCounts:[9,9,9]}),
          editable: api.canCardifyShape({...base, hasEditable:true}),
          complexSpan: api.canCardifyShape({...base, hasComplexSpan:true}),
          footer: api.canCardifyShape({...base, hasFooter:true}),
          mismatchedCells: api.canCardifyShape({...base, rowCellCounts:[4,3,4]}),
          tooManyRows: api.canCardifyShape({...base, rowCount:41, rowCellCounts:Array(41).fill(4)})
        };
        console.log(JSON.stringify(cases));
        """
    )
    assert result == {
        "simple": True,
        "tooWide": False,
        "editable": False,
        "complexSpan": False,
        "footer": False,
        "mismatchedCells": False,
        "tooManyRows": False,
    }


def test_v2_scroll_state_reports_start_middle_and_end():
    result = _run_node(
        """
        const api = require('./static/responsive-v2.js');
        console.log(JSON.stringify({
          fitted: api.computeScrollState({scrollWidth:320,clientWidth:320,scrollLeft:0}),
          start: api.computeScrollState({scrollWidth:900,clientWidth:320,scrollLeft:0}),
          middle: api.computeScrollState({scrollWidth:900,clientWidth:320,scrollLeft:250}),
          end: api.computeScrollState({scrollWidth:900,clientWidth:320,scrollLeft:580})
        }));
        """
    )
    assert result["fitted"] == {"scrollable": False, "atStart": True, "atEnd": True}
    assert result["start"] == {"scrollable": True, "atStart": True, "atEnd": False}
    assert result["middle"] == {"scrollable": True, "atStart": False, "atEnd": False}
    assert result["end"] == {"scrollable": True, "atStart": False, "atEnd": True}


def test_v2_dynamic_tables_and_sidebar_focus_are_wired_to_runtime_state():
    assert "MutationObserver" in JS_V2
    assert "ResizeObserver" in JS_V2
    assert "dataset.label" in JS_V2
    assert "#traineesTable" in JS_V2
    assert "aria-description" in JS_V2
    assert "responsive-sidebar-lock" in JS_V2
    assert "window.scrollTo(0, sidebarScrollY)" in JS_V2
    assert "event.key !== 'Tab'" in JS_V2
    assert "sidebarOpener" in JS_V2
