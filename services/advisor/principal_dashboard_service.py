import json
import csv
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

# Path Helpers
def get_final_class_folder(department, class_name):
    class_folder_name = class_name.replace(" ", "_")
    return Path("generated/final") / department / class_folder_name

def get_principal_metadata_file(department, class_name):
    return get_final_class_folder(department, class_name) / "principal_approval.json"

def get_audit_log_file():
    return Path("audit_log.json")

def write_audit_log(user, action, student=None, department=None, class_name=None):
    """
    Appends a log entry to audit_log.json in the project root.
    """
    log_file = get_audit_log_file()
    
    log_entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": user,
        "action": action,
        "student": student or "",
        "department": department or "",
        "class": class_name or ""
    }
    
    # Load existing logs or initialize new list
    logs = []
    if log_file.exists():
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except Exception:
            logs = []
            
    logs.append(log_entry)
    
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=4)

def load_principal_state(department, class_name):
    """
    Loads principal_approval.json for a class.
    If it doesn't exist, initializes it from the HOD approval state.
    """
    final_folder = get_final_class_folder(department, class_name)
    final_folder.mkdir(parents=True, exist_ok=True)
    meta_file = get_principal_metadata_file(department, class_name)
    
    # Load HOD approval state
    from services.advisor.hod_dashboard_service import load_approval_state
    hod_state = load_approval_state(department, class_name)
    
    if meta_file.exists():
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
            
    # Initialize from HOD state
    # Keep student statuses and info as approved by HOD
    students_state = []
    for s in hod_state.get("students", []):
        students_state.append({
            "register_number": s["register_number"],
            "student_name": s["student_name"],
            "status": s["status"], # Approved/Rejected/Submitted to HOD
            "conduct": s.get("conduct", "Good"),
            "remarks": s.get("remarks", ""),
            "rejection_reason": s.get("rejection_reason", ""),
            "parent_meeting_required": s.get("parent_meeting_required", False)
        })
        
    state = {
        "principal_name": "Dr. S.U. PRABHA",
        "approval_time": "",
        "department": department,
        "class": class_name,
        "status": "HOD Approved" if hod_state.get("status") in ["Approved", "Partially Approved"] else hod_state.get("status"),
        "certificate_count": sum(1 for s in students_state if s["status"] == "Approved"),
        "students": students_state
    }
    
    save_principal_state(department, class_name, state)
    return state

def save_principal_state(department, class_name, state):
    meta_file = get_principal_metadata_file(department, class_name)
    meta_file.parent.mkdir(parents=True, exist_ok=True)
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4)

def get_batches_for_principal():
    """
    Scans HOD approvals to identify batches that have been processed by the HOD,
    along with their current Principal approval status.
    """
    batches = []
    hod_base = Path("approvals/hod")
    if not hod_base.exists():
        return batches
        
    for dept_dir in hod_base.iterdir():
        if dept_dir.is_dir():
            for class_dir in dept_dir.iterdir():
                if class_dir.is_dir():
                    app_file = class_dir / "approval.json"
                    if app_file.exists():
                        try:
                            with open(app_file, "r", encoding="utf-8") as f:
                                hod_data = json.load(f)
                                
                            department = hod_data["department"]
                            class_name = hod_data["class"]
                            hod_status = hod_data["status"]
                            
                            # Only HOD approved or partially approved batches are visible to Principal
                            if hod_status in ["Approved", "Partially Approved", "Rejected"]:
                                # Get advisor submission details for student count & submission time
                                from services.advisor.hod_dashboard_service import get_advisor_class_folder
                                advisor_folder = get_advisor_class_folder(department, class_name)
                                submission_file = advisor_folder / "submission.json"
                                
                                advisor_name = "Advisor"
                                sub_time = hod_data.get("last_updated") or ""
                                student_count = len(hod_data.get("students", []))
                                
                                if submission_file.exists():
                                    with open(submission_file, "r") as sf:
                                        sub_meta = json.load(sf)
                                        advisor_name = sub_meta.get("advisor", advisor_name)
                                        sub_time = sub_meta.get("submitted_time", sub_time)
                                        student_count = sub_meta.get("student_count", student_count)
                                        
                                # Check if Principal has already approved
                                p_meta_file = get_principal_metadata_file(department, class_name)
                                p_status = "Pending Principal"
                                p_time = ""
                                if p_meta_file.exists():
                                    with open(p_meta_file, "r", encoding="utf-8") as pf:
                                        p_data = json.load(pf)
                                        p_status = p_data.get("status", p_status)
                                        p_time = p_data.get("approval_time", "")
                                        
                                batches.append({
                                    "department": department,
                                    "class": class_name,
                                    "advisor": advisor_name,
                                    "hod": "Dr. Alan Turing", # Default Mock HOD name
                                    "student_count": student_count,
                                    "submission_time": sub_time,
                                    "hod_status": hod_status,
                                    "principal_status": p_status,
                                    "approval_time": p_time
                                })
                        except Exception:
                            pass
                            
    return batches

