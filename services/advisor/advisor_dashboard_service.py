import csv
import json
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

REQUIRED_COLUMNS = [
    "tc_number", "umis_number", "admission_number", "student_name", "parent_name",
    "gender", "dob", "dob_words", "nationality", "course", "roll_number",
    "register_number", "class_leaving", "admission_date", "medium", "last_attended",
    "reason_leaving", "conduct", "certificate_date", "student_photo"
]

def validate_csv_data(file_path):
    """
    Validates the students CSV file according to the requested rules:
    - Duplicate Register Numbers
    - Missing fields (columns)
    - Invalid DOB (format must be dd/mm/yyyy)
    - Invalid Admission Number (alphanumeric and dashes/slashes, non-empty)
    - Empty values in any of the required columns
    Returns a list of error strings. If the list is empty, validation passed.
    """
    errors = []
    
    # 1. Check if file is readable and parseable
    try:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if not headers:
                return ["The uploaded CSV is empty or has no header."]
            
            # 2. Check for missing columns/fields
            missing_cols = [col for col in REQUIRED_COLUMNS if col not in headers]
            if missing_cols:
                errors.append(f"Missing required columns in CSV header: {', '.join(missing_cols)}")
                return errors # Return early if header structure is invalid
            
            rows = list(reader)
    except Exception as e:
        return [f"Failed to parse CSV: {str(e)}"]

    if not rows:
        return ["The CSV contains no data rows."]

    # 3. Check for duplicates, empty values, invalid DOB, invalid Admission Number row-by-row
    seen_register_numbers = set()
    duplicate_registers = set()
    
    for idx, row in enumerate(rows, start=2): # Start counting from line 2 (first data row)
        reg_num = (row.get("register_number") or "").strip()
        adm_num = (row.get("admission_number") or "").strip()
        dob = (row.get("dob") or "").strip()
        
        # Check empty values across all required columns
        empty_cols = []
        for col in REQUIRED_COLUMNS:
            val = (row.get(col) or "").strip()
            if not val:
                empty_cols.append(col)
        
        if empty_cols:
            errors.append(f"Row {idx}: Empty values in columns: {', '.join(empty_cols)}")
            
        # Check duplicate Register Numbers
        if reg_num:
            if reg_num in seen_register_numbers:
                duplicate_registers.add(reg_num)
            else:
                seen_register_numbers.add(reg_num)
        else:
            errors.append(f"Row {idx}: Register Number is empty.")

        # Check invalid DOB (dd/mm/yyyy)
        if dob:
            # Match regex dd/mm/yyyy
            if not re.match(r"^\d{2}/\d{2}/\d{4}$", dob):
                errors.append(f"Row {idx}: Invalid Date of Birth format '{dob}'. Must be dd/mm/yyyy.")
            else:
                try:
                    datetime.strptime(dob, "%d/%m/%Y")
                except ValueError:
                    errors.append(f"Row {idx}: Invalid Date of Birth value '{dob}' (e.g. Feb 30th or invalid month/day).")
        
        # Check invalid Admission Number (non-empty, alphanumeric and dashes/slashes)
        if adm_num:
            if not re.match(r"^[A-Za-z0-9\-/]+$", adm_num):
                errors.append(f"Row {idx}: Invalid Admission Number '{adm_num}'. It must contain only letters, digits, hyphens (-) or slashes (/).")
        else:
            if "admission_number" not in empty_cols: # avoid redundant error
                errors.append(f"Row {idx}: Admission Number is empty.")

    if duplicate_registers:
        errors.append(f"Duplicate Register Numbers found in CSV: {', '.join(duplicate_registers)}")

    return errors

def get_class_folder(department, class_name):
    class_folder_name = class_name.replace(" ", "_")
    return Path("generated/advisor") / department / class_folder_name

def get_students_status_file(department, class_name):
    return get_class_folder(department, class_name) / "students_status.json"

def get_submission_file(department, class_name):
    return get_class_folder(department, class_name) / "submission.json"

def is_class_submitted(department, class_name):
    return get_submission_file(department, class_name).exists()

def load_students_from_csv(department, class_name):
    """Loads student records directly from the saved CSV file."""
    csv_path = get_class_folder(department, class_name) / "csv" / "students.csv"
    if not csv_path.exists():
        return []
    
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)

