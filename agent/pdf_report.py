"""Professional, publication-ready PDF report generation for ACID AI runs.

Renders structured FinalReport instances into downloadable PDF documents adhering
strictly to defense-in-depth principles: zero external network dependencies,
strict secret redaction, safe XML/text escaping, bounded memory usage, and
verifiable page numbering and truthfulness disclaimers.
"""
import io
import xml.sax.saxutils as saxutils
from typing import Dict, Any, Union, List

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    KeepTogether,
    HRFlowable,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
from reportlab.pdfgen import canvas

from agent.models import FinalReport
from agent.security import redact_secrets
from agent.report import format_file_list, generate_plain_english_summary


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas providing accurate 'Page X of Y' pagination and running headers/footers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: List[Dict[str, Any]] = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_header_footer(num_pages)
            super().showPage()
        super().save()

    def draw_header_footer(self, page_count: int):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))

        # Running Header (pages > 1)
        if self._pageNumber > 1:
            self.drawString(40, 755, "ACID AI — Execution & Repair Report")
            run_id = getattr(self, "report_run_id", "")
            if run_id:
                self.drawRightString(612 - 40, 755, f"Run ID: {run_id}")
            self.setStrokeColor(colors.HexColor("#e2e8f0"))
            self.setLineWidth(0.5)
            self.line(40, 750, 612 - 40, 750)

        # Running Footer (all pages)
        self.setStrokeColor(colors.HexColor("#e2e8f0"))
        self.setLineWidth(0.5)
        self.line(40, 42, 612 - 40, 42)
        self.drawString(40, 30, "Automated & Verified by ACID AI Delivery Engine | Confidential")
        self.drawRightString(612 - 40, 30, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()


def _safe_escape(text: Any) -> str:
    """Sanitize and XML-escape text for safe rendering in ReportLab Paragraphs."""
    if text is None:
        return ""
    clean = redact_secrets(str(text))
    # Replace null bytes and unusual control characters
    clean = clean.replace("\x00", "")
    # Escape XML entities for ReportLab mini-HTML
    return saxutils.escape(clean, entities={'"': '&quot;', "'": '&#39;'})


def _bound_code_text(text: str, max_chars: int = 1500) -> str:
    """Bound code or log snippets and break long unbroken tokens to prevent table overflow."""
    if not text:
        return ""
    clean = redact_secrets(text.strip())
    if len(clean) > max_chars:
        clean = clean[:max_chars] + f"\n\n[... truncated {len(clean) - max_chars} characters for readability ...]"

    # Break exceedingly long words (> 80 chars) to prevent line overflow
    def break_long_words(line: str) -> str:
        words = line.split(" ")
        broken_words = []
        for w in words:
            if len(w) > 80:
                chunks = [w[i:i + 70] for i in range(0, len(w), 70)]
                broken_words.append(" ".join(chunks))
            else:
                broken_words.append(w)
        return " ".join(broken_words)

    lines = [break_long_words(line_item) for line_item in clean.splitlines()]
    return "\n".join(lines)


def generate_pdf_report(report_input: Union[FinalReport, Dict[str, Any]]) -> bytes:
    """Generate a high-quality PDF report from a FinalReport or report data dictionary.

    Args:
        report_input: FinalReport instance or serializable report dictionary.

    Returns:
        Raw bytes of the generated PDF document.
    """
    if isinstance(report_input, FinalReport):
        data = report_input.model_dump()
    else:
        data = dict(report_input)

    run_id = data.get("run_id", "unknown-run")
    repo_name = data.get("repository", "unknown-repo")
    branch = data.get("branch", "unknown")
    base_commit = data.get("base_commit", "unknown")
    short_sha = data.get("short_sha", base_commit[:7] if base_commit else "unknown")
    outcome = (data.get("outcome") or "unresolved").lower()
    mode = data.get("mode", "real")
    created_at = data.get("created_at", "")
    elapsed = data.get("elapsed_seconds") or 0.0
    retry_count = data.get("retry_count", 0)
    unresolved = data.get("unresolved_issues", [])
    pub = data.get("publication", {})
    attempts = data.get("attempts", [])
    verified_patches = data.get("verified_patches", [])
    scope_statement = data.get("verification_scope_statement", "")

    # Ensure Plain-English Summary is present
    summary = data.get("summary")
    if not summary:
        summary = generate_plain_english_summary(report_data=data)

    buffer = io.BytesIO()

    # Document Geometry: Letter size (612 x 792), 40pt margins = 532pt printable width
    printable_width = 532
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=40,
        rightMargin=40,
        topMargin=46,
        bottomMargin=48,
    )

    # Styles Setup
    base_styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "DocTitle",
        parent=base_styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "DocSubTitle",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=10,
    )
    meta_label = ParagraphStyle(
        "MetaLabel",
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#475569"),
    )
    meta_val = ParagraphStyle(
        "MetaVal",
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#0f172a"),
    )
    meta_val_mono = ParagraphStyle(
        "MetaValMono",
        fontName="Courier",
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#0f172a"),
    )
    section_h1 = ParagraphStyle(
        "SectionH1",
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=8,
        spaceAfter=6,
    )
    section_h2 = ParagraphStyle(
        "SectionH2",
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#1e293b"),
        spaceBefore=6,
        spaceAfter=4,
    )
    body_text = ParagraphStyle(
        "BodyText",
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#334155"),
        spaceAfter=4,
    )
    summary_label = ParagraphStyle(
        "SummaryLabel",
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#1e293b"),
    )
    summary_text = ParagraphStyle(
        "SummaryText",
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#334155"),
    )
    code_snippet_style = ParagraphStyle(
        "CodeSnippet",
        fontName="Courier",
        fontSize=7,
        leading=8.5,
        textColor=colors.HexColor("#0f172a"),
    )
    scope_disclaimer_style = ParagraphStyle(
        "ScopeDisclaimer",
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#1e293b"),
    )

    story = []

    # ── HEADER & TITLE ────────────────────────────────────────────────────────
    story.append(Paragraph("🛡️ ACID AI — Execution & Repair Report", title_style))
    story.append(Paragraph(
        "Autonomous CI/CD Failure Triage, Deterministic Policy Validation & Isolated Verification",
        subtitle_style,
    ))

    # ── RUN OVERVIEW METADATA TABLE ───────────────────────────────────────────
    is_mock = "mock" in str(mode).lower()
    mode_display = "DEMONSTRATION RUN (Deterministic Mock)" if is_mock else "LIVE REPOSITORY RUN (Real Execution)"
    pr_ctx = f"PR #{data.get('pr_number')}" if data.get("pr_number") else f"Push ({branch})"

    meta_table_data = [
        [
            Paragraph("Repository:", meta_label), Paragraph(_safe_escape(repo_name), meta_val),
            Paragraph("Run ID:", meta_label), Paragraph(_safe_escape(run_id), meta_val_mono),
        ],
        [
            Paragraph("Branch / Context:", meta_label), Paragraph(_safe_escape(pr_ctx), meta_val),
            Paragraph("Execution Mode:", meta_label), Paragraph(_safe_escape(mode_display), meta_val),
        ],
        [
            Paragraph("Base Commit:", meta_label),
            Paragraph(f"{_safe_escape(short_sha)} ({_safe_escape(base_commit[:16])}...)", meta_val_mono),
            Paragraph("Timestamp:", meta_label), Paragraph(_safe_escape(created_at), meta_val),
        ],
        [
            Paragraph("Repair Attempts:", meta_label), Paragraph(f"{retry_count} attempt(s)", meta_val),
            Paragraph("Duration:", meta_label), Paragraph(f"{elapsed:.2f}s", meta_val),
        ],
    ]
    meta_table = Table(meta_table_data, colWidths=[90, 176, 90, 176])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#f1f5f9")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 8))

    # ── OVERALL OUTCOME BANNER ────────────────────────────────────────────────
    outcome_colors = {
        "healthy": (colors.HexColor("#ecfdf5"), colors.HexColor("#047857"), colors.HexColor("#10b981")),
        "repaired": (colors.HexColor("#ecfdf5"), colors.HexColor("#047857"), colors.HexColor("#10b981")),
        "partially repaired": (colors.HexColor("#eff6ff"), colors.HexColor("#1d4ed8"), colors.HexColor("#3b82f6")),
        "blocked": (colors.HexColor("#fffbeb"), colors.HexColor("#b45309"), colors.HexColor("#f59e0b")),
        "unresolved": (colors.HexColor("#fef2f2"), colors.HexColor("#b91c1c"), colors.HexColor("#ef4444")),
    }
    bg_color, text_color, border_color = outcome_colors.get(outcome, outcome_colors["unresolved"])
    outcome_header_text = f"OVERALL OUTCOME: {outcome.upper()}"
    outcome_desc_text = summary.get("overall_outcome_text", outcome)

    outcome_banner_data = [
        [
            Paragraph(f"<b>{_safe_escape(outcome_header_text)}</b>", ParagraphStyle(
                "OutcomeBannerHead",
                fontName="Helvetica-Bold",
                fontSize=11,
                leading=14,
                textColor=text_color,
            )),
        ],
        [
            Paragraph(_safe_escape(outcome_desc_text), ParagraphStyle(
                "OutcomeBannerDesc",
                fontName="Helvetica",
                fontSize=8.5,
                leading=11.5,
                textColor=colors.HexColor("#1e293b"),
            )),
        ],
    ]
    outcome_banner = Table(outcome_banner_data, colWidths=[printable_width])
    outcome_banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg_color),
        ("BOX", (0, 0), (-1, -1), 1, border_color),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(outcome_banner)
    story.append(Spacer(1, 10))

    # ── LEVEL 1: PLAIN-ENGLISH RUN SUMMARY (PAGE 1) ───────────────────────────
    story.append(Paragraph("💡 Plain-English Run Summary (Beginner-Friendly)", section_h1))

    summary_rows = [
        [
            Paragraph("What Happened?", summary_label),
            Paragraph(_safe_escape(summary.get("what_happened", "")), summary_text),
        ],
        [
            Paragraph("Why Did It Happen?", summary_label),
            Paragraph(_safe_escape(summary.get("why_it_happened", "")), summary_text),
        ],
        [
            Paragraph("What ACID AI Attempted:", summary_label),
            Paragraph(_safe_escape(summary.get("what_acid_attempted", "")), summary_text),
        ],
        [
            Paragraph("Did the Repair Work?", summary_label),
            Paragraph(_safe_escape(summary.get("did_repair_work", "")), summary_text),
        ],
        [
            Paragraph("Why Did ACID AI Stop?", summary_label),
            Paragraph(_safe_escape(summary.get("why_agent_stopped", "")), summary_text),
        ],
        [
            Paragraph("What You Should Do Next:", summary_label),
            Paragraph(_safe_escape(summary.get("what_to_do_next", "")), summary_text),
        ],
        [
            Paragraph("Publication Status:", summary_label),
            Paragraph(_safe_escape(summary.get("publication_status", "")), summary_text),
        ],
    ]

    summary_table = Table(summary_rows, colWidths=[140, 392])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#cbd5e1")),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 10))

    # Verification Scope Summary Callout on Page 1
    scope_box_data = [
        [
            Paragraph(
                f"<b>Truthfulness & Verification Boundary:</b> {_safe_escape(scope_statement)}",
                scope_disclaimer_style,
            )
        ]
    ]
    scope_box = Table(scope_box_data, colWidths=[printable_width])
    scope_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f5f9")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("LINELEFT", (0, 0), (0, -1), 3, colors.HexColor("#4f46e5")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(scope_box)

    # ── LEVEL 2: TECHNICAL DETAILS (PAGE 2+) ──────────────────────────────────
    story.append(PageBreak())

    story.append(Paragraph("🔬 Technical Details & Failure Triage", section_h1))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=8))

    # Stage results table
    init_checks = data.get("initial_checks", {})
    stages_list = init_checks.get("stages", [])
    stage_table_data = [
        [
            Paragraph("<b>Stage Name</b>", meta_label),
            Paragraph("<b>Exit Status</b>", meta_label),
            Paragraph("<b>Execution Note</b>", meta_label),
        ]
    ]
    if stages_list:
        for s in stages_list:
            s_name = s.get("name", s.get("id", "stage"))
            s_status = str(s.get("status", "unknown")).upper()
            s_note = s.get("note") or (f"Exit code: {s.get('exit_code')}" if "exit_code" in s else "Evaluated")
            stage_table_data.append([
                Paragraph(_safe_escape(s_name), body_text),
                Paragraph(_safe_escape(s_status), body_text),
                Paragraph(_safe_escape(s_note), body_text),
            ])
    else:
        stage_table_data.append([
            Paragraph("Initial Repository Inspection", body_text),
            Paragraph(_safe_escape(outcome.upper()), body_text),
            Paragraph("Checks evaluated during run startup", body_text),
        ])

    stage_table = Table(stage_table_data, colWidths=[160, 100, 272])
    stage_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(stage_table)
    story.append(Spacer(1, 8))

    # Log Evidence Box
    cited_evidence = init_checks.get("evidence", "")
    if cited_evidence:
        story.append(Paragraph("<b>Supporting Failure Log Evidence:</b>", section_h2))
        bounded_evidence = _bound_code_text(cited_evidence, max_chars=1200)
        evidence_p = Paragraph(f"<pre>{_safe_escape(bounded_evidence)}</pre>", code_snippet_style)
        evidence_table = Table([[evidence_p]], colWidths=[printable_width])
        evidence_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0f172a")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#334155")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(evidence_table)
        story.append(Spacer(1, 10))

    # ── ATTEMPTS TIMELINE BREAKDOWN ───────────────────────────────────────────
    story.append(Paragraph("🔄 Autonomous Repair Attempts Timeline", section_h1))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=8))

    if not attempts:
        story.append(Paragraph("<i>No repair attempts were executed during this run.</i>", body_text))
        story.append(Spacer(1, 8))
    else:
        for att in attempts:
            att_idx = att.get("attempt", 1)
            att_status = att.get("status", "UNKNOWN")
            att_cat = att.get("failure_category", "actionable_failure")
            att_reason = att.get("reason", "")
            diag = att.get("diagnosis") or {}
            root_cause = diag.get("root_cause", "Diagnosis completed")
            patch_dict = att.get("patch") or {}
            diff_text = patch_dict.get("diff", "")
            files_changed = patch_dict.get("files") or att.get("affected_files") or []
            files_str = format_file_list(files_changed)

            verif_dict = att.get("verification") or {}
            verif_cmds = verif_dict.get("executed_commands", [])
            cmds_str = ", ".join(verif_cmds) if verif_cmds else "None"
            verif_exit = verif_dict.get("exit_code", "N/A")
            test_results = verif_dict.get("output") or att.get("test_results") or ""

            # Check whether patch was proposed vs applied
            policy_val = patch_dict.get("validation") or {}
            if isinstance(policy_val, dict):
                is_valid = policy_val.get("is_valid", False)
            else:
                is_valid = getattr(policy_val, "is_valid", False)
            is_verified = verif_dict.get("is_verified", False)

            if is_verified:
                patch_lifecycle = "Applied in disposable workspace & Verified in sandbox container"
            elif is_valid:
                patch_lifecycle = "Proposed candidate patch (unverified)"
            else:
                patch_lifecycle = "Proposed candidate patch (Rejected by safety policy)"

            attempt_rows = [
                [
                    Paragraph(f"<b>Attempt #{att_idx} — Status: {att_status}</b>", ParagraphStyle(
                        "AttHeader",
                        fontName="Helvetica-Bold",
                        fontSize=9,
                        leading=11,
                        textColor=colors.HexColor("#1e293b"),
                    )),
                    Paragraph(f"Category: <code>{_safe_escape(att_cat)}</code>", ParagraphStyle(
                        "AttCat",
                        fontName="Helvetica",
                        fontSize=8,
                        leading=10,
                        alignment=TA_RIGHT,
                        textColor=colors.HexColor("#64748b"),
                    )),
                ],
                [
                    Paragraph(
                        f"<b>Target Files:</b> {_safe_escape(files_str)}<br/>"
                        f"<b>Lifecycle State:</b> {_safe_escape(patch_lifecycle)}<br/>"
                        f"<b>Root Cause:</b> {_safe_escape(root_cause)}<br/>"
                        f"<b>Verification Command:</b> <code>{_safe_escape(cmds_str)}</code> "
                        f"(Exit Code: {_safe_escape(str(verif_exit))})<br/>"
                        f"<b>Attempt Result:</b> {_safe_escape(att_reason)}",
                        body_text,
                    ),
                    Paragraph("", body_text),
                ],
            ]

            att_table = Table(attempt_rows, colWidths=[380, 152])
            att_table.setStyle(TableStyle([
                ("SPAN", (0, 1), (1, 1)),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#e2e8f0")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]))

            attempt_block = [att_table]

            # Diff snippet if present
            if diff_text:
                bounded_diff = _bound_code_text(diff_text, max_chars=1200)
                diff_p = Paragraph(f"<pre>{_safe_escape(bounded_diff)}</pre>", code_snippet_style)
                diff_table = Table([[diff_p]], colWidths=[printable_width])
                diff_table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0f172a")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#334155")),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]))
                attempt_block.append(Spacer(1, 3))
                attempt_block.append(diff_table)

            # Test output excerpt if present
            if test_results:
                bounded_test = _bound_code_text(test_results, max_chars=800)
                test_p = Paragraph(f"<pre>{_safe_escape(bounded_test)}</pre>", code_snippet_style)
                test_table = Table([[test_p]], colWidths=[printable_width])
                test_table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1e293b")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#334155")),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]))
                attempt_block.append(Spacer(1, 3))
                attempt_block.append(test_table)

            attempt_block.append(Spacer(1, 8))
            story.append(KeepTogether(attempt_block))

    # ── CUMULATIVE VERIFIED PATCHES ───────────────────────────────────────────
    story.append(Paragraph("📦 Cumulative Verified Patches", section_h1))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=6))
    if verified_patches:
        for idx, vp in enumerate(verified_patches, start=1):
            expl = vp.get("explanation", "Targeted code repair")
            files = format_file_list(vp.get("files", []))
            story.append(Paragraph(
                f"• <b>Patch #{idx}:</b> {_safe_escape(expl)} — Modified files: <code>{_safe_escape(files)}</code>",
                body_text,
            ))
    else:
        story.append(Paragraph("<i>No patches were verified and applied during this run.</i>", body_text))
    story.append(Spacer(1, 8))

    # ── UNRESOLVED ISSUES ─────────────────────────────────────────────────────
    story.append(Paragraph("⚠️ Unresolved Issues & Limitations", section_h1))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=6))
    if unresolved:
        for issue in unresolved:
            story.append(Paragraph(f"• {_safe_escape(issue)}", body_text))
    else:
        story.append(Paragraph("• No unresolved issues remaining. Repository is clean and passing.", body_text))
    story.append(Spacer(1, 8))

    # ── GITHUB DRAFT PR PUBLICATION ───────────────────────────────────────────
    story.append(Paragraph("🚀 GitHub Draft PR Publication", section_h1))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=6))
    pub_outcome = pub.get("outcome", "skipped")
    if pub_outcome == "successful":
        pr_link = pub.get("pr_url") or "#"
        story.append(Paragraph(
            f"<b>Status:</b> SUCCESSFUL<br/>"
            f"<b>Draft PR:</b> <a href='{_safe_escape(pr_link)}' color='#4f46e5'>"
            f"<u>Draft PR #{pub.get('pr_number')}</u></a><br/>"
            f"<b>PR URL:</b> {_safe_escape(pr_link)}<br/>"
            f"<b>Target Branch:</b> <code>{_safe_escape(pub.get('branch'))}</code><br/>"
            f"<b>Commit SHA:</b> <code>{_safe_escape(pub.get('commit_sha'))}</code><br/>"
            f"<b>Details:</b> {_safe_escape(pub.get('message'))}",
            body_text,
        ))
    elif pub_outcome == "blocked":
        story.append(Paragraph(
            f"<b>Status:</b> BLOCKED<br/>"
            f"<b>Reason:</b> {_safe_escape(pub.get('message', 'Publication was blocked'))}",
            body_text,
        ))
    else:
        story.append(Paragraph(
            f"<b>Status:</b> SKIPPED<br/>"
            f"<b>Reason:</b> "
            f"{_safe_escape(pub.get('message', 'Publication was not enabled or repair was unverified.'))}",
            body_text,
        ))
    story.append(Spacer(1, 10))

    # ── FINAL SECTION: SCOPE, TRUTHFULNESS & HUMAN REVIEW NOTICE ──────────────
    final_notice_block = [
        Paragraph("⚖️ Verification Scope & Human Review Notice", section_h1),
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=6),
        Paragraph(_safe_escape(scope_statement), body_text),
        Paragraph(
            "<b>Mandatory Human Review:</b> Passing tests verify only the executed assertions. Automated repairs "
            "reduce triage latency but do NOT guarantee complete correctness or absence of non-evaluated edge cases. "
            "Engineering review and manual approval are strictly required before merging any repair PR.",
            ParagraphStyle(
                "HumanReviewNotice",
                parent=body_text,
                textColor=colors.HexColor("#b91c1c"),
            ),
        ),
    ]
    story.append(KeepTogether(final_notice_block))

    # Custom canvas maker carrying report_run_id for running headers
    def canvas_maker(*args, **kwargs):
        c = NumberedCanvas(*args, **kwargs)
        c.report_run_id = run_id
        return c

    doc.build(story, canvasmaker=canvas_maker)

    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
