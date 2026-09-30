"""OpenBagus Reporting Package.

Provides renderers for briefs, dashboards, HTML email reports, and printable views.
"""

from openbagus.reporting.brief import render_crypto_brief, render_macro_brief
from openbagus.reporting.dashboard import PwaDashboardRenderer
from openbagus.reporting.email import render_email_report
from openbagus.reporting.pdf import render_pdf_report

__all__ = [
    "render_crypto_brief",
    "render_macro_brief",
    "PwaDashboardRenderer",
    "render_email_report",
    "render_pdf_report",
]