def load_students_status(department, class_name):
    """
    Returns a list of student dicts with their current status.
    If students_status.json exists, uses that.
    Otherwise, reads from the CSV and initializes all status values to 'Not Generated'.
    """
    class_dir = get_class_folder(department, class_name)
    status_path = get_students_status_file(department, class_name)
    
    if status_path.exists():
        try:
            with open(status_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass # fall back to parsing CSV
            
    # Fallback to CSV
    csv_students = load_students_from_csv(department, class_name)
    students_status = []
    
    # Check if submission exists
    submitted = is_class_submitted(department, class_name)
    default_status = "Submitted to HOD" if submitted else "Not Generated"
    
    for s in csv_students:
        reg_no = s.get("register_number", "")
        # Check if HTML/PDF already generated
        html_exists = (class_dir / "html" / f"{reg_no}.html").exists()
        pdf_exists = (class_dir / "pdf" / f"{reg_no}.pdf").exists()
        
        status = default_status
        if not submitted:
            if html_exists and pdf_exists:
                status = "Generated"
            else:
                status = "Not Generated"
                
        students_status.append({
            "register_number": reg_no,
            "student_name": s.get("student_name", ""),
            "status": status,
            "student_photo": s.get("student_photo", "")
        })
        
    save_students_status(department, class_name, students_status)
    return students_status

def save_students_status(department, class_name, students_status):
    status_path = get_students_status_file(department, class_name)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(students_status, f, indent=4)

def update_all_students_status(department, class_name, status):
    """Updates status for all students in the class."""
    students = load_students_status(department, class_name)
    for s in students:
        s["status"] = status
    save_students_status(department, class_name, students)

def get_class_stats(department, class_name):
    """
    Returns a dictionary of statistics for the advisor dashboard:
    Total Students, Pending, Generated, Approved by HOD, Rejected
    """
    students = load_students_status(department, class_name)
    total = len(students)
    
    # Status Values: Not Generated, Generated, Submitted to HOD, Approved, Rejected
    # 'Pending' represents 'Submitted to HOD' (awaiting approval) or 'Not Generated'.
    # Let's count Pending as 'Submitted to HOD' or 'Not Generated' explicitly.
    pending = sum(1 for s in students if s["status"] in ["Submitted to HOD", "Not Generated"])
    generated = sum(1 for s in students if s["status"] == "Generated")
    approved = sum(1 for s in students if s["status"] == "Approved")
    rejected = sum(1 for s in students if s["status"] == "Rejected")
    
    return {
        "total_students": total,
        "pending": pending,
        "generated": generated,
        "approved": approved,
        "rejected": rejected
    }

def submit_to_hod_workflow(advisor_username, department, class_name):
    """
    Executes the SUBMIT TO HOD action:
    1. Creates submission.json metadata.
    2. Updates status of all students to 'Submitted to HOD'.
    3. Generates the ClassName.zip containing: html/, pdf/, csv/, submission.json.
    """
    class_dir = get_class_folder(department, class_name)
    students = load_students_status(department, class_name)
    
    # 1. Update all student statuses to 'Submitted to HOD'
    update_all_students_status(department, class_name, "Submitted to HOD")
    
    # Update batch metadata to SUBMITTED
    metadata_path = class_dir / "metadata.json"
    if metadata_path.exists():
        try:
            with open(metadata_path, "r") as f:
                meta = json.load(f)
            meta["status"] = "SUBMITTED"
            with open(metadata_path, "w") as f:
                json.dump(meta, f, indent=4)
        except Exception:
            pass

    # 2. Create submission.json
    submission_data = {
        "advisor": advisor_username,
        "department": department,
        "class": class_name,
        "submitted_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "student_count": len(students),
        "status": "Submitted to HOD"
    }
    
    sub_file = get_submission_file(department, class_name)
    with open(sub_file, "w", encoding="utf-8") as f:
        json.dump(submission_data, f, indent=4)
        
    # 3. Create ClassName.zip
    generate_class_zip(department, class_name)

def generate_class_zip(department, class_name):
    """
    Generates a zip file named ClassName.zip (e.g. IV_BE_CSE_A.zip)
    containing: csv/, pdf/, submission.json
    """
    class_dir = get_class_folder(department, class_name)
    zip_filename = f"{class_name.replace(' ', '_')}.zip"
    zip_path = class_dir / zip_filename
    
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
        # Add csv directory
        csv_dir = class_dir / "csv"
        if csv_dir.exists():
            for f in csv_dir.iterdir():
                if f.is_file():
                    zip_file.write(f, arcname=f"csv/{f.name}")
                    
        # Add pdf directory
        pdf_dir = class_dir / "pdf"
        if pdf_dir.exists():
            for f in pdf_dir.iterdir():
                if f.is_file():
                    zip_file.write(f, arcname=f"pdf/{f.name}")
                    
        # Add submission.json
        sub_file = get_submission_file(department, class_name)
        if sub_file.exists():
            zip_file.write(sub_file, arcname="submission.json")

    return zip_path
