"""
Turso database package — mixin-based architecture.

TursoDatabase composes domain-specific mixins via multiple inheritance.
All consumers should use `from turso_db import get_database` (backward-compat shim)
or `from db import get_database`.
"""

import streamlit as st

from db._core import ConnectionMixin
from db._schema import SchemaMixin
from db._operators import OperatorsMixin
from db._cache import CacheMixin
from db._usage import UsageMixin
from db._templates import TemplatesMixin
from db._queries import QueryHistoryMixin
from db._company_ids import CompanyIdMixin
from db._outcomes import OutcomesMixin
from db._staged import StagedExportsMixin
from db._pipeline import PipelineRunsMixin
from db._metadata import MetadataMixin
from db._error_log import ErrorLogMixin
from db._title_prefs import TitlePrefsMixin


class TursoDatabase(
    ConnectionMixin,
    SchemaMixin,
    OperatorsMixin,
    CacheMixin,
    UsageMixin,
    TemplatesMixin,
    QueryHistoryMixin,
    CompanyIdMixin,
    OutcomesMixin,
    StagedExportsMixin,
    PipelineRunsMixin,
    MetadataMixin,
    ErrorLogMixin,
    TitlePrefsMixin,
):
    """Turso database connection manager."""

    pass


@st.cache_resource(ttl=3600)  # Refresh connection every hour to prevent stale connections
def get_database() -> TursoDatabase:
    """Get cached database instance from Streamlit secrets."""
    db = TursoDatabase(
        url=st.secrets["TURSO_DATABASE_URL"],
        auth_token=st.secrets["TURSO_AUTH_TOKEN"],
    )
    db.init_schema()
    return db
