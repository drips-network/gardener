"""
Alembic environment configuration
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Add the app directory to Python path to import our modules
# In Docker, the working directory is /app
app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if os.path.exists("/app"):
    sys.path.insert(0, "/app")
else:
    sys.path.insert(0, app_dir)

# Import models only, avoid importing full settings during migrations
from services.shared.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use
config = context.config


def _database_url_from_env():
    """
    Build a database URL from environment variables

    Prefers DATABASE_URL, then PG* variables (Railway), finally POSTGRES_* defaults
    """
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return db_url

    pg_user = os.getenv("PGUSER")
    pg_host = os.getenv("PGHOST")
    if pg_host and pg_user:
        pg_pass = os.getenv("PGPASSWORD", "")
        pg_port = os.getenv("PGPORT", "5432")
        pg_db = os.getenv("PGDATABASE", "railway")
        return f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"

    user = os.getenv("POSTGRES_USER", "gardener")
    password = os.getenv("POSTGRES_PASSWORD", "gardener_dev")
    host = os.getenv("POSTGRES_HOST", "postgres")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "gardener_db")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


# Set the database URL directly from env to avoid importing full settings
config.set_main_option("sqlalchemy.url", _database_url_from_env())

# Interpret the config file for Python logging
# This line sets up loggers basically
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option('my_important_option')
# ... etc


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available

    Calls to context.execute() here emit the given string to the
    script output
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode

    In this scenario we need to create an Engine
    and associate a connection with the context
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
