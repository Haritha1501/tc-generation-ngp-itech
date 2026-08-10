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
        # Ensure Office user exists even if database was previously seeded
        office_user = db.query(DBUser).filter(DBUser.role == "office").first()
        if not office_user:
            office_path = Path("data/office.json")
            if office_path.exists():
                with open(office_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for off in data.get("office_users", []):
                    db_user = DBUser(
                        username=off["username"],
                        password=off["password"],
                        name=off["name"],
                        role="office"
                    )
                    db.add(db_user)
            else:
                db_user = DBUser(
                    username="office",
                    password="password123",
                    name="Central Office Administrator",
                    role="office"
                )
                db.add(db_user)
            db.commit()

        # Check if users table is empty
        if db.query(DBUser).first() is not None:
            return
            
        print("Seeding users from JSON files...")

        
        # Seed Advisors
        advisors_path = Path("data/advisors.json")
        if advisors_path.exists():
            with open(advisors_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for adv in data.get("advisors", []):
                db_user = DBUser(
                    username=adv["username"],
                    password=adv["password"],
                    name=adv["name"],
                    role="advisor",
                    department=adv["department"],
                    class_name=adv["class"]
                )
                db.add(db_user)
                
        # Seed HODs
        hods_path = Path("data/hods.json")
        if hods_path.exists():
            with open(hods_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for hod in data.get("hods", []):
                db_user = DBUser(
                    username=hod["username"],
                    password=hod["password"],
                    name=hod["name"],
                    role="hod",
                    department=hod["department"]
                )
                db.add(db_user)
                
        # Seed Principals
        principal_path = Path("data/principal.json")
        if principal_path.exists():
            with open(principal_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for p in data.get("principals", []):
                db_user = DBUser(
                    username=p["username"],
                    password=p["password"],
                    name=p["name"],
                    role="principal"
                )
                db.add(db_user)
                
        # Seed Office Users
        office_path = Path("data/office.json")
        if office_path.exists():
            with open(office_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for off in data.get("office_users", []):
                db_user = DBUser(
                    username=off["username"],
                    password=off["password"],
                    name=off["name"],
                    role="office"
                )
                db.add(db_user)
        else:
            # Fallback default office user if office.json is missing
            db_user = DBUser(
                username="office",
                password="password123",
                name="Central Office Administrator",
                role="office"
            )
            db.add(db_user)

        db.commit()
        print("Seeding complete.")
    except Exception as e:
        print(f"Error seeding database: {e}")
        db.rollback()
    finally:
        db.close()

