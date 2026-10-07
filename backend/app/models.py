from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Experiment(Base):
    __tablename__ = "experiments"
    __table_args__ = (
        CheckConstraint("length(trim(name)) >= 3", name="experiment_name_length"),
        CheckConstraint("length(trim(agent_version)) >= 1", name="agent_version_length"),
        CheckConstraint("status = 'draft'", name="experiment_draft_status"),
        CheckConstraint(
            "jsonb_typeof(scenarios) = 'array' AND jsonb_array_length(scenarios) BETWEEN 1 AND 3",
            name="experiment_scenario_count",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(80))
    agent_version: Mapped[str] = mapped_column(String(80))
    scenarios: Mapped[list[str]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'draft'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
