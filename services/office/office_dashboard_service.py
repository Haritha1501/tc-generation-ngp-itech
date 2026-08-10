import json
import csv
import shutil
from pathlib import Path
from datetime import datetime
from services.office.notification_service import load_notifications, find_advisor_username

def get_all_batches():
    """
    Scans generated folders and approvals to aggregate all batches/classes across all departments.
    """
    batches = {}
    
    # 1. Scan advisor / office uploads
    adv_base = Path("generated/advisor")
    if adv_base.exists():
        for dept_dir in adv_base.iterdir():
            if dept_dir.is_dir():
                dept = dept_dir.name
                for class_dir in dept_dir.iterdir():
                    if class_dir.is_dir():
                        class_name = class_dir.name.replace("_", " ")
                        meta_file = class_dir / "metadata.json"
                        sub_file = class_dir / "submission.json"
                        status_file = class_dir / "students_status.json"
                        
                        total_students = 0
                        if status_file.exists():
                            try:
                                with open(status_file, "r", encoding="utf-8") as f:
                                    total_students = len(json.load(f))
                            except Exception:
                                pass
                        elif meta_file.exists():
                            try:
                                with open(meta_file, "r", encoding="utf-8") as f:
                                    meta = json.load(f)
                                    total_students = meta.get("total_students", 0)
                            except Exception:
                                pass
                                
                        status = "Generated"
                        workflow_type = "Advisor Upload"
                        submitted_time = ""
                        advisor = find_advisor_username(dept, class_name)
                        
                        if sub_file.exists():
                            try:
                                with open(sub_file, "r", encoding="utf-8") as f:
                                    sub_data = json.load(f)
                                    status = sub_data.get("status", status)
                                    workflow_type = sub_data.get("workflow_type", workflow_type)
                                    submitted_time = sub_data.get("submitted_time", "")
                                    advisor = sub_data.get("advisor", advisor)
                            except Exception:
                                pass

                        batches[(dept, class_name)] = {
                            "department": dept,
                            "class_name": class_name,
                            "total_students": total_students,
                            "status": status,
                            "workflow_type": workflow_type,
                            "advisor": advisor,
                            "submitted_time": submitted_time,
                            "folder": str(class_dir)
                        }

    # 2. Check HOD approval status
    hod_base = Path("approvals/hod")
    if hod_base.exists():
        for dept_dir in hod_base.iterdir():
            if dept_dir.is_dir():
                dept = dept_dir.name
                for class_dir in dept_dir.iterdir():
                    if class_dir.is_dir():
                        class_name = class_dir.name.replace("_", " ")
                        app_file = class_dir / "approval.json"
                        if app_file.exists():
                            try:
                                with open(app_file, "r", encoding="utf-8") as f:
                                    app_data = json.load(f)
                                key = (dept, class_name)
                                if key in batches:
                                    batches[key]["status"] = app_data.get("status", batches[key]["status"])
                            except Exception:
                                pass

    # 3. Check Principal final approval status
    final_base = Path("generated/final")
    if final_base.exists():
        for dept_dir in final_base.iterdir():
            if dept_dir.is_dir():
                dept = dept_dir.name
                for class_dir in dept_dir.iterdir():
                    if class_dir.is_dir():
                        class_name = class_dir.name.replace("_", " ")
                        p_file = class_dir / "principal_approval.json"
                        if p_file.exists():
                            try:
                                with open(p_file, "r", encoding="utf-8") as f:
                                    p_data = json.load(f)
                                key = (dept, class_name)
                                if key in batches:
                                    batches[key]["status"] = p_data.get("status", batches[key]["status"])
                            except Exception:
                                pass

    return list(batches.values())

def get_office_stats():
    batches = get_all_batches()
    total_batches = len(batches)
    approved_batches = sum(1 for b in batches if b["status"] == "Approved")
    pending_principal = sum(1 for b in batches if b["status"] in ["Approved", "Partially Approved", "Direct Office Submission", "Submitted to Principal"])
    
    rejected_students = get_all_rejected_students()
    total_rejected = len(rejected_students)
    
    return {
        "total_batches": total_batches,
        "approved_batches": approved_batches,
        "pending_principal": pending_principal,
        "total_rejected": total_rejected
    }

