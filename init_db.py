# init_db.py
from backend.database.database import engine, Base, SQLALCHEMY_DATABASE_URL
from backend.database import models  # noqa: F401  (import registers models on Base)

print(f"Creating database tables at: {SQLALCHEMY_DATABASE_URL}")
Base.metadata.create_all(bind=engine)
print("Done!")