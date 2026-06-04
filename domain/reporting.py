"""PDF-ready reporting contracts."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ReportMetric:
    """Single report KPI or scalar value."""

    label: str
    value: Any
    unit: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"label": self.label, "value": self.value, "unit": self.unit}


@dataclass(frozen=True)
class ReportTable:
    """Tabular report block ready for a later PDF renderer."""

    title: str
    columns: list[str]
    rows: list[list[Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"title": self.title, "columns": list(self.columns), "rows": list(self.rows)}


@dataclass(frozen=True)
class ReportSection:
    """Logical report section with metrics, tables, warnings, and errors."""

    title: str
    metrics: list[ReportMetric] = field(default_factory=list)
    tables: list[ReportTable] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "metrics": [metric.as_dict() for metric in self.metrics],
            "tables": [table.as_dict() for table in self.tables],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class ReportDocument:
    """Renderer-neutral report document structure."""

    report_type: str
    title: str
    generated_at: datetime = field(default_factory=_utc_now)
    source_services: list[str] = field(default_factory=list)
    sections: list[ReportSection] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    pdf_ready: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "report_type": self.report_type,
            "title": self.title,
            "generated_at": self.generated_at.isoformat(),
            "source_services": list(self.source_services),
            "sections": [section.as_dict() for section in self.sections],
            "metadata": dict(self.metadata),
            "pdf_ready": self.pdf_ready,
        }
