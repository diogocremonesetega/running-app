import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from geoalchemy2 import alembic_helpers

from alembic import context
from app.config import settings
from app.db import Base
# ensure models are imported so Alembic can find them!
from app.models import *

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

config.set_main_option("sqlalchemy.url", settings.database_url)

def custom_include_object(object, name, type_, reflected, compare_to):
    # filter out tiger and topology tables from extensions
    if type_ == "table" and name in [
        "spatial_ref_sys", "topology", "layer", "countysub_lookup",
        "county_lookup", "direction_lookup", "secondary_unit_lookup",
        "state_lookup", "street_type_lookup", "zip_lookup", "zip_lookup_all",
        "zip_lookup_base", "zip_state", "zip_state_loc", "geocode_settings",
        "geocode_settings_default", "loader_platform", "loader_variables",
        "loader_lookuptables", "tract", "tabblock", "bg", "zcta5", "faces",
        "featnames", "edges", "addr", "addrfeat", "cousub", "county", "state",
        "place", "place_lookup", "pagc_gaz", "pagc_lex", "pagc_rules",
        "tabblock20"
    ]:
        return False
    return alembic_helpers.include_object(object, name, type_, reflected, compare_to)

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=custom_include_object,
        process_revision_directives=alembic_helpers.writer,
        render_item=alembic_helpers.render_item,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection, 
        target_metadata=target_metadata,
        include_object=custom_include_object,
        process_revision_directives=alembic_helpers.writer,
        render_item=alembic_helpers.render_item,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
