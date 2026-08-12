import os
import json
from pathlib import Path
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker

# Default to SQLite if DATABASE_URL is not set, to support easy testing
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tc_generator.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# SQLite requires connect_args for multithreading
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class DBUser(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)          # 'advisor', 'hod', 'principal'
    department = Column(String, nullable=True)     # For advisor/hod
    class_name = Column(String, nullable=True)     # For advisor

def init_db():
    Base.metadata.create_all(bind=engine)

def seed_users():
    db = SessionLocal()
    try:
        print("Syncing users from JSON configuration files...")

        def upsert_user(username, password, name, role, department=None, class_name=None):
            user = db.query(DBUser).filter(DBUser.username == username).first()
            if user:
                user.password = password
                user.name = name
                user.role = role
                user.department = department
                user.class_name = class_name
            else:
                user = DBUser(
                    username=username,
                    password=password,
                    name=name,
                    role=role,
                    department=department,
                    class_name=class_name
                )
                db.add(user)

        # 1. Seed/Sync Advisors from data/advisors.json
        advisors_path = Path("data/advisors.json")
        if advisors_path.exists():
            with open(advisors_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for adv in data.get("advisors", []):
                upsert_user(
                    username=adv["username"],
                    password=adv["password"],
                    name=adv["name"],
                    role="advisor",
                    department=adv.get("department"),
                    class_name=adv.get("class")
                )

        # 2. Seed/Sync HODs from data/hods.json
        hods_path = Path("data/hods.json")
        if hods_path.exists():
            with open(hods_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for hod in data.get("hods", []):
                upsert_user(
                    username=hod["username"],
                    password=hod["password"],
                    name=hod["name"],
                    role="hod",
                    department=hod.get("department")
                )

        # 3. Seed/Sync Principals from data/principal.json
        principal_path = Path("data/principal.json")
        if principal_path.exists():
            with open(principal_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for p in data.get("principals", []):
                upsert_user(
                    username=p["username"],
                    password=p["password"],
                    name=p["name"],
                    role="principal"
                )

        # 4. Seed/Sync Office Users from data/office.json (or default fallback)
        office_path = Path("data/office.json")
        if office_path.exists():
            with open(office_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for off in data.get("office_users", []):
                upsert_user(
                    username=off["username"],
                    password=off["password"],
                    name=off["name"],
                    role="office"
                )
        else:
            upsert_user(
                username="office",
                password="password123",
                name="Central Office Administrator",
                role="office"
            )

        db.commit()
        print("User database sync complete.")
    except Exception as e:
        print(f"Error seeding database: {e}")
        db.rollback()
    finally:
        db.close()


