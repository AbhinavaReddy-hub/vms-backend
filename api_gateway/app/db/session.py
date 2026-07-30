from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

connect_args = {"check_same_thread": False} if _is_sqlite else {}
# Postgres hangs up idle connections, which a local SQLite file never did.
# pool_pre_ping catches an already-dead connection and transparently reopens it;
# pool_recycle retires connections before the server is likely to drop them.
# Without these you get an occasional "server closed the connection
# unexpectedly" on the first request after a quiet spell. Still worth keeping
# with Postgres in a container alongside this one: `docker compose restart db`
# drops every open connection, and pool_pre_ping is what stops that turning
# into a 500 on the next request.
if not _is_sqlite:
    connect_args = {"connect_timeout": 10}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    pool_recycle=1800 if not _is_sqlite else -1,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
