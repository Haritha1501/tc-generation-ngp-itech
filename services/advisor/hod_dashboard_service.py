import json
import csv
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

# Path Helpers
def get_hod_class_folder(department, class_name):
    class_folder_name = class_name.replace(" ", "_")
    return Path("approvals/hod") / department / class_folder_name

def get_approval_file(department, class_name):
    return get_hod_class_folder(department, class_name) / "approval.json"

def get_advisor_class_folder(department, class_name):
    class_folder_name = class_name.replace(" ", "_")
    return Path("generated/advisor") / department / class_folder_name

def load_advisor_students_csv(department, class_name):
    csv_path = get_advisor_class_folder(department, class_name) / "csv" / "students.csv"
    if not csv_path.exists():
        return []
    
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)

def load_approval_state(department, class_name):
    """
    Loads approval.json for a class.
    If it doesn't exist, initializes it from the advisor's CSV and students_status.json.
    """
    hod_folder = get_hod_class_folder(department, class_name)
    hod_folder.mkdir(parents=True, exist_ok=True)
    app_file = get_approval_file(department, class_name)
    
    # Read advisor students status list (source of truth for student statuses)
    advisor_status_file = get_advisor_class_folder(department, class_name) / "students_status.json"
    advisor_students = []
    if advisor_status_file.exists():
        try:
            with open(advisor_status_file, "r", encoding="utf-8") as f:
                advisor_students = json.load(f)
        except Exception:
            pass

    # Read students details from CSV to get conduct
    csv_students = load_advisor_students_csv(department, class_name)
    student_conducts = {s.get("register_number", ""): s.get("conduct", "Good") for s in csv_students}
    
    if app_file.exists():
        try:
            with open(app_file, "r", encoding="utf-8") as f:
                state = json.load(f)
                
            # Keep state synced with advisor's students_status.json
            updated = False
            for s in state.get("students", []):
                reg_no = s.get("register_number", "")
                adv_match = next((item for item in advisor_students if item.get("register_number") == reg_no), None)
                if adv_match:
                    if s["status"] != adv_match["status"]:
                        s["status"] = adv_match["status"]
                        updated = True
                if reg_no in student_conducts and s.get("conduct") != student_conducts[reg_no]:
                    s["conduct"] = student_conducts[reg_no]
                    updated = True
                    
            if updated:
                save_approval_state(department, class_name, state)
                
            return state
        except Exception:
            pass
            
    # Initialize new approval state
    students_state = []
    for s in advisor_students:
        reg_no = s.get("register_number", "")
        conduct = student_conducts.get(reg_no, "Good")
        
        students_state.append({
            "register_number": reg_no,
            "student_name": s.get("student_name", ""),
            "status": s.get("status", "Submitted to HOD"),
            "conduct": conduct,
            "parent_meeting_required": False,
            "remarks": "",
            "rejection_reason": ""
        })
        
    state = {
        "department": department,
        "class": class_name,
        "status": "Submitted to HOD",
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "students": students_state
    }
    
    save_approval_state(department, class_name, state)
    return state

def save_approval_state(department, class_name, state):
    app_file = get_approval_file(department, class_name)
    app_file.parent.mkdir(parents=True, exist_ok=True)
    with open(app_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4)

def sync_status_to_advisor(department, class_name, state):
    """Syncs student statuses from HOD approval.json to Advisor students_status.json & submission.json."""
    advisor_folder = get_advisor_class_folder(department, class_name)
    advisor_status_file = advisor_folder / "students_status.json"
    
    # 1. Update students_status.json
    if advisor_status_file.exists():
        try:
            with open(advisor_status_file, "r", encoding="utf-8") as f:
                adv_students = json.load(f)
            
            for s in state.get("students", []):
                reg_no = s.get("register_number", "")
                adv_match = next((item for item in adv_students if item.get("register_number") == reg_no), None)
                if adv_match:
                    adv_match["status"] = s["status"]
                    
            with open(advisor_status_file, "w", encoding="utf-8") as f:
                json.dump(adv_students, f, indent=4)
        except Exception:
            pass
            
    # 2. Update submission.json
    submission_file = advisor_folder / "submission.json"
    if submission_file.exists():
        try:
            with open(submission_file, "r") as f:
                sub_data = json.load(f)
            sub_data["status"] = state["status"]
            with open(submission_file, "w") as f:
                json.dump(sub_data, f, indent=4)
        except Exception:
            pass

    # 3. Update metadata.json
    meta_file = advisor_folder / "metadata.json"
    if meta_file.exists():
        try:
            with open(meta_file, "r") as f:
                meta_data = json.load(f)
            meta_data["status"] = state["status"].upper().replace(" ", "_")
            with open(meta_file, "w") as f:
                json.dump(meta_data, f, indent=4)
        except Exception:
            pass