def get_principal_stats():
    """
    Calculates statistics for Principal dashboard:
    Pending, Approved Today, Rejected, Downloads.
    """
    batches = get_batches_for_principal()
    
    pending = 0
    approved_today = 0
    rejected = 0
    downloads = 0
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    for b in batches:
        p_status = b["principal_status"]
        app_time = b["approval_time"]
        
        if p_status == "Approved":
            downloads += 1
            if app_time and app_time.startswith(today_str):
                approved_today += 1
        elif p_status == "Rejected":
            rejected += 1
        elif p_status == "Pending Principal":
            pending += 1
            
    return {
        "pending": pending,
        "approved_today": approved_today,
        "rejected": rejected,
        "downloads": downloads
    }

def regenerate_final_certificates(department, class_name, approved_students_regs):
    """
    Regenerates final certificates for ONLY the approved students,
    swapping the placeholder signature for the actual principal.jpg signature.
    """
    final_folder = get_final_class_folder(department, class_name)
    html_folder = final_folder / "html"
    pdf_folder = final_folder / "pdf"
    
    html_folder.mkdir(parents=True, exist_ok=True)
    pdf_folder.mkdir(parents=True, exist_ok=True)
    
    # 1. Copy root static resources to final static folder so relative styles and actual signature resolve
    final_static = Path("generated/final") / department / "static"
    if final_static.exists():
        shutil.rmtree(final_static)
        
    shutil.copytree("static", final_static, dirs_exist_ok=True)
    
    # 2. Load advisor students CSV
    from services.advisor.hod_dashboard_service import load_advisor_students_csv, get_advisor_class_folder
    csv_students = load_advisor_students_csv(department, class_name)
    
    # Filter only approved students
    approved_records = [s for s in csv_students if s.get("register_number") in approved_students_regs]
    
    # Match advisor photos from preview directory
    advisor_folder = get_advisor_class_folder(department, class_name)
    for s in approved_records:
        reg_no = s.get("register_number", "")
        photo_filename = s.get("student_photo", "")
        
        preview_photo = advisor_folder / "preview" / photo_filename
        reg_photo = advisor_folder / "preview" / f"{reg_no}.jpg"
        
        if preview_photo.exists() and photo_filename:
            # Copy to final static images so it loads
            shutil.copy(preview_photo, final_static / "images" / photo_filename)
            s["student_photo"] = photo_filename
        elif reg_photo.exists():
            shutil.copy(reg_photo, final_static / "images" / f"{reg_no}.jpg")
            s["student_photo"] = f"{reg_no}.jpg"
        else:
            s["student_photo"] = "principal.jpg" # fallback
            
    # 3. Temporarily overwrite data/students.csv so the existing generator reads it
    temp_csv_backup = Path("data/students_backup.csv")
    main_csv = Path("data/students.csv")
    
    # Backup current students.csv
    if main_csv.exists():
        shutil.copy(main_csv, temp_csv_backup)
        
    try:
        # Write filtered approved students CSV to data/students.csv
        advisor_csv_path = advisor_folder / "csv" / "students.csv"
        # We write a custom temporary CSV for the generator containing only approved students
        with open(main_csv, "w", newline="", encoding="utf-8") as f:
            if approved_records:
                writer = csv.DictWriter(f, fieldnames=approved_records[0].keys())
                writer.writeheader()
                writer.writerows(approved_records)
                
        # Trigger the generation
        from services.certificate.certificate_service import generate_certificates
        generate_certificates(approved_records, str(html_folder), str(pdf_folder))
    finally:
        # Restore backup
        if temp_csv_backup.exists():
            shutil.copy(temp_csv_backup, main_csv)
            temp_csv_backup.unlink()

def generate_final_zip(department, class_name):
    """
    Generates the final approved ZIP contains final approved PDFs, CSV, and principal_approval.json.
    """
    final_folder = get_final_class_folder(department, class_name)
    zip_filename = f"{class_name.replace(' ', '_')}_final.zip"
    zip_path = final_folder / zip_filename
    
    advisor_folder = Path("generated/advisor") / department / class_name.replace(" ", "_")
    p_state = load_principal_state(department, class_name)
    approved_regs = [s["register_number"] for s in p_state.get("students", []) if s["status"] == "Approved"]
    
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
        # Add csv directory
        csv_dir = advisor_folder / "csv"
        if csv_dir.exists():
            for f in csv_dir.iterdir():
                if f.is_file():
                    zip_file.write(f, arcname=f"csv/{f.name}")
                    
        # Add approved PDF certificates
        pdf_dir = final_folder / "pdf"
        if pdf_dir.exists():
            for f in pdf_dir.iterdir():
                reg_no = f.stem
                if f.is_file() and reg_no in approved_regs:
                    zip_file.write(f, arcname=f"pdf/{f.name}")
                    
        # Add principal_approval.json
        meta_file = get_principal_metadata_file(department, class_name)
        if meta_file.exists():
            zip_file.write(meta_file, arcname="principal_approval.json")
            
    return zip_path
