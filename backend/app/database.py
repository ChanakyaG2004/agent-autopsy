import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://agent_autopsy:agent_autopsy@127.0.0.1:55432/agent_autopsy",
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 3},
    hide_parameters=True,
)


class Base(DeclarativeBase):
    pass


def get_session() -> Generator[Session, None, None]:
    with Session(engine, expire_on_commit=False) as session:
        yield session