def get_submitted_classes(department):
    """
    Scans the advisor directories under department to list all submitted classes,
    pulling submission metadata and HOD approval status.
    """
    submitted_classes = []
    base_dir = Path("generated/advisor") / department
    if not base_dir.exists():
        return submitted_classes
        
    for class_dir in base_dir.iterdir():
        if class_dir.is_dir():
            submission_file = class_dir / "submission.json"
            if submission_file.exists():
                try:
                    with open(submission_file, "r") as f:
                        sub_data = json.load(f)
                        
                    class_name = sub_data.get("class", class_dir.name.replace("_", " "))
                    
                    # Read approval status if exists
                    app_file = get_approval_file(department, class_name)
                    if app_file.exists():
                        with open(app_file, "r", encoding="utf-8") as af:
                            app_data = json.load(af)
                        sub_data["hod_status"] = app_data.get("status", "Submitted to HOD")
                        sub_data["last_updated"] = app_data.get("last_updated", "")
                    else:
                        sub_data["hod_status"] = sub_data.get("status", "Submitted to HOD")
                        sub_data["last_updated"] = ""
                        
                    submitted_classes.append(sub_data)
                except Exception:
                    pass
                    
    return submitted_classes

def get_hod_stats(department):
    """
    Calculates statistics for HOD dashboard:
    Pending Classes, Approved Classes, Rejected Classes, Total Certificates, Need Parent Meeting.
    """
    classes = get_submitted_classes(department)
    
    pending_count = 0
    approved_count = 0
    rejected_count = 0
    total_certs = 0
    parent_meeting_count = 0
    recently_processed = []
    
    for c in classes:
        class_name = c["class"]
        status = c["hod_status"]
        
        # Increment class counters
        if status == "Approved":
            approved_count += 1
            recently_processed.append({
                "class": class_name,
                "action": "Approved",
                "time": c.get("last_updated") or c.get("submitted_time")
            })
        elif status == "Rejected":
            rejected_count += 1
            recently_processed.append({
                "class": class_name,
                "action": "Rejected",
                "time": c.get("last_updated") or c.get("submitted_time")
            })
        else:
            pending_count += 1
            
        # Scan students in this class for stats
        app_state = load_approval_state(department, class_name)
        total_certs += len(app_state.get("students", []))
        
        for s in app_state.get("students", []):
            if s.get("parent_meeting_required"):
                parent_meeting_count += 1
                
    # Sort recently processed by time descending
    recently_processed.sort(key=lambda x: x["time"], reverse=True)
    
    return {
        "pending_classes": pending_count,
        "approved_classes": approved_count,
        "rejected_classes": rejected_count,
        "total_certificates": total_certs,
        "parent_meeting": parent_meeting_count,
        "recently_processed": recently_processed[:5] # top 5
    }

def generate_approved_zip(department, class_name):
    """
    Generates a ZIP named ClassName_approved.zip
    containing ONLY certificates of approved students.
    """
    hod_folder = get_hod_class_folder(department, class_name)
    hod_folder.mkdir(parents=True, exist_ok=True)
    
    zip_filename = f"{class_name.replace(' ', '_')}_approved.zip"
    zip_path = hod_folder / zip_filename
    
    advisor_folder = get_advisor_class_folder(department, class_name)
    app_state = load_approval_state(department, class_name)
    approved_students = [s["register_number"] for s in app_state.get("students", []) if s["status"] == "Approved"]
    
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
        # Add csv directory
        csv_dir = advisor_folder / "csv"
        if csv_dir.exists():
            for f in csv_dir.iterdir():
                if f.is_file():
                    zip_file.write(f, arcname=f"csv/{f.name}")
                    
        # Add approved PDF certificates
        pdf_dir = advisor_folder / "pdf"
        if pdf_dir.exists():
            for f in pdf_dir.iterdir():
                reg_no = f.stem
                if f.is_file() and reg_no in approved_students:
                    zip_file.write(f, arcname=f"pdf/{f.name}")
                    
        # Add approval.json
        app_file = get_approval_file(department, class_name)
        if app_file.exists():
            zip_file.write(app_file, arcname="approval.json")
            
    return zip_path
