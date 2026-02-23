"""
Keyboard shortcuts PoC — Ctrl+Enter to click the primary submit button.

Uses st.components.v1.html() to inject JS that reaches Streamlit's DOM
from the iframe via window.parent.document.

Caveats:
- Fragile: depends on Streamlit DOM internals (button class names).
- May be blocked by CSP on Community Cloud.
- This is a PoC — proper shortcuts need a user story defining the target shortcuts.
"""

import streamlit.components.v1 as components


def inject_ctrl_enter_shortcut() -> None:
    """Inject Ctrl+Enter keyboard shortcut to click the primary submit button."""
    components.html(
        """
        <script>
        (function() {
            const doc = window.parent.document;
            if (doc._ctrlEnterInjected) return;
            doc._ctrlEnterInjected = true;
            doc.addEventListener('keydown', function(e) {
                if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                    // Find the primary-styled Streamlit button
                    const btn = doc.querySelector(
                        'button[kind="primary"], button.stButton > button[kind="secondary"]'
                    );
                    if (btn) {
                        btn.click();
                        e.preventDefault();
                    }
                }
            });
        })();
        </script>
        """,
        height=0,
        width=0,
    )
