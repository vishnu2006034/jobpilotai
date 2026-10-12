from alembic import context
from sqlalchemy import create_engine

from app.config import Settings
from app.db import Base
from app import identity  # noqa: F401
from app import jobs  # noqa: F401
from app import applications  # noqa: F401
from app import operations  # noqa: F401
from app import discovery  # noqa: F401
from app import resumes  # noqa: F401

config = context.config


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=Settings.from_env().database_url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif config.attributes.get("connection") is not None:
    run(config.attributes["connection"])
else:
    engine = create_engine(Settings.from_env().database_url)
    with engine.connect() as connection:
        run(connection)
    engine.dispose()
