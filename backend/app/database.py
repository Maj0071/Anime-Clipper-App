from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

# Database URL from environment
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://clipper:clipper_dev_password@db:5432/anime_clipper"
)

# Fall back to SQLite for local development if PostgreSQL is unavailable
if DATABASE_URL.startswith("postgresql://"):
    try:
        _test_engine = create_engine(DATABASE_URL)
        with _test_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        _test_engine.dispose()
    except Exception:
        db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "anime_clipper.db")
        DATABASE_URL = f"sqlite:///{db_path}"
        print(f"[DEV] PostgreSQL unavailable, using SQLite: {db_path}")

# Create engine
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    echo=False,
    **({} if DATABASE_URL.startswith("sqlite") else {"pool_size": 10, "max_overflow": 20}),
    connect_args=connect_args
)

# Create session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Base class for models
Base = declarative_base()


def get_db():
    """
    Dependency for FastAPI routes to get database session
    
    Usage:
        @app.get("/items")
        def read_items(db: Session = Depends(get_db)):
            items = db.query(Item).all()
            return items
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Initialize database tables
    
    This creates all tables defined in models.
    In production, use Alembic migrations instead.
    """
    from app.models import Base
    Base.metadata.create_all(bind=engine)


def reset_db():
    """
    Drop and recreate all tables
    
    WARNING: This will delete all data!
    Only use for development/testing.
    """
    from app.models import Base
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
