from alembic import context

from app.database import DATABASE_URL, engine
from app.models import Experiment

target_metadata = Experiment.metadata


def migrate(connection):
    context.configure(
        connection=connection, target_metadata=target_metadata, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied_connection = context.config.attributes.get("connection")
    if supplied_connection is not None:
        migrate(supplied_connection)
    else:
        with engine.connect() as connection:
            migrate(connection)
