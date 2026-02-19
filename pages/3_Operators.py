"""
Operators - Manage operator metadata.
Superhuman-inspired: clean, focused, inline editing.
"""

import streamlit as st
import streamlit_shadcn_ui as ui
from turso_db import get_database
from ui_components import inject_base_styles, page_header, paginate_items, pagination_controls, empty_state, labeled_divider

st.set_page_config(page_title="Operators", page_icon="👤", layout="wide")

# Apply design system styles
inject_base_styles()

from utils import require_auth
require_auth()


# Initialize
@st.cache_resource
def get_db():
    return get_database()


def has_zoho_credentials() -> bool:
    """Check if Zoho credentials are configured."""
    try:
        return all([
            st.secrets.get("ZOHO_CLIENT_ID"),
            st.secrets.get("ZOHO_CLIENT_SECRET"),
            st.secrets.get("ZOHO_REFRESH_TOKEN"),
        ])
    except Exception:
        return False


try:
    db = get_db()
except Exception as e:
    st.error(f"Failed to connect: {e}")
    st.stop()


# Session state
if "operators_editing_id" not in st.session_state:
    st.session_state.operators_editing_id = None
if "operators_adding" not in st.session_state:
    st.session_state.operators_adding = False


# =============================================================================
# HEADER
# =============================================================================
operators = db.get_operators()

page_header(
    "Operators",
    "Manage operators for lead assignment",
    right_content=(f'<span style="font-family: var(--font-mono); font-size: 1.25rem; font-weight: 600; color: #f0f2f5;">{len(operators)}</span>', f"{len(operators):,} operators"),
)

st.markdown("---")


# =============================================================================
# ZOHO SYNC
# =============================================================================
with st.expander("Sync from Zoho CRM", expanded=False):
    if not has_zoho_credentials():
        st.warning("Zoho credentials not configured")
        st.caption("Add ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN to secrets.toml")
    else:
        # Show last sync info
        from zoho_sync import get_last_sync_time
        last_sync = get_last_sync_time(db)

        synced_ops = [op for op in operators if op.get("synced_at")]

        if last_sync:
            st.caption(f"Last sync: {last_sync[:16].replace('T', ' ')} UTC ({len(synced_ops)} synced operators)")
        else:
            st.caption("Never synced - will perform full sync")

        btn_col1, btn_col2 = st.columns(2)

        with btn_col1:
            sync_clicked = st.button("Sync Changes", type="primary", key="op_sync_btn")
        with btn_col2:
            _resync_trigger = st.button("Full Resync", key="op_resync_btn")
            st.caption("Full Resync replaces all records")

        _resync_confirmed = ui.alert_dialog(
            show=_resync_trigger,
            title="Full Resync",
            description="This will fetch all records from Zoho CRM. This may take a while.",
            confirm_label="Resync",
            cancel_label="Cancel",
            key="op_resync_dialog",
        )

        if sync_clicked:
            with st.spinner("Syncing from Zoho CRM..."):
                try:
                    from zoho_auth import ZohoAuth
                    from zoho_sync import run_sync

                    auth = ZohoAuth.from_streamlit_secrets(st.secrets)
                    result = run_sync(db, auth, force_full=False)

                    sync_type = result.get('sync_type', 'unknown')
                    if result['total_zoho'] == 0 and sync_type == 'incremental':
                        st.info("No changes since last sync")
                    else:
                        msg = f"{sync_type.title()} sync: "
                        parts = []
                        if result['created']:
                            parts.append(f"{result['created']} created")
                        if result['updated']:
                            parts.append(f"{result['updated']} updated")
                        if result['linked']:
                            parts.append(f"{result['linked']} linked")
                        if result['skipped']:
                            parts.append(f"{result['skipped']} skipped")
                        st.success(msg + ", ".join(parts) if parts else msg + "no changes")
                    st.rerun()
                except Exception as e:
                    st.error(f"Sync failed: {e}")

        if _resync_confirmed:
            with st.spinner("Full resync from Zoho CRM..."):
                try:
                    from zoho_auth import ZohoAuth
                    from zoho_sync import run_sync

                    auth = ZohoAuth.from_streamlit_secrets(st.secrets)
                    result = run_sync(db, auth, force_full=True)

                    parts = []
                    if result['created']:
                        parts.append(f"{result['created']} created")
                    if result['updated']:
                        parts.append(f"{result['updated']} updated")
                    if result['linked']:
                        parts.append(f"{result['linked']} linked")
                    if result['skipped']:
                        parts.append(f"{result['skipped']} skipped")
                    st.success(f"Full sync: " + (", ".join(parts) if parts else "no changes"))
                    st.rerun()
                except Exception as e:
                    st.error(f"Sync failed: {e}")

