import json
from datetime import datetime
from pathlib import Path
from services.database import SessionLocal, DBUser

NOTIFICATIONS_FILE = Path("data/notifications.json")

def get_notifications_file() -> Path:
    NOTIFICATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    return NOTIFICATIONS_FILE

def load_notifications():
    nfile = get_notifications_file()
    if not nfile.exists():
        return []
    try:
        with open(nfile, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_notifications(notifications):
    nfile = get_notifications_file()
    with open(nfile, "w", encoding="utf-8") as f:
        json.dump(notifications, f, indent=4)

def find_advisor_username(department: str, class_name: str) -> str:
    """Finds the username of the advisor assigned to a department and class."""
    db = SessionLocal()
    try:
        user = db.query(DBUser).filter(
            DBUser.role == "advisor",
            DBUser.department == department,
            DBUser.class_name == class_name
        ).first()
        if user:
            return user.username
        
        # Fallback to department match if class name formatting varies
        user_dept = db.query(DBUser).filter(
            DBUser.role == "advisor",
            DBUser.department == department
        ).first()
        if user_dept:
            return user_dept.username
    finally:
        db.close()
    return "advisor"

def send_rejection_notification(
    office_user: str,
    student_name: str,
    identifier: str,
    department: str,
    class_name: str,
    rejection_reason: str
):
    notifications = load_notifications()
    advisor_username = find_advisor_username(department, class_name)
    
    notification_entry = {
        "id": len(notifications) + 1,
        "sent_by": office_user,
        "advisor_username": advisor_username,
        "student_name": student_name,
        "identifier": identifier,
        "department": department,
        "class_name": class_name,
        "rejection_reason": rejection_reason,
        "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "read": False
    }
    
    notifications.append(notification_entry)
    save_notifications(notifications)
    return notification_entry

def get_notifications_for_advisor(advisor_username: str, department: str = None, class_name: str = None):
    notifications = load_notifications()
    matched = []
    for n in notifications:
        # Match by username or matching department & class
        if n.get("advisor_username") == advisor_username:
            matched.append(n)
        elif department and class_name and n.get("department") == department and n.get("class_name") == class_name:
            matched.append(n)
    return matched

def mark_notification_as_read(notification_id: int):
    notifications = load_notifications()
    updated = False
    for n in notifications:
        if n.get("id") == notification_id:
            n["read"] = True
            updated = True
    if updated:
        save_notifications(notifications)
