"""Native Microsoft Word (.docx) report generator with genuine editable Office charts.

Generates ECMA-376 / ISO/IEC 29500 compliant OpenXML packages:
- Pure Python standard library (zipfile, xml)
- True embedded Office DrawingML charts (c:chartSpace)
- Embedded Excel workbook (word/embeddings/Microsoft_Excel_Worksheet1.xlsx)
- Interactive 'Edit Data' support in Microsoft Word
- Professional research formatting: Decision, Scenarios, Fundamentals, Ownership, and Sources
"""

from __future__ import annotations

import io
import math
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from openbagus.domains.equities.ownership import OwnershipStructure


def get_reports_dir(root: Path | None = None) -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        p = Path(local_app_data) / "OpenBagus" / "reports"
    elif root:
        p = root / "reports"
    else:
        p = Path("reports")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _create_embedded_xlsx(sheet_title: str, categories: list[str], series_name: str, values: list[float]) -> bytes:
    """Builds a minimal, valid OpenXML Excel workbook (.xlsx) matching the chart dataset."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # [Content_Types].xml
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
            '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
            '  <Default Extension="xml" ContentType="application/xml"/>\n'
            '  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>\n'
            '  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>\n'
            "</Types>",
        )

        # _rels/.rels
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>\n'
            "</Relationships>",
        )

        # xl/_rels/workbook.xml.rels
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>\n'
            "</Relationships>",
        )

        # xl/workbook.xml
        z.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">\n'
            "  <sheets>\n"
            f'    <sheet name="{escape(sheet_title)}" sheetId="1" r:id="rId1"/>\n'
            "  </sheets>\n"
            "</workbook>",
        )

        # xl/worksheets/sheet1.xml
        rows_xml = [
            '    <row r="1">',
            f'      <c r="A1" t="inlineStr"><is><t>Category</t></is></c>',
            f'      <c r="B1" t="inlineStr"><is><t>{escape(series_name)}</t></is></c>',
            "    </row>",
        ]
        for idx, (cat, val) in enumerate(zip(categories, values), start=2):
            rows_xml.append(
                f'    <row r="{idx}">\n'
                f'      <c r="A{idx}" t="inlineStr"><is><t>{escape(cat)}</t></is></c>\n'
                f'      <c r="B{idx}"><v>{val}</v></c>\n'
                f"    </row>"
            )

        z.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">\n'
            f'  <dimension ref="A1:B{len(categories)+1}"/>\n'
            "  <sheetData>\n" + "\n".join(rows_xml) + "\n  </sheetData>\n"
            "</worksheet>",
        )

    return buf.getvalue()


def _create_chart_xml(chart_title: str, categories: list[str], series_name: str, values: list[float]) -> str:
    """Creates DrawingML chart XML with externalData linkage to the embedded workbook."""
    cat_items = []
    for idx, c in enumerate(categories):
        cat_items.append(f'<c:pt idx="{idx}"><c:v>{escape(c)}</c:v></c:pt>')

    val_items = []
    for idx, v in enumerate(values):
        val_items.append(f'<c:pt idx="{idx}"><c:v>{v}</c:v></c:pt>')

    num_pts = len(categories)

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">\n'
        "  <c:chart>\n"
        "    <c:title>\n"
        "      <c:tx>\n"
        "        <c:rich>\n"
        "          <a:bodyPr/>\n"
        "          <a:lstStyle/>\n"
        f"          <a:p><a:r><a:t>{escape(chart_title)}</a:t></a:r></a:p>\n"
        "        </c:rich>\n"
        "      </c:tx>\n"
        '      <c:layout/>\n'
        "    </c:title>\n"
        "    <c:plotArea>\n"
        "      <c:layout/>\n"
        "      <c:barChart>\n"
        '        <c:barDir val="col"/>\n'
        '        <c:grouping val="clustered"/>\n'
        '        <c:varyColors val="0"/>\n'
        "        <c:ser>\n"
        '          <c:idx val="0"/>\n'
        '          <c:order val="0"/>\n'
        f"          <c:tx><c:v>{escape(series_name)}</c:v></c:tx>\n"
        "          <c:cat>\n"
        "            <c:strRef>\n"
        f"              <c:f>Sheet1!$A$2:$A${num_pts+1}</c:f>\n"
        "              <c:strData>\n"
        f'                <c:ptCount val="{num_pts}"/>\n'
        + "\n".join(cat_items)
        + "\n              </c:strData>\n"
        "            </c:strRef>\n"
        "          </c:cat>\n"
        "          <c:val>\n"
        "            <c:numRef>\n"
        f"              <c:f>Sheet1!$B$2:$B${num_pts+1}</c:f>\n"
        "              <c:numData>\n"
        '                <c:formatCode>General</c:formatCode>\n'
        f'                <c:ptCount val="{num_pts}"/>\n'
        + "\n".join(val_items)
        + "\n              </c:numData>\n"
        "            </c:numRef>\n"
        "          </c:val>\n"
        "        </c:ser>\n"
        '        <c:axId val="1001"/>\n'
        '        <c:axId val="1002"/>\n'
        "      </c:barChart>\n"
        "      <c:catAx>\n"
        '        <c:axId val="1001"/>\n'
        "        <c:scaling><c:orientation val=\"minMax\"/></c:scaling>\n"
        '        <c:delete val="0"/>\n'
        '        <c:axPos val="b"/>\n'
        '        <c:crossAx val="1002"/>\n'
        '        <c:tickLblPos val="nextTo"/>\n'
        "      </c:catAx>\n"
        "      <c:valAx>\n"
        '        <c:axId val="1002"/>\n'
        "        <c:scaling><c:orientation val=\"minMax\"/></c:scaling>\n"
        '        <c:delete val="0"/>\n'
        '        <c:axPos val="l"/>\n'
        '        <c:crossAx val="1001"/>\n'
        '        <c:tickLblPos val="nextTo"/>\n'
        "      </c:valAx>\n"
        "    </c:plotArea>\n"
        '    <c:plotVisOnly val="1"/>\n'
        "  </c:chart>\n"
        '  <c:externalData r:id="rId1">\n'
        '    <c:autoUpdate val="0"/>\n'
        "  </c:externalData>\n"
        "</c:chartSpace>"
    )


def generate_word_report(
    asset: str,
    quant_result: Any = None,
    packet: Any = None,
    ownership: OwnershipStructure | None = None,
    backtest_result: Any = None,
    root: Path | None = None,
    timeframe: str = "D1",
) -> Path:
    """Creates a professional .docx report with genuine, editable DrawingML Office charts."""
    reports_dir = get_reports_dir(root)
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    file_path = reports_dir / f"{asset}_{timeframe}_{timestamp_str}_Report.docx"

    decision = getattr(quant_result, "decision", "RESEARCH")
    decision_reason = getattr(quant_result, "decision_reason", "Quantitative analysis")
    price_val = getattr(quant_result, "price", 0.0)
    price_str = f"Rp{price_val:,.0f}" if price_val else "DATA GAP"

    # Determine chart dataset (Financial Ratios or Ownership Breakdown)
    has_chart = False
    chart_title = ""
    categories: list[str] = []
    series_name = ""
    values: list[float] = []

    if ownership and ownership.top_shareholders:
        has_chart = True
        chart_title = f"{asset} Shareholder Distribution (%)"
        categories = [s.shareholder[:16] for s in ownership.top_shareholders]
        if ownership.public_shareholders_pct > 0:
            categories.append("Public (<5%)")
        series_name = "Ownership %"
        values = [round(s.percentage, 2) for s in ownership.top_shareholders]
        if ownership.public_shareholders_pct > 0:
            values.append(round(ownership.public_shareholders_pct, 2))
    elif packet and getattr(packet, "fundamentals", None) and packet.fundamentals.get("ratios"):
        ratios = packet.fundamentals["ratios"]
        if len(ratios) >= 2:
            has_chart = True
            chart_title = f"{asset} Key Financial Ratios (%)"
            categories = list(ratios.keys())[:6]
            series_name = "Reported %"
            values = [round(float(ratios[k]), 2) for k in categories]

    # Generate embedded Excel workbook and DrawingML chart if verified data exists
    xlsx_bytes: bytes | None = None
    chart_xml: str | None = None
    if has_chart:
        xlsx_bytes = _create_embedded_xlsx("Sheet1", categories, series_name, values)
        chart_xml = _create_chart_xml(chart_title, categories, series_name, values)

    # Document paragraphs and tables
    p_entries = [
        f'<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="48"/><w:color w:val="0F4C81"/></w:rPr><w:t>OpenBagus Quantitative Research Report</w:t></w:r></w:p>',
        f'<w:p><w:r><w:rPr><w:i/><w:color w:val="595959"/></w:rPr><w:t>Asset: {escape(asset)} | Timeframe: {timeframe} | Generated: {timestamp_str} UTC</w:t></w:r></w:p>',
        '<w:p/>',
        f'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="32"/><w:color w:val="0F4C81"/></w:rPr><w:t>1. Executive Summary &amp; Decision</w:t></w:r></w:p>',
        f'<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Action: </w:t></w:r><w:r><w:rPr><w:b/><w:color w:val="2E7D32"/></w:rPr><w:t>{escape(decision)}</w:t></w:r><w:r><w:t> at {price_str}</w:t></w:r></w:p>',
        f'<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Decision Rationale: </w:t></w:r><w:r><w:t>{escape(decision_reason)}</w:t></w:r></w:p>',
        '<w:p/>',
        f'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="32"/><w:color w:val="0F4C81"/></w:rPr><w:t>2. Trade Geometry &amp; Risk Scenarios</w:t></w:r></w:p>',
    ]

    if quant_result and getattr(quant_result, "bullish_validation", None):
        s = quant_result.bullish_validation
        p_entries.append(
            f'<w:p><w:r><w:t>Bullish Scenario: {escape(s.trigger_condition)}. Entry Zone: {escape(s.entry_zone)}, Invalidation Stop: Rp{s.stop_price:,.0f}, Target: Rp{s.tp1:,.0f}. Net Reward:Risk: {escape(s.reward_risk_str)}.</w:t></w:r></w:p>'
        )
    else:
        p_entries.append(
            f'<w:p><w:r><w:t>Active breakout setup is currently unconfirmed. Standing structural levels provide boundary discipline.</w:t></w:r></w:p>'
        )

    if has_chart:
        p_entries.extend([
            '<w:p/>',
            f'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="32"/><w:color w:val="0F4C81"/></w:rPr><w:t>3. Visual Intelligence (Editable Office Chart)</w:t></w:r></w:p>',
            f'<w:p><w:r><w:t>The following chart is an embedded, native Office chart with direct Excel spreadsheet linkage:</w:t></w:r></w:p>',
            '<w:p>'
            '  <w:r>'
            '    <w:drawing>'
            '      <wp:inline distT="0" distB="0" distL="0" distR="0">'
            '        <wp:extent cx="5486400" cy="3200400"/>'
            '        <wp:docPr id="1" name="Chart 1"/>'
            '        <a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '          <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart">'
            '            <c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
            '                     xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            '                     r:id="rId1"/>'
            '          </a:graphicData>'
            '        </a:graphic>'
            '      </wp:inline>'
            '    </w:drawing>'
            '  </w:r>'
            '</w:p>',
            '<w:p/>',
        ])
    else:
        p_entries.extend([
            '<w:p/>',
            f'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="32"/><w:color w:val="0F4C81"/></w:rPr><w:t>3. Visual Intelligence &amp; Quantitative Summary</w:t></w:r></w:p>',
            f'<w:p><w:r><w:rPr><w:i/><w:color w:val="595959"/></w:rPr><w:t>Chart Omitted: No multi-holder shareholder filing or audited financial ratio dataset available to construct an editable Office chart without synthetic assumptions. Quantitative levels are summarized below:</w:t></w:r></w:p>',
            '<w:tbl>',
            '  <w:tblPr><w:tblBorders><w:top w:val="single" w:sz="4" w:color="D3D3D3"/><w:bottom w:val="single" w:sz="4" w:color="D3D3D3"/><w:insideH w:val="single" w:sz="4" w:color="EEEEEE"/></w:tblBorders></w:tblPr>',
            '  <w:tblGrid><w:gridCol w:w="4680"/><w:gridCol w:w="4680"/></w:tblGrid>',
            '  <w:tr><w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Dimension</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Value</w:t></w:r></w:p></w:tc></w:tr>',
            f'  <w:tr><w:tc><w:p><w:r><w:t>Action</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>{escape(decision)}</w:t></w:r></w:p></w:tc></w:tr>',
            f'  <w:tr><w:tc><w:p><w:r><w:t>Price</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>{price_str}</w:t></w:r></w:p></w:tc></w:tr>',
            f'  <w:tr><w:tc><w:p><w:r><w:t>Market Regime</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>{escape(getattr(quant_result, "regime", "N/A"))}</w:t></w:r></w:p></w:tc></w:tr>',
            '</w:tbl>',
            '<w:p/>',
        ])

    if ownership:
        dom_str = f"{ownership.domestic_pct:.2f}%" if ownership.domestic_pct is not None else "N/A"
        for_str = f"{ownership.foreign_pct:.2f}%" if ownership.foreign_pct is not None else "N/A"
        p_entries.extend([
            f'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="32"/><w:color w:val="0F4C81"/></w:rPr><w:t>4. Shareholder Ownership Disclosure</w:t></w:r></w:p>',
            f'<w:p><w:r><w:t>Domestic Ownership: {dom_str} | Foreign Ownership: {for_str}</w:t></w:r></w:p>',
            f'<w:p><w:r><w:t>Public Free Float (&lt;5%): {ownership.public_shareholders_pct:.2f}%</w:t></w:r></w:p>',
            f'<w:p><w:r><w:rPr><w:i/><w:color w:val="595959"/></w:rPr><w:t>{escape(ownership.denominator_explanation)}</w:t></w:r></w:p>',
            '<w:p/>',
        ])

    p_entries.extend([
        f'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="32"/><w:color w:val="0F4C81"/></w:rPr><w:t>5. Provenance &amp; Disclaimers</w:t></w:r></w:p>',
        f'<w:p><w:r><w:t>Data Freshness: {getattr(quant_result, "data_freshness", "UNVERIFIED")}. Sources: {escape("; ".join(getattr(quant_result, "sources", ["OpenBagus Engine"])))}.</w:t></w:r></w:p>',
        f'<w:p><w:r><w:rPr><w:i/><w:color w:val="7F7F7F"/></w:rPr><w:t>Notice: This report is for research and risk analysis only; not broker execution or financial advice.</w:t></w:r></w:p>',
    ])

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">\n'
        '  <w:body>\n'
        + "\n".join(p_entries)
        + '\n    <w:sectPr>\n'
        '      <w:pgSz w:w="12240" w:h="15840"/>\n'
        '      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>\n'
        '    </w:sectPr>\n'
        '  </w:body>\n'
        '</w:document>'
    )

    # Build final DOCX zip package
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # [Content_Types].xml
        content_types_overrides = [
            '  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>\n'
        ]
        if has_chart:
            content_types_overrides.extend([
                '  <Override PartName="/word/charts/chart1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>\n',
                '  <Override PartName="/word/embeddings/Microsoft_Excel_Worksheet1.xlsx" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"/>\n',
            ])

        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
            '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
            '  <Default Extension="xml" ContentType="application/xml"/>\n'
            + "".join(content_types_overrides)
            + "</Types>",
        )

        # _rels/.rels
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>\n'
            "</Relationships>",
        )

        # word/_rels/document.xml.rels
        doc_rels = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n',
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n',
        ]
        if has_chart:
            doc_rels.append('  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="charts/chart1.xml"/>\n')
        doc_rels.append("</Relationships>")
        z.writestr("word/_rels/document.xml.rels", "".join(doc_rels))

        # word/charts/_rels/chart1.xml.rels and chart parts
        if has_chart and chart_xml and xlsx_bytes:
            z.writestr(
                "word/charts/_rels/chart1.xml.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
                '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/package" Target="../embeddings/Microsoft_Excel_Worksheet1.xlsx"/>\n'
                "</Relationships>",
            )
            z.writestr("word/charts/chart1.xml", chart_xml)
            z.writestr("word/embeddings/Microsoft_Excel_Worksheet1.xlsx", xlsx_bytes)

        # Main document
        z.writestr("word/document.xml", document_xml)

    file_path.write_bytes(buf.getvalue())
    return file_path