def get_all_rejected_students():
    """
    Returns a list of all rejected student records across all departments and classes.
    """
    rejected = []
    notifications = load_notifications()
    notified_identifiers = {n.get("identifier") for n in notifications}

    # 1. Scan HOD approvals
    hod_base = Path("approvals/hod")
    if hod_base.exists():
        for dept_dir in hod_base.iterdir():
            if dept_dir.is_dir():
                dept = dept_dir.name
                for class_dir in dept_dir.iterdir():
                    if class_dir.is_dir():
                        class_name = class_dir.name.replace("_", " ")
                        app_file = class_dir / "approval.json"
                        if app_file.exists():
                            try:
                                with open(app_file, "r", encoding="utf-8") as f:
                                    app_data = json.load(f)
                                for s in app_data.get("students", []):
                                    if s.get("status") == "Rejected":
                                        reg_no = s.get("register_number", "")
                                        wf_type = app_data.get("workflow_type", "Advisor Upload")
                                        adv = "N/A (Office Direct)" if wf_type == "Office Direct Upload" else find_advisor_username(dept, class_name)
                                        rejected.append({
                                            "student_name": s.get("student_name", ""),
                                            "register_number": reg_no,
                                            "admission_number": s.get("admission_number", reg_no),
                                            "department": dept,
                                            "class_name": class_name,
                                            "rejected_by": "HOD",
                                            "rejection_reason": s.get("rejection_reason", "Not specified"),
                                            "assigned_advisor": adv,
                                            "workflow_type": wf_type,
                                            "notification_sent": reg_no in notified_identifiers
                                        })
                            except Exception:
                                pass

    # 2. Scan Principal approvals (Principal rejections override/add)
    final_base = Path("generated/final")
    if final_base.exists():
        for dept_dir in final_base.iterdir():
            if dept_dir.is_dir():
                dept = dept_dir.name
                for class_dir in dept_dir.iterdir():
                    if class_dir.is_dir():
                        class_name = class_dir.name.replace("_", " ")
                        p_file = class_dir / "principal_approval.json"
                        if p_file.exists():
                            try:
                                with open(p_file, "r", encoding="utf-8") as f:
                                    p_data = json.load(f)
                                for s in p_data.get("students", []):
                                    if s.get("status") == "Rejected":
                                        reg_no = s.get("register_number", "")
                                        wf_type = p_data.get("workflow_type", "Advisor Upload")
                                        adv = "N/A (Office Direct)" if wf_type == "Office Direct Upload" else find_advisor_username(dept, class_name)
                                        # Check if already added from HOD, update rejected_by to Principal if so
                                        match = next((item for item in rejected if item["register_number"] == reg_no and item["department"] == dept and item["class_name"] == class_name), None)
                                        if match:
                                            match["rejected_by"] = "Principal"
                                            match["rejection_reason"] = s.get("rejection_reason") or match["rejection_reason"]
                                        else:
                                            rejected.append({
                                                "student_name": s.get("student_name", ""),
                                                "register_number": reg_no,
                                                "admission_number": s.get("admission_number", reg_no),
                                                "department": dept,
                                                "class_name": class_name,
                                                "rejected_by": "Principal",
                                                "rejection_reason": s.get("rejection_reason", "Not specified"),
                                                "assigned_advisor": adv,
                                                "workflow_type": wf_type,
                                                "notification_sent": reg_no in notified_identifiers
                                            })
                            except Exception:
                                pass

    return rejected


def submit_office_batch_to_principal(department: str, class_name: str, username: str):
    """
    Submits an Office-uploaded batch directly to the Principal (Workflow B).
    """
    from services.advisor.advisor_dashboard_service import get_class_folder, load_students_from_csv, save_students_status, generate_class_zip
    
    class_dir = get_class_folder(department, class_name)
    sub_file = class_dir / "submission.json"
    
    students = load_students_from_csv(department, class_name)
    
    # Save submission metadata marking as Workflow B
    sub_metadata = {
        "advisor": f"Office ({username})",
        "department": department,
        "class": class_name,
        "submitted_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "student_count": len(students),
        "status": "Submitted to Principal",
        "workflow_type": "Office Direct Upload"
    }
    with open(sub_file, "w", encoding="utf-8") as f:
        json.dump(sub_metadata, f, indent=4)
        
    # Also initialize HOD approval state with Approved status so Principal service picks it up automatically
    hod_folder = Path("approvals/hod") / department / class_name.replace(" ", "_")
    hod_folder.mkdir(parents=True, exist_ok=True)
    app_file = hod_folder / "approval.json"
    
    students_state = []
    for s in students:
        reg_no = s.get("register_number", "")
        students_state.append({
            "register_number": reg_no,
            "student_name": s.get("student_name", ""),
            "status": "Approved", # Office pre-approves for Principal signature
            "conduct": s.get("conduct", "Good"),
            "parent_meeting_required": False,
            "remarks": "Office Direct Upload",
            "rejection_reason": ""
        })
        
    hod_state = {
        "department": department,
        "class": class_name,
        "status": "Approved",
        "workflow_type": "Office Direct Upload",
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "students": students_state
    }
    with open(app_file, "w", encoding="utf-8") as f:
        json.dump(hod_state, f, indent=4)
        
    generate_class_zip(department, class_name)
    return sub_metadata