st.markdown("---")


# =============================================================================
# SEARCH
# =============================================================================
search_query = st.text_input(
    "Search operators",
    placeholder="Search by name, business, phone, email, ZIP, or website...",
    label_visibility="collapsed",
)

# Filter operators based on search
if search_query:
    query_lower = search_query.lower()
    filtered_operators = [
        op for op in operators
        if query_lower in (op["operator_name"] or "").lower()
        or query_lower in (op["vending_business_name"] or "").lower()
        or query_lower in (op["operator_phone"] or "").lower()
        or query_lower in (op["operator_email"] or "").lower()
        or query_lower in (op["operator_zip"] or "").lower()
        or query_lower in (op.get("operator_website") or "").lower()
    ]
    st.caption(f"Showing {len(filtered_operators)} of {len(operators)} operators")
else:
    filtered_operators = operators

st.markdown("---")


# =============================================================================
# ADD BUTTON
# =============================================================================
if not st.session_state.operators_adding:
    if ui.button(text="+ Add operator", variant="default", key="op_add_btn"):
        st.session_state.operators_adding = True
        st.rerun()


# =============================================================================
# ADD FORM
# =============================================================================
if st.session_state.operators_adding:
    st.subheader("New operator")

    col1, col2 = st.columns(2)

    with col1:
        new_name = st.text_input("Name", placeholder="John Smith")
        new_business = st.text_input("Business", placeholder="ABC Vending")
        new_phone = st.text_input("Phone", placeholder="(555) 123-4567")
        new_website = st.text_input("Website", placeholder="https://abcvending.com")

    with col2:
        new_zip = st.text_input("ZIP", placeholder="75201")
        new_team = st.text_input("Team", placeholder="North Texas")
        new_email = st.text_input("Email", placeholder="john@abc.com")

    col1, col2, col3 = st.columns([1, 1, 2])

    with col1:
        if ui.button(text="Save", variant="default", key="op_save_new_btn"):
            if not new_name:
                st.error("Name required")
            else:
                try:
                    db.create_operator(
                        operator_name=new_name,
                        vending_business_name=new_business or None,
                        operator_phone=new_phone or None,
                        operator_email=new_email or None,
                        operator_zip=new_zip or None,
                        operator_website=new_website or None,
                        team=new_team or None,
                    )
                    st.session_state.operators_adding = False
                    st.toast(f"Operator '{new_name}' created")
                    st.rerun()
                except Exception as e:
                    if "UNIQUE" in str(e):
                        st.error("Operator already exists")
                    else:
                        st.error(str(e))

    with col2:
        if ui.button(text="Cancel", variant="outline", key="op_cancel_new_btn"):
            st.session_state.operators_adding = False
            st.rerun()

    st.markdown("---")


# =============================================================================
# OPERATOR LIST
# =============================================================================
if not filtered_operators:
    if search_query:
        empty_state("No operators match your search", icon="🔍", hint="Try a different search term.")
    else:
        empty_state("No operators yet", icon="👤", hint="Click '+ Add operator' to create your first operator.")
