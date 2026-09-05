import json
import csv
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from services.advisor.hod_dashboard_service import (
    get_hod_class_folder,
    get_approval_file as get_hod_approval_file,
    load_approval_state as load_hod_approval_state,
    get_advisor_class_folder,
    save_approval_state as save_hod_approval_state
)

COMPUTER_CLUSTER_DEPTS = ["CSE", "AIDS", "IT", "CS", "CSBS"]

def is_computer_cluster(department: str) -> bool:
    if not department:
        return False
    return department.strip().upper() in [d.upper() for d in COMPUTER_CLUSTER_DEPTS]

def get_dean_class_folder(department: str, class_name: str) -> Path:
    class_folder_name = class_name.replace(" ", "_")
    return Path("approvals/dean") / department / class_folder_name

def get_dean_approval_file(department: str, class_name: str) -> Path:
    return get_dean_class_folder(department, class_name) / "dean_approval.json"

def load_dean_approval_state(department: str, class_name: str) -> dict:
    """
    Loads dean_approval.json for a class.
    If it doesn't exist, initializes it from the HOD's approval state.
    """
    dean_folder = get_dean_class_folder(department, class_name)
    dean_folder.mkdir(parents=True, exist_ok=True)
    dean_file = get_dean_approval_file(department, class_name)
    
    # Load HOD approval state
    hod_state = load_hod_approval_state(department, class_name)
    
    if dean_file.exists():
        try:
            with open(dean_file, "r", encoding="utf-8") as f:
                state = json.load(f)
            return state
        except Exception:
            pass

    # Initialize from HOD state
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
        "dean_name": "Dr. D. Palannikumar, Ph.D.",
        "department": department,
        "class": class_name,
        "status": "Pending Dean",
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "certificate_count": sum(1 for s in students_state if s["status"] == "Approved"),
        "students": students_state
    }

    save_dean_approval_state(department, class_name, state)
    return state

def save_dean_approval_state(department: str, class_name: str, state: dict):
    dean_file = get_dean_approval_file(department, class_name)
    dean_file.parent.mkdir(parents=True, exist_ok=True)
    with open(dean_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4)

def sync_dean_status_to_pipeline(department: str, class_name: str, state: dict):
    """
    Syncs Dean decisions down to Advisor/HOD states and metadata.
    """
    # 1. Update Advisor submission.json and metadata
    advisor_folder = get_advisor_class_folder(department, class_name)
    submission_file = advisor_folder / "submission.json"
    if submission_file.exists():
        try:
            with open(submission_file, "r", encoding="utf-8") as f:
                sub_data = json.load(f)
            sub_data["status"] = state["status"]
            sub_data["dean_status"] = state["status"]
            with open(submission_file, "w", encoding="utf-8") as f:
                json.dump(sub_data, f, indent=4)
        except Exception:
            pass

    # 2. Update HOD approval state status if needed
    hod_app_file = get_hod_approval_file(department, class_name)
    if hod_app_file.exists():
        try:
            with open(hod_app_file, "r", encoding="utf-8") as f:
                hod_state = json.load(f)
            hod_state["dean_status"] = state["status"]
            with open(hod_app_file, "w", encoding="utf-8") as f:
                json.dump(hod_state, f, indent=4)
        except Exception:
            pass

def get_submitted_classes_for_dean(departments=COMPUTER_CLUSTER_DEPTS):
    """
    Scans for classes in Computer Cluster departments that have been approved by HOD
    and require Dean review.
    """
    submitted_classes = []
    
    for dept in departments:
        hod_dept_dir = Path("approvals/hod") / dept
        if not hod_dept_dir.exists():
            continue
            
        for class_dir in hod_dept_dir.iterdir():
            if class_dir.is_dir():
                app_file = class_dir / "approval.json"
                if app_file.exists():
                    try:
                        with open(app_file, "r", encoding="utf-8") as af:
                            hod_data = json.load(af)
                            
                        class_name = hod_data.get("class", class_dir.name.replace("_", " "))
                        hod_status = hod_data.get("status", "")
                        
                        # Process if HOD approved/partially approved
                        if hod_status in ["Approved", "Partially Approved", "Pending Dean", "Submitted to Dean"]:
                            advisor_folder = get_advisor_class_folder(dept, class_name)
                            submission_file = advisor_folder / "submission.json"
                            
                            advisor_name = "Advisor"
                            sub_time = hod_data.get("last_updated", "")
                            student_count = len(hod_data.get("students", []))
                            
                            if submission_file.exists():
                                with open(submission_file, "r", encoding="utf-8") as sf:
                                    sub_meta = json.load(sf)
                                    advisor_name = sub_meta.get("advisor", advisor_name)
                                    sub_time = sub_meta.get("submitted_time", sub_time)
                                    student_count = sub_meta.get("student_count", student_count)
                                    
                            # Check Dean approval file
                            dean_app_file = get_dean_approval_file(dept, class_name)
                            dean_status = "Pending Dean"
                            last_updated = sub_time
                            if dean_app_file.exists():
                                with open(dean_app_file, "r", encoding="utf-8") as df:
                                    dean_data = json.load(df)
                                    dean_status = dean_data.get("status", dean_status)
                                    last_updated = dean_data.get("last_updated", last_updated)
                                    
                            submitted_classes.append({
                                "department": dept,
                                "class": class_name,
                                "advisor": advisor_name,
                                "student_count": student_count,
                                "submitted_time": sub_time,
                                "hod_status": hod_status,
                                "dean_status": dean_status,
                                "last_updated": last_updated
                            })
                    except Exception:
                        pass
                        
    return submitted_classes

def get_dean_stats(departments=COMPUTER_CLUSTER_DEPTS):
    """
    Calculates statistics for Dean dashboard across Computer Cluster departments.
    """
    classes = get_submitted_classes_for_dean(departments)
    
    pending_count = 0
    approved_count = 0
    rejected_count = 0
    total_certs = 0
    recently_processed = []
    
    for c in classes:
        dept = c["department"]
        class_name = c["class"]
        status = c["dean_status"]
        
        if status == "Approved":
            approved_count += 1
            recently_processed.append({
                "class": class_name,
                "department": dept,
                "action": "Approved",
                "time": c.get("last_updated") or c.get("submitted_time")
            })
        elif status == "Rejected":
            rejected_count += 1
            recently_processed.append({
                "class": class_name,
                "department": dept,
                "action": "Rejected",
                "time": c.get("last_updated") or c.get("submitted_time")
            })
        else:
            pending_count += 1
            
        dean_state = load_dean_approval_state(dept, class_name)
        total_certs += len(dean_state.get("students", []))
        
    recently_processed.sort(key=lambda x: x["time"], reverse=True)
    
    return {
        "pending_classes": pending_count,
        "approved_classes": approved_count,
        "rejected_classes": rejected_count,
        "total_certificates": total_certs,
        "recently_processed": recently_processed[:5]
    }