else:
    # Paginate the operator list
    page_items, current_page, total_pages = paginate_items(filtered_operators, page_size=20, page_key="operators_page")
    st.caption(f"Showing {(current_page - 1) * 20 + 1}–{min(current_page * 20, len(filtered_operators))} of {len(filtered_operators):,} operators")

    for op in page_items:
        is_editing = st.session_state.operators_editing_id == op["id"]

        if is_editing:
            # Edit mode
            col1, col2 = st.columns(2)

            with col1:
                edit_name = st.text_input("Name", value=op["operator_name"], key=f"name_{op['id']}")
                edit_business = st.text_input("Business", value=op["vending_business_name"] or "", key=f"biz_{op['id']}")
                edit_phone = st.text_input("Phone", value=op["operator_phone"] or "", key=f"phone_{op['id']}")
                edit_website = st.text_input("Website", value=op["operator_website"] or "", key=f"web_{op['id']}")

            with col2:
                edit_zip = st.text_input("ZIP", value=op["operator_zip"] or "", key=f"zip_{op['id']}")
                edit_team = st.text_input("Team", value=op["team"] or "", key=f"team_{op['id']}")
                edit_email = st.text_input("Email", value=op["operator_email"] or "", key=f"email_{op['id']}")

            col1, col2, col3 = st.columns([1, 1, 2])

            with col1:
                if ui.button(text="Save", variant="default", key=f"op_save_edit_{op['id']}_btn"):
                    if not edit_name:
                        st.error("Name required")
                    else:
                        db.update_operator(
                            op["id"],
                            operator_name=edit_name,
                            vending_business_name=edit_business or None,
                            operator_phone=edit_phone or None,
                            operator_email=edit_email or None,
                            operator_zip=edit_zip or None,
                            operator_website=edit_website or None,
                            team=edit_team or None,
                        )
                        st.session_state.operators_editing_id = None
                        st.rerun()

            with col2:
                if ui.button(text="Cancel", variant="outline", key=f"op_cancel_edit_{op['id']}_btn"):
                    st.session_state.operators_editing_id = None
                    st.rerun()

        else:
            # Display mode - show all operator fields
            col1, col2, col3 = st.columns([4, 4, 2])

            with col1:
                st.markdown(f"**{op['operator_name']}**")
                st.caption(op["vending_business_name"] or "—")

            with col2:
                # Contact info
                contact_parts = []
                if op["operator_phone"]:
                    contact_parts.append(f"📞 {op['operator_phone']}")
                if op["operator_email"]:
                    contact_parts.append(f"✉️ {op['operator_email']}")
                if op["operator_zip"]:
                    contact_parts.append(f"📍 {op['operator_zip']}")
                if op.get("operator_website"):
                    contact_parts.append(f"🌐 {op['operator_website']}")

                if contact_parts:
                    st.caption("  ·  ".join(contact_parts))
                else:
                    st.caption("—")

            with col3:
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    if ui.button(text="Edit", variant="secondary", key=f"op_edit_{op['id']}_btn"):
                        st.session_state.operators_editing_id = op["id"]
                        st.rerun()
                with btn_col2:
                    _del_trigger = ui.button(text="Delete", variant="destructive", key=f"op_delete_{op['id']}_btn")
                    _del_confirmed = ui.alert_dialog(
                        show=_del_trigger,
                        title="Delete Operator",
                        description=f"Delete {op['operator_name']}? This action cannot be undone.",
                        confirm_label="Delete",
                        cancel_label="Cancel",
                        key=f"op_delete_{op['id']}_dialog",
                    )
                    if _del_confirmed:
                        try:
                            db.delete_operator(op["id"])
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to delete: {e}")

        st.markdown("---")
        st.markdown("")

    # Pagination controls at bottom
    if total_pages > 1:
        labeled_divider("Pages")
        pagination_controls(current_page, total_pages, page_key="operators_page")
