import json
import shutil
import zipfile
import base64
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, Request, UploadFile, File, Form, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from services.database import init_db, seed_users, SessionLocal, DBUser

# Import services
from services.certificate.csv_reader import get_students
from services.certificate.certificate_service import generate_certificates
from services.advisor.advisor_dashboard_service import (
    validate_csv_data,
    get_class_folder,
    get_students_status_file,
    get_submission_file,
    is_class_submitted,
    load_students_from_csv,
    load_students_status,
    save_students_status,
    update_all_students_status,
    get_class_stats,
    submit_to_hod_workflow,
    generate_class_zip
)
from services.advisor.hod_dashboard_service import (
    get_hod_class_folder,
    get_approval_file,
    get_advisor_class_folder,
    load_approval_state,
    save_approval_state,
    sync_status_to_advisor,
    get_submitted_classes,
    get_hod_stats,
    generate_approved_zip
)
from services.advisor.principal_dashboard_service import (
    get_final_class_folder,
    get_principal_metadata_file,
    load_principal_state,
    save_principal_state,
    get_batches_for_principal,
    get_principal_stats,
    regenerate_final_certificates,
    generate_final_zip,
    write_audit_log
)
from services.office.notification_service import (
    send_rejection_notification,
    get_notifications_for_advisor
)
from services.office.office_dashboard_service import (
    get_all_batches,
    get_office_stats,
    get_all_rejected_students,
    submit_office_batch_to_principal
)


import os

app = FastAPI(title="Transfer Certificate Generator")

# Ensure required directories exist for cloud deployment
for folder in ["static", "generated", "uploads", "data", "approvals", "output", "(generatedpdfs)"]:
    Path(folder).mkdir(parents=True, exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/generated", StaticFiles(directory="generated"), name="generated")

# Set up templates
templates = Jinja2Templates(directory="templates")

# Status Priority for sorting students (critical/active statuses first)
STATUS_PRIORITY = {
    "Rejected": 1,
    "Not Generated": 2,
    "Generated": 3,
    "Submitted to HOD": 4,
    "HOD Approved": 5,
    "Partially Approved": 5,
    "Approved": 6
}

# Configure Session Middleware
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-for-advisor-tc")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Initialize and seed database
init_db()
seed_users()

# Dependency to get db session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Path to advisors list
ADVISORS_FILE = Path("data/advisors.json")

def get_class_zip_filename(class_name: str, suffix: str = "") -> str:
    """
    Helper to map a class name (e.g. 'IV BE CSE A' or 'IV-CSE-A') to
    the new batch zip filename format like '2024-2028-CSE-A'.
    If the class is already in batch format, returns it as-is.
    """
    import re
    name = class_name.strip()
    
    # 1. Check if it matches "IV BE <dept> <sec>"
    match_iv_be_sec = re.match(r"^IV\s+BE\s+(\w+)\s+(\w+)$", name, re.IGNORECASE)
    if match_iv_be_sec:
        dept = match_iv_be_sec.group(1).upper()
        sec = match_iv_be_sec.group(2).upper()
        name = f"2024-2028-{dept}-{sec}"
    else:
        # 2. Check if it matches "IV BE <dept>" (no section)
        match_iv_be = re.match(r"^IV\s+BE\s+(\w+)$", name, re.IGNORECASE)
        if match_iv_be:
            dept = match_iv_be.group(1).upper()
            name = f"2024-2028-{dept}"
        else:
            # 3. Check if it matches "IV-BE-<dept>-<sec>" or "IV-BE-<dept>"
            match_iv_hyphen = re.match(r"^IV[-_]BE[-_](\w+)(?:[-_](\w+))?$", name, re.IGNORECASE)
            if match_iv_hyphen:
                dept = match_iv_hyphen.group(1).upper()
                sec = match_iv_hyphen.group(2)
                if sec:
                    name = f"2024-2028-{dept}-{sec.upper()}"
                else:
                    name = f"2024-2028-{dept}"
            else:
                # 4. Check if it matches "IV-CSE-A"
                match_iv_simple = re.match(r"^IV[-_](\w+)[-_](\w+)$", name, re.IGNORECASE)
                if match_iv_simple:
                    dept = match_iv_simple.group(1).upper()
                    sec = match_iv_simple.group(2).upper()
                    name = f"2024-2028-{dept}-{sec}"
                else:
                    # 5. Check if it matches "IV-CSE"
                    match_iv_simple_no_sec = re.match(r"^IV[-_](\w+)$", name, re.IGNORECASE)
                    if match_iv_simple_no_sec:
                        dept = match_iv_simple_no_sec.group(1).upper()
                        name = f"2024-2028-{dept}"
                        
    formatted = name.replace(" ", "_")
    if suffix:
        return f"{formatted}_{suffix}.zip"
    return f"{formatted}.zip"

def get_logged_in_advisor(request: Request):
    """Dependency to retrieve logged in advisor from session."""
    advisor = request.session.get("advisor")
    if not advisor:
        raise HTTPException(status_code=307, detail="Not logged in")
    return advisor

@app.get("/")
def home(request: Request, error: str = None, success: str = None):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"request": request, "error": error, "success": success}
    )

@app.get("/preview-sample")
def preview_sample(request: Request):
    """Render the default TC template for preview using data/students.csv."""
    try:
        students = get_students("data/students.csv")
        if not students:
            return "No sample students found in data/students.csv"
        student = students[0]
        student["student_photo"] = "/static/images/" + student["student_photo"]
        student["principal_signature"] = "/static/images/principal.jpg"
        
        context = {
            "request": request,
            **student
        }
        return templates.TemplateResponse(
            request=request,
            name="tc_template.html",
            context=context
        )
    except Exception as e:
        return f"Error loading sample: {str(e)}"

@app.post("/register")
def register_advisor(
    request: Request,
    name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    batch: str = Form(...),
    department: str = Form(...),
    section: str = Form(...),
    db: Session = Depends(get_db)
):
    name = name.strip()
    username = username.strip()
    password = password.strip()
    batch = batch.strip()
    department = department.strip().upper()
    section = section.strip().upper()
    
    if not all([name, username, password, batch, department, section]):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"request": request, "error": "All fields are required.", "success": None}
        )
        
    class_name = f"{batch}-{department}-{section}"
    
    existing_user = db.query(DBUser).filter(DBUser.username == username).first()
    if existing_user:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"request": request, "error": f"Username '{username}' already exists.", "success": None}
        )
        
    new_user = DBUser(
        username=username,
        password=password,
        name=f"{name} ({department})",
        role="advisor",
        department=department,
        class_name=class_name
    )
    
    try:
        db.add(new_user)
        db.commit()
    except Exception as e:
        db.rollback()
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"request": request, "error": f"Failed to save advisor data: {str(e)}", "success": None}
        )
        
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request, 
            "error": None, 
            "success": f"Class '{class_name}' and Advisor '{name}' registered successfully! You can now log in."
        }
    )

@app.get("/generate")
def generate_default():
    """Trigger the default batch generation for data/students.csv."""
    try:
        # Fall back to root level generation
        generate_certificates(None, "output/html", "output/pdf")
        return {
            "status": "success",
            "message": "Sample certificates generated successfully in output/ folder"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ================= ADVISOR LOGIN & LOGOUT =================

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    # If already logged in, redirect to dashboard
    if request.session.get("advisor"):
        return RedirectResponse(url="/advisor")
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})

@app.post("/login")
def login(
    request: Request, 
    username: str = Form(...), 
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    # Query matching advisor in database
    advisor_match = db.query(DBUser).filter(
        DBUser.username == username,
        DBUser.password == password,
        DBUser.role == "advisor"
    ).first()
            
    if advisor_match:
        # Store in session
        request.session["advisor"] = {
            "username": advisor_match.username,
            "name": advisor_match.name,
            "department": advisor_match.department,
            "class": advisor_match.class_name
        }
        return RedirectResponse(url="/advisor", status_code=303)
    else:
        return templates.TemplateResponse(request=request, name="login.html", context={"error": "Invalid username or password."})

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")

# ================= ADVISOR DASHBOARD =================

@app.get("/advisor")
def advisor_dashboard(request: Request):
    advisor = request.session.get("advisor")
    if not advisor:
        return RedirectResponse(url="/login")
        
    dept = advisor["department"]
    class_name = advisor["class"]
    
    # Check if there is data
    students = load_students_status(dept, class_name)
    students.sort(key=lambda s: (STATUS_PRIORITY.get(s.get("status", ""), 99), s.get("register_number", "")))
    stats = get_class_stats(dept, class_name)
    is_submitted = is_class_submitted(dept, class_name)
    
    # Retrieve and clear flash messages from session
    upload_errors = request.session.pop("upload_errors", None)
    upload_success = request.session.pop("upload_success", None)
    
    # Read HOD status if submitted
    submission_status = "Pending"
    submission_metadata = None
    if is_submitted:
        sub_file = get_submission_file(dept, class_name)
        if sub_file.exists():
            with open(sub_file, "r") as f:
                submission_metadata = json.load(f)
                submission_status = submission_metadata.get("status", "Submitted to HOD")

    # Retrieve notifications for this advisor
    notifications = get_notifications_for_advisor(
        advisor_username=advisor["username"],
        department=dept,
        class_name=class_name
    )

    return templates.TemplateResponse(
        request=request,
        name="advisor_dashboard.html",
        context={
            "request": request,
            "advisor": advisor,
            "students": students,
            "stats": stats,
            "is_submitted": is_submitted,
            "submission": submission_metadata,
            "submission_status": submission_status,
            "upload_errors": upload_errors,
            "upload_success": upload_success,
            "notifications": notifications
        }
    )


@app.post("/advisor/upload")
def upload_csv(
    request: Request,
    students_csv: UploadFile = File(...),
    photos_zip: UploadFile = File(None)
):
    advisor = request.session.get("advisor")
    if not advisor:
        return RedirectResponse(url="/login", status_code=303)
        
    dept = advisor["department"]
    class_name = advisor["class"]
    
    if is_class_submitted(dept, class_name):
        return RedirectResponse(url="/advisor", status_code=303)
        
    class_dir = get_class_folder(dept, class_name)
    
    # Create required folder structure
    (class_dir / "csv").mkdir(parents=True, exist_ok=True)
    (class_dir / "html").mkdir(parents=True, exist_ok=True)
    (class_dir / "pdf").mkdir(parents=True, exist_ok=True)
    (class_dir / "preview").mkdir(parents=True, exist_ok=True)
    
    # Save uploaded CSV file temporarily for validation
    csv_path = class_dir / "csv" / "students.csv"
    with open(csv_path, "wb") as buffer:
        shutil.copyfileobj(students_csv.file, buffer)
        
    # Validate the CSV file
    errors = validate_csv_data(csv_path)
    if errors:
        # Delete invalid CSV file
        if csv_path.exists():
            csv_path.unlink()
        request.session["upload_errors"] = errors
        return RedirectResponse(url="/advisor", status_code=303)
        
    # If photo zip is provided, extract photos
    if photos_zip and photos_zip.filename:
        temp_zip = class_dir / "temp_photos.zip"
        with open(temp_zip, "wb") as buffer:
            shutil.copyfileobj(photos_zip.file, buffer)
            
        try:
            with zipfile.ZipFile(temp_zip, "r") as zip_ref:
                # Extract directly to preview directory
                zip_ref.extractall(class_dir / "preview")
                
            # Copy all extracted photos to static/images/ (so existing generator resolves them)
            # and to generated/advisor/<dept>/static/images/ (for PDF resolution)
            static_images_dir = Path("static/images")
            static_images_dir.mkdir(parents=True, exist_ok=True)
            
            dept_images_dir = Path("generated/advisor") / dept / "static" / "images"
            dept_images_dir.mkdir(parents=True, exist_ok=True)
            
            preview_dir = class_dir / "preview"
            for f in preview_dir.iterdir():
                if f.is_file() and f.suffix.lower() in [".jpg", ".jpeg", ".png"]:
                    # Copy to global static
                    shutil.copy(f, static_images_dir / f.name)
                    # Copy to department static
                    shutil.copy(f, dept_images_dir / f.name)
        except Exception as e:
            request.session["upload_errors"] = [f"Failed to extract photo zip: {str(e)}"]
            if temp_zip.exists():
                temp_zip.unlink()
            return RedirectResponse(url="/advisor", status_code=303)
        finally:
            if temp_zip.exists():
                temp_zip.unlink()
                
    # Remove any existing status file to trigger reinitialization
    status_file = get_students_status_file(dept, class_name)
    if status_file.exists():
        status_file.unlink()
        
    write_audit_log(advisor["username"], "Upload CSV", None, dept, class_name)
    request.session["upload_success"] = True
    return RedirectResponse(url="/advisor", status_code=303)

@app.post("/advisor/generate")
def generate_advisor_certificates(request: Request):
    advisor = request.session.get("advisor")
    if not advisor:
        return RedirectResponse(url="/login", status_code=303)
        
    dept = advisor["department"]
    class_name = advisor["class"]
    
    if is_class_submitted(dept, class_name):
        return RedirectResponse(url="/advisor", status_code=303)
        
    class_dir = get_class_folder(dept, class_name)
    csv_path = class_dir / "csv" / "students.csv"
    
    if not csv_path.exists():
        return RedirectResponse(url="/advisor", status_code=303)
        
    # Copy project static resources into department directory so relative paths '../../static' resolve correctly in PDF
    dept_static = Path("generated/advisor") / dept / "static"
    shutil.copytree("static", dept_static, dirs_exist_ok=True)
    shutil.copy("static/images/principal_placeholder.jpg", dept_static / "images" / "principal.jpg")
        
    # Load students from CSV
    students = load_students_from_csv(dept, class_name)
    
    # Prepare student records for the certificate generator.
    # Set photo field properly
    for s in students:
        reg_no = s.get("register_number", "")
        photo_filename = s.get("student_photo", "")
        
        # Verify if photo exists in preview directory, if not try register_number.jpg
        preview_photo = class_dir / "preview" / photo_filename
        reg_photo = class_dir / "preview" / f"{reg_no}.jpg"
        
        if preview_photo.exists() and photo_filename:
            s["student_photo"] = photo_filename
        elif reg_photo.exists():
            s["student_photo"] = f"{reg_no}.jpg"
        else:
            # Fallback placeholder photo
            s["student_photo"] = "principal.jpg"
            
    # Generate HTML & PDF
    html_folder = class_dir / "html"
    pdf_folder = class_dir / "pdf"
    
    # Temporarily override data/students.csv so the existing generator reads it
    temp_csv_backup = Path("data/students_backup.csv")
    main_csv = Path("data/students.csv")
    
    if main_csv.exists():
        shutil.copy(main_csv, temp_csv_backup)
        
    try:
        # Write advisor CSV to data/students.csv
        shutil.copy(csv_path, main_csv)
        
        # Trigger the generation
        generate_certificates(students, str(html_folder), str(pdf_folder))
    finally:
        # Restore backup
        if temp_csv_backup.exists():
            shutil.copy(temp_csv_backup, main_csv)
            temp_csv_backup.unlink()
            
    # Update status of students to 'Generated'
    update_all_students_status(dept, class_name, "Generated")
    
    # Generate batch metadata
    metadata = {
        "department": dept,
        "class": class_name,
        "status": "GENERATED",
        "generated_at": datetime.now().strftime("%d-%m-%Y %H:%M"),
        "total_students": len(students)
    }
    with open(class_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=4)
        
    write_audit_log(advisor["username"], "Generate Certificates", None, dept, class_name)
    return RedirectResponse(url="/advisor", status_code=303)

@app.post("/advisor/submit")
def submit_to_hod(request: Request):
    advisor = request.session.get("advisor")
    if not advisor:
        return RedirectResponse(url="/login", status_code=303)
        
    dept = advisor["department"]
    class_name = advisor["class"]
    
    if is_class_submitted(dept, class_name):
        return RedirectResponse(url="/advisor", status_code=303)
        
    # Trigger freeze, submission metadata creation and ZIP generation
    submit_to_hod_workflow(advisor["username"], dept, class_name)
    write_audit_log(advisor["username"], "Submit to HOD", None, dept, class_name)
    return RedirectResponse(url="/advisor", status_code=303)

@app.get("/advisor/download-zip")
def download_class_zip(request: Request):
    advisor = request.session.get("advisor")
    if not advisor:
        return RedirectResponse(url="/login")
        
    dept = advisor["department"]
    class_name = advisor["class"]
    
    class_dir = get_class_folder(dept, class_name)
    zip_filename = f"{class_name.replace(' ', '_')}.zip"
    zip_path = class_dir / zip_filename
    
    # Re-generate zip if it doesn't exist
    if not zip_path.exists():
        generate_class_zip(dept, class_name)
        
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="ZIP file not found.")
        
    download_filename = get_class_zip_filename(class_name)
    return FileResponse(
        path=zip_path,
        media_type="application/x-zip-compressed",
        filename=download_filename
    )

def get_authorized_user(request: Request):
    """
    Returns logged-in user dict if any of office, principal, hod, or advisor session exists.
    Otherwise returns None.
    """
    for role_key in ["office", "principal", "hod", "advisor"]:
        user = request.session.get(role_key)
        if user:
            return user
    return None

def find_student_class_by_reg(register_number: str):
    """
    Searches generated and approval directories to discover department and class_name
    for a given student register number if not provided in the request or session.
    """
    reg_clean = str(register_number).strip()
    
    # 1. Search generated/final
    final_base = Path("generated/final")
    if final_base.exists():
        for dept_dir in final_base.iterdir():
            if dept_dir.is_dir():
                for c_dir in dept_dir.iterdir():
                    if c_dir.is_dir():
                        if (c_dir / "html" / f"{reg_clean}.html").exists() or (c_dir / "pdf" / f"{reg_clean}.pdf").exists():
                            return dept_dir.name, c_dir.name.replace("_", " ")

    # 2. Search generated/advisor
    adv_base = Path("generated/advisor")
    if adv_base.exists():
        for dept_dir in adv_base.iterdir():
            if dept_dir.is_dir():
                for c_dir in dept_dir.iterdir():
                    if c_dir.is_dir():
                        if (c_dir / "html" / f"{reg_clean}.html").exists() or (c_dir / "pdf" / f"{reg_clean}.pdf").exists():
                            return dept_dir.name, c_dir.name.replace("_", " ")

    # 3. Search approvals/hod
    hod_base = Path("approvals/hod")
    if hod_base.exists():
        for dept_dir in hod_base.iterdir():
            if dept_dir.is_dir():
                for c_dir in dept_dir.iterdir():
                    if c_dir.is_dir() and (c_dir / "approval.json").exists():
                        try:
                            with open(c_dir / "approval.json", "r", encoding="utf-8") as f:
                                app_data = json.load(f)
                            if any(str(s.get("register_number")).strip() == reg_clean for s in app_data.get("students", [])):
                                return dept_dir.name, c_dir.name.replace("_", " ")
                        except Exception:
                            pass

    return None, None

def is_batch_principal_approved(department: str, class_name: str) -> bool:
    """
    Returns True ONLY if the class/batch has been approved by the Principal
    as recorded in principal_approval.json.
    """
    real_class_name = class_name.replace("_", " ")
    p_meta_file = get_principal_metadata_file(department, real_class_name)
    if p_meta_file.exists():
        try:
            with open(p_meta_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("status") == "Approved"
        except Exception:
            pass
    return False

def sanitize_html_approval_state(html_content: str, is_approved: bool) -> str:
    """
    Sanitizes HTML content to guarantee approval state rules:
    - If NOT approved: replaces real signature/seal image references with pending placeholders.
    - If approved: replaces pending placeholders with real signature/seal image references.
    """
    import re
    if not is_approved:
        html_content = html_content.replace("principal.jpeg", "pending_signature.jpg")
        html_content = html_content.replace("principal.jpg", "pending_signature.jpg")
        html_content = html_content.replace("seal.jpeg", "pending_seal.jpg")
        html_content = html_content.replace("seal.jpg", "pending_seal.jpg")
        html_content = re.sub(r'<img\s+src="[^"]*principal_design\.(jpeg|jpg)"[^>]*>', '', html_content)
    else:
        html_content = html_content.replace("pending_signature.jpg", "principal.jpeg")
        html_content = html_content.replace("pending_seal.jpg", "seal.jpeg")
    return html_content

@app.get("/tc/download-pdf/{department}/{class_name}/{register_number}")
@app.get("/advisor/download-pdf/{register_number}")
def download_pdf(
    request: Request,
    register_number: str,
    department: str = None,
    class_name: str = None
):
    user = get_authorized_user(request)
    if not user:
        return RedirectResponse(url="/login")
        
    if not department and "department" in user:
        department = user["department"]
    if not class_name and "class" in user:
        class_name = user["class"]
    elif not class_name and "class_name" in user:
        class_name = user["class_name"]
        
    if not department or not class_name:
        auto_dept, auto_class = find_student_class_by_reg(register_number)
        if auto_dept and auto_class:
            department = auto_dept
            class_name = auto_class

    if not department or not class_name:
        raise HTTPException(status_code=400, detail="Department and Class Name are required.")
        
    real_class_name = class_name.replace("_", " ")
    approved = is_batch_principal_approved(department, real_class_name)
    
    if approved:
        final_pdf = get_final_class_folder(department, real_class_name) / "pdf" / f"{register_number}.pdf"
        if final_pdf.exists():
            pdf_path = final_pdf
        else:
            from services.advisor.principal_dashboard_service import load_principal_state, regenerate_final_certificates
            p_state = load_principal_state(department, real_class_name)
            approved_regs = [s["register_number"] for s in p_state.get("students", []) if s["status"] == "Approved"]
            regenerate_final_certificates(department, real_class_name, approved_regs)
            pdf_path = final_pdf
    else:
        advisor_pdf = get_class_folder(department, real_class_name) / "pdf" / f"{register_number}.pdf"
        pdf_path = advisor_pdf
        
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found. Please generate certificates first.")
        
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"TC_{register_number}.pdf"
    )

@app.get("/tc/download-html/{department}/{class_name}/{register_number}")
@app.get("/advisor/download-html/{register_number}")
def download_html(
    request: Request,
    register_number: str,
    department: str = None,
    class_name: str = None
):
    user = get_authorized_user(request)
    if not user:
        return RedirectResponse(url="/login")
        
    if not department and "department" in user:
        department = user["department"]
    if not class_name and "class" in user:
        class_name = user["class"]
    elif not class_name and "class_name" in user:
        class_name = user["class_name"]
        
    if not department or not class_name:
        auto_dept, auto_class = find_student_class_by_reg(register_number)
        if auto_dept and auto_class:
            department = auto_dept
            class_name = auto_class

    if not department or not class_name:
        raise HTTPException(status_code=400, detail="Department and Class Name are required.")

        
    real_class_name = class_name.replace("_", " ")
    approved = is_batch_principal_approved(department, real_class_name)
    
    if approved:
        final_html = get_final_class_folder(department, real_class_name) / "html" / f"{register_number}.html"
        html_path = final_html if final_html.exists() else get_class_folder(department, real_class_name) / "html" / f"{register_number}.html"
    else:
        html_path = get_class_folder(department, real_class_name) / "html" / f"{register_number}.html"
    
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="HTML not found. Please generate certificates first.")
        
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
        
    app_base_dir = Path(__file__).parent
    css_path = app_base_dir / "static" / "css" / "style.css"
    if css_path.exists():
        with open(css_path, "r", encoding="utf-8") as f:
            css_content = f.read()
        html_content = html_content.replace(
            '<link rel="stylesheet" href="../../static/css/style.css">',
            f'<style>\n{css_content}\n</style>'
        )
        
    def to_base64(filepath: Path, mime: str) -> str:
        if filepath.exists():
            with open(filepath, "rb") as img_f:
                b64_data = base64.b64encode(img_f.read()).decode("utf-8")
            return f"data:{mime};base64,{b64_data}"
        return ""
        
    for img_name, mime in [("watermark", "image/png"), ("logo", "image/png"), ("pending_seal", "image/jpeg"), ("pending_signature", "image/jpeg"), ("seal", "image/jpeg"), ("principal", "image/jpeg"), ("principal_design", "image/jpeg")]:
        img_b64 = ""
        for ext in ['.jpeg', '.jpg', '.png']:
            p = app_base_dir / "static" / "images" / f"{img_name}{ext}"
            if p.exists():
                img_b64 = to_base64(p, mime)
                break
                
        if img_b64:
            for ext in ['.jpeg', '.jpg', '.png']:
                html_content = html_content.replace(f"../../static/images/{img_name}{ext}", img_b64)
        
    import re
    photo_frame_match = re.search(r'<div class="photo-frame">\s*<img\s+src="([^"]+)"', html_content)
    if photo_frame_match:
        photo_src = photo_frame_match.group(1)
        photo_filename = photo_src.split('/')[-1]
        
        c_dir = get_class_folder(department, real_class_name)
        photo_path = c_dir / "preview" / photo_filename
        
        if not photo_path.exists():
            for ext in ['.jpg', '.jpeg', '.png']:
                p = c_dir / "preview" / f"{register_number}{ext}"
                if p.exists():
                    photo_path = p
                    break
                    
        if not photo_path.exists():
            photo_path = app_base_dir / "static" / "images" / photo_filename
            
        if photo_path.exists():
            mime = "image/png" if photo_path.suffix.lower() == ".png" else "image/jpeg"
            photo_b64 = to_base64(photo_path, mime)
            if photo_b64:
                html_content = html_content.replace(photo_src, photo_b64)
                
    html_content = sanitize_html_approval_state(html_content, approved)
    return Response(
        content=html_content,
        media_type="text/html",
        headers={"Content-Disposition": f"attachment; filename=TC_{register_number}.html"}
    )

PREVIEW_ONLY_CSS = """
<style>
img.principal-designation-img {
    width: 175px;
}
.principal-sign {
    position: absolute;
    top: -6mm;
    width: 36mm;
    height: auto;
    left: 50%;
    transform: translateX(-50%);
}
</style>
"""

def inject_preview_styles(html_content: str) -> str:
    """Injects preview-only CSS rules into the HTML string right before </head>."""
    if "</head>" in html_content:
        return html_content.replace("</head>", f"{PREVIEW_ONLY_CSS}\n</head>")
    return html_content + PREVIEW_ONLY_CSS

@app.get("/tc/preview/html/{department}/{class_name}/{register_number}", response_class=HTMLResponse)
@app.get("/advisor/preview/html/{department}/{class_name}/{register_number}", response_class=HTMLResponse)
def preview_html_in_browser(department: str, class_name: str, register_number: str, request: Request):
    """
    Renders the generated student certificate HTML file in the browser for any authorized role.
    If the student is approved by Principal, it loads the signed final HTML.
    Otherwise, it loads the advisor-generated HTML.
    """
    user = get_authorized_user(request)
    if not user:
        return HTMLResponse(content="<h3>Unauthorized</h3>", status_code=401)
        
    real_class_name = class_name.replace("_", " ")
    approved = is_batch_principal_approved(department, real_class_name)
    
    final_dir = get_final_class_folder(department, real_class_name)
    final_html = final_dir / "html" / f"{register_number}.html"
    
    class_dir = get_class_folder(department, real_class_name)
    advisor_html = class_dir / "html" / f"{register_number}.html"
    
    if approved and final_html.exists():
        html_path = final_html
        preview_photo_prefix = f"/generated/final/{department}/{class_name}/preview/"
    elif advisor_html.exists():
        html_path = advisor_html
        preview_photo_prefix = f"/generated/advisor/{department}/{class_name}/preview/"
    else:
        return HTMLResponse(content="<h3>Certificate HTML not generated yet.</h3>", status_code=404)
        
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
        
    html_content = html_content.replace("../../static/", "/static/")
    html_content = html_content.replace("../static/", "/static/")
    html_content = html_content.replace("../preview/", preview_photo_prefix)
    
    html_content = sanitize_html_approval_state(html_content, approved)
    html_content = inject_preview_styles(html_content)
    return HTMLResponse(content=html_content)




# ================= HOD SIMULATOR =================

@app.post("/advisor/simulate-hod")
def simulate_hod(request: Request, action: str = Form(...)):
    """Simulates HOD actions: Approving, Rejecting, or Resetting the submission (for testing)."""
    advisor = request.session.get("advisor")
    if not advisor:
        return RedirectResponse(url="/login", status_code=303)
        
    dept = advisor["department"]
    class_name = advisor["class"]
    class_dir = get_class_folder(dept, class_name)
    
    if action == "approve":
        # Set all students status to Approved
        update_all_students_status(dept, class_name, "Approved")
        
        # Update submission.json status
        sub_file = get_submission_file(dept, class_name)
        if sub_file.exists():
            with open(sub_file, "r") as f:
                sub_data = json.load(f)
            sub_data["status"] = "Approved"
            with open(sub_file, "w") as f:
                json.dump(sub_data, f, indent=4)
                
            # Re-generate zip to include updated submission.json
            generate_class_zip(dept, class_name)
            
    elif action == "reject":
        # Set all students status to Rejected
        update_all_students_status(dept, class_name, "Rejected")
        
        # Update submission.json status
        sub_file = get_submission_file(dept, class_name)
        if sub_file.exists():
            with open(sub_file, "r") as f:
                sub_data = json.load(f)
            sub_data["status"] = "Rejected"
            with open(sub_file, "w") as f:
                json.dump(sub_data, f, indent=4)
                
            # Re-generate zip
            generate_class_zip(dept, class_name)
            
    elif action == "reset":
        # Delete submission.json and update students status back to Generated (unfreezing)
        sub_file = get_submission_file(dept, class_name)
        if sub_file.exists():
            sub_file.unlink()
            
        zip_path = class_dir / f"{class_name.replace(' ', '_')}.zip"
        if zip_path.exists():
            zip_path.unlink()
            
        update_all_students_status(dept, class_name, "Generated")
        
        # Update batch metadata back to GENERATED
        meta_path = class_dir / "metadata.json"
        if meta_path.exists():
            with open(meta_path, "r") as f:
                meta = json.load(f)
            meta["status"] = "GENERATED"
            with open(meta_path, "w") as f:
                json.dump(meta, f, indent=4)
                
    return RedirectResponse(url="/advisor", status_code=303)


# ================= HOD PORTAL =================

HODS_FILE = Path("data/hods.json")

@app.get("/hod/login", response_class=HTMLResponse)
def hod_login_page(request: Request):
    if request.session.get("hod"):
        return RedirectResponse(url="/hod")
    return templates.TemplateResponse(request=request, name="hod_login.html", context={"error": None})

@app.post("/hod/login")
def hod_login(
    request: Request, 
    username: str = Form(...), 
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    hod_match = db.query(DBUser).filter(
        DBUser.username == username,
        DBUser.password == password,
        DBUser.role == "hod"
    ).first()
            
    if hod_match:
        request.session["hod"] = {
            "username": hod_match.username,
            "name": hod_match.name,
            "department": hod_match.department
        }
        return RedirectResponse(url="/hod", status_code=303)
    else:
        return templates.TemplateResponse(request=request, name="hod_login.html", context={"error": "Invalid username or password."})

@app.get("/hod/logout")
def hod_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")

@app.get("/hod")
def hod_dashboard(request: Request):
    hod = request.session.get("hod")
    if not hod:
        return RedirectResponse(url="/hod/login")
        
    dept = hod["department"]
    classes = get_submitted_classes(dept)
    stats = get_hod_stats(dept)
    
    return templates.TemplateResponse(
        request=request,
        name="hod_dashboard.html",
        context={
            "request": request,
            "hod": hod,
            "classes": classes,
            "stats": stats
        }
    )

@app.get("/hod/class/{department}/{class_name}")
def hod_class_detail(request: Request, department: str, class_name: str):
    hod = request.session.get("hod")
    if not hod:
        return RedirectResponse(url="/hod/login")
        
    real_class_name = class_name.replace("_", " ")
    
    # 1. Load submission metadata to verify advisor has submitted
    advisor_folder = get_advisor_class_folder(department, real_class_name)
    submission_file = advisor_folder / "submission.json"
    if not submission_file.exists():
        raise HTTPException(status_code=404, detail="This class has not been submitted by the advisor yet.")
        
    with open(submission_file, "r") as f:
        submission = json.load(f)
        
    # 2. Load HOD approval state
    approval_state = load_approval_state(department, real_class_name)
    students = approval_state.get("students", [])
    students.sort(key=lambda s: (STATUS_PRIORITY.get(s.get("status", ""), 99), s.get("register_number", "")))
    
    # Calculate stats for the class
    total = len(students)
    approved = sum(1 for s in students if s["status"] == "Approved")
    rejected = sum(1 for s in students if s["status"] == "Rejected")
    pm = sum(1 for s in students if s.get("parent_meeting_required"))
    
    class_stats = {
        "total": total,
        "approved": approved,
        "rejected": rejected,
        "parent_meeting": pm
    }
    
    return templates.TemplateResponse(
        request=request,
        name="hod_class_detail.html",
        context={
            "request": request,
            "hod": hod,
            "department": department,
            "class_name": real_class_name,
            "submission": submission,
            "students": students,
            "class_stats": class_stats
        }
    )

@app.post("/hod/action/class")
def hod_action_class(
    request: Request,
    department: str = Form(...),
    class_name: str = Form(...),
    action: str = Form(...),
    rejection_reason: str = Form(None)
):
    hod = request.session.get("hod")
    if not hod:
        return RedirectResponse(url="/hod/login", status_code=303)
        
    approval_state = load_approval_state(department, class_name)
    
    if action == "approve_all":
        approval_state["status"] = "Approved"
        for s in approval_state["students"]:
            s["status"] = "Approved"
            s["rejection_reason"] = ""
        write_audit_log(hod["username"], "HOD Approve Entire Class", None, department, class_name)
            
    elif action == "reject_all":
        if not rejection_reason or not rejection_reason.strip():
            raise HTTPException(status_code=400, detail="Rejection reason is mandatory.")
        approval_state["status"] = "Rejected"
        for s in approval_state["students"]:
            s["status"] = "Rejected"
            s["rejection_reason"] = rejection_reason.strip()
        write_audit_log(hod["username"], f"HOD Reject Entire Class. Reason: {rejection_reason}", None, department, class_name)
            
    approval_state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_approval_state(department, class_name, approval_state)
    sync_status_to_advisor(department, class_name, approval_state)
    
    # Generate the approved ZIP if approved
    if action == "approve_all":
        generate_approved_zip(department, class_name)
        
    class_name_param = class_name.replace(" ", "_")
    return RedirectResponse(url=f"/hod/class/{department}/{class_name_param}", status_code=303)

@app.post("/hod/action/student")
def hod_action_student(
    request: Request,
    department: str = Form(...),
    class_name: str = Form(...),
    register_number: str = Form(...),
    action: str = Form(...),
    rejection_reason: str = Form(None),
    parent_meeting: str = Form(None),
    remarks: str = Form(None)
):
    hod = request.session.get("hod")
    if not hod:
        return RedirectResponse(url="/hod/login", status_code=303)
        
    approval_state = load_approval_state(department, class_name)
    students = approval_state.get("students", [])
    
    student_match = next((s for s in students if s["register_number"] == register_number), None)
    if not student_match:
        raise HTTPException(status_code=404, detail="Student not found in this class.")
        
    if action == "approve":
        student_match["status"] = "Approved"
        student_match["rejection_reason"] = ""
        write_audit_log(hod["username"], "HOD Approve Student", register_number, department, class_name)
        
    elif action == "reject":
        if not rejection_reason or not rejection_reason.strip():
            raise HTTPException(status_code=400, detail="Rejection reason is mandatory.")
        student_match["status"] = "Rejected"
        student_match["rejection_reason"] = rejection_reason.strip()
        write_audit_log(hod["username"], f"HOD Reject Student. Reason: {rejection_reason}", register_number, department, class_name)
        
    elif action == "save_remarks":
        # Only allowed if student's conduct is poor
        if student_match.get("conduct", "").lower() == "poor":
            student_match["parent_meeting_required"] = (parent_meeting == "true" or parent_meeting == "on")
            student_match["remarks"] = remarks.strip() if remarks else ""
        write_audit_log(hod["username"], f"HOD Save Remarks (PM Required: {parent_meeting})", register_number, department, class_name)
            
    # Calculate new overall class status based on student statuses
    all_approved = all(s["status"] == "Approved" for s in students)
    all_rejected = all(s["status"] == "Rejected" for s in students)
    
    if all_approved:
        approval_state["status"] = "Approved"
    elif all_rejected:
        approval_state["status"] = "Rejected"
    else:
        approval_state["status"] = "Partially Approved"
        
    approval_state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_approval_state(department, class_name, approval_state)
    sync_status_to_advisor(department, class_name, approval_state)
    
    # Generate approved ZIP
    generate_approved_zip(department, class_name)
    
    class_name_param = class_name.replace(" ", "_")
    return RedirectResponse(url=f"/hod/class/{department}/{class_name_param}", status_code=303)

@app.get("/hod/download-approved-zip/{department}/{class_name}")
def download_approved_zip(request: Request, department: str, class_name: str):
    hod = request.session.get("hod")
    if not hod:
        return RedirectResponse(url="/hod/login")
        
    real_class_name = class_name.replace("_", " ")
    zip_path = generate_approved_zip(department, real_class_name)
    
    download_filename = get_class_zip_filename(real_class_name, "approved")
    
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Approved ZIP file could not be generated.")
        
    return FileResponse(
        path=zip_path,
        media_type="application/x-zip-compressed",
        filename=download_filename
    )

@app.get("/hod/preview/html/{department}/{class_name}/{register_number}", response_class=HTMLResponse)
def hod_preview_html_in_browser(department: str, class_name: str, register_number: str, request: Request):
    """
    Renders the student certificate HTML file for the HOD in the browser,
    fixing path references dynamically for the iframe.
    """
    hod = request.session.get("hod")
    if not hod:
        return HTMLResponse(content="<h3>Unauthorized</h3>", status_code=401)
        
    real_class_name = class_name.replace("_", " ")
    approved = is_batch_principal_approved(department, real_class_name)
    
    if approved:
        final_dir = get_final_class_folder(department, real_class_name)
        final_html = final_dir / "html" / f"{register_number}.html"
        html_path = final_html if final_html.exists() else get_advisor_class_folder(department, real_class_name) / "html" / f"{register_number}.html"
        class_path_uri = f"/generated/final/{department}/{class_name}/preview/"
    else:
        html_path = get_advisor_class_folder(department, real_class_name) / "html" / f"{register_number}.html"
        class_path_uri = f"/generated/advisor/{department}/{class_name}/preview/"
    
    if not html_path.exists():
        return HTMLResponse(content="<h3>Certificate HTML not generated yet.</h3>", status_code=404)
        
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
        
    html_content = html_content.replace("../../static/", "/static/")
    html_content = html_content.replace("../preview/", class_path_uri)
    
    html_content = sanitize_html_approval_state(html_content, approved)
    html_content = inject_preview_styles(html_content)
    return HTMLResponse(content=html_content)



# ================= PRINCIPAL PORTAL =================

@app.get("/principal/login", response_class=HTMLResponse)
def principal_login_page(request: Request):
    if request.session.get("principal"):
        return RedirectResponse(url="/principal")
    return templates.TemplateResponse(request=request, name="principal_login.html", context={"error": None})

@app.post("/principal/login")
def principal_login(
    request: Request, 
    username: str = Form(...), 
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    principal_match = db.query(DBUser).filter(
        DBUser.username == username,
        DBUser.password == password,
        DBUser.role == "principal"
    ).first()
            
    if principal_match:
        request.session["principal"] = {
            "username": principal_match.username,
            "name": principal_match.name
        }
        return RedirectResponse(url="/principal", status_code=303)
    else:
        return templates.TemplateResponse(request=request, name="principal_login.html", context={"error": "Invalid username or password."})

@app.get("/principal/logout")
def principal_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")

@app.get("/principal")
def principal_dashboard(request: Request):
    principal = request.session.get("principal")
    if not principal:
        return RedirectResponse(url="/principal/login")
        
    batches = get_batches_for_principal()
    stats = get_principal_stats()
    
    office_direct_batches = [b for b in batches if b.get("workflow_type") == "Office Direct Upload"]
    advisor_batches = [b for b in batches if b.get("workflow_type") != "Office Direct Upload"]
    
    return templates.TemplateResponse(
        request=request,
        name="principal_dashboard.html",
        context={
            "request": request,
            "principal": principal,
            "batches": batches,
            "office_direct_batches": office_direct_batches,
            "advisor_batches": advisor_batches,
            "stats": stats
        }
    )


@app.get("/principal/class/{department}/{class_name}")
def principal_class_detail(request: Request, department: str, class_name: str):
    principal = request.session.get("principal")
    if not principal:
        return RedirectResponse(url="/principal/login")
        
    real_class_name = class_name.replace("_", " ")
    
    # 1. Load submission metadata from advisor submission or HOD approval or Principal approval
    advisor_folder = get_advisor_class_folder(department, real_class_name)
    submission_file = advisor_folder / "submission.json"
    
    submission = {}
    if submission_file.exists():
        with open(submission_file, "r", encoding="utf-8") as f:
            submission = json.load(f)
    else:
        from services.advisor.hod_dashboard_service import get_approval_file
        app_file = get_approval_file(department, real_class_name)
        if app_file.exists():
            with open(app_file, "r", encoding="utf-8") as f:
                app_data = json.load(f)
            wf_type = app_data.get("workflow_type", "Office Direct Upload")
            adv_name = "Office" if wf_type == "Office Direct Upload" else "Advisor"
            submission = {
                "advisor": adv_name,
                "department": department,
                "class": real_class_name,
                "submitted_time": app_data.get("last_updated", ""),
                "student_count": len(app_data.get("students", [])),
                "status": app_data.get("status", "Submitted to Principal"),
                "workflow_type": wf_type
            }
        else:
            p_meta = get_principal_metadata_file(department, real_class_name)
            if p_meta.exists():
                with open(p_meta, "r", encoding="utf-8") as f:
                    p_data = json.load(f)
                submission = {
                    "advisor": "Office" if p_data.get("workflow_type") == "Office Direct Upload" else "Advisor",
                    "department": department,
                    "class": real_class_name,
                    "submitted_time": p_data.get("approval_time", ""),
                    "student_count": p_data.get("certificate_count", 0),
                    "status": p_data.get("status", "Approved"),
                    "workflow_type": p_data.get("workflow_type", "Office Direct Upload")
                }
            else:
                raise HTTPException(status_code=404, detail="No submission or approval record found for this class.")
        
    # 2. Load Principal approval state
    p_state = load_principal_state(department, real_class_name)
    students = p_state.get("students", [])
    students.sort(key=lambda s: (STATUS_PRIORITY.get(s.get("status", ""), 99), s.get("register_number", "")))

    
    # Calculate stats for the class
    total = len(students)
    approved = sum(1 for s in students if s["status"] == "Approved")
    rejected = sum(1 for s in students if s["status"] == "Rejected")
    
    class_stats = {
        "total": total,
        "hod_approved": sum(1 for s in students if s["status"] in ["Approved", "Submitted to HOD"]),
        "approved": approved,
        "rejected": rejected
    }
    
    return templates.TemplateResponse(
        request=request,
        name="principal_class_detail.html",
        context={
            "request": request,
            "principal": principal,
            "department": department,
            "class_name": real_class_name,
            "submission": submission,
            "students": students,
            "class_stats": class_stats
        }
    )

@app.post("/principal/action/class")
def principal_action_class(
    request: Request,
    department: str = Form(...),
    class_name: str = Form(...),
    action: str = Form(...),
    rejection_reason: str = Form(None)
):
    principal = request.session.get("principal")
    if not principal:
        return RedirectResponse(url="/principal/login", status_code=303)
        
    p_state = load_principal_state(department, class_name)
    
    if action == "approve_all":
        p_state["status"] = "Approved"
        p_state["approval_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        approved_regs = []
        for s in p_state["students"]:
            s["status"] = "Approved"
            s["rejection_reason"] = ""
            approved_regs.append(s["register_number"])
        p_state["certificate_count"] = len(approved_regs)
        
        # Save state first so ZIP generator reads it
        save_principal_state(department, class_name, p_state)
            
        # Regenerate final certificates with actual signature!
        regenerate_final_certificates(department, class_name, approved_regs)
        # Generate final ZIP
        generate_final_zip(department, class_name)
        
        write_audit_log(principal["username"], "Principal Approve Entire Class", None, department, class_name)
        
    elif action == "reject_all":
        if not rejection_reason or not rejection_reason.strip():
            raise HTTPException(status_code=400, detail="Rejection reason is mandatory.")
        p_state["status"] = "Rejected"
        p_state["approval_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for s in p_state["students"]:
            s["status"] = "Rejected"
            s["rejection_reason"] = rejection_reason.strip()
        p_state["certificate_count"] = 0
        
        save_principal_state(department, class_name, p_state)
            
        write_audit_log(principal["username"], f"Principal Reject Entire Class. Reason: {rejection_reason}", None, department, class_name)
    
    class_name_param = class_name.replace(" ", "_")
    return RedirectResponse(url=f"/principal/class/{department}/{class_name_param}", status_code=303)

@app.post("/principal/action/student")
def principal_action_student(
    request: Request,
    department: str = Form(...),
    class_name: str = Form(...),
    register_number: str = Form(...),
    action: str = Form(...),
    rejection_reason: str = Form(None)
):
    principal = request.session.get("principal")
    if not principal:
        return RedirectResponse(url="/principal/login", status_code=303)
        
    p_state = load_principal_state(department, class_name)
    students = p_state.get("students", [])
    
    student_match = next((s for s in students if s["register_number"] == register_number), None)
    if not student_match:
        raise HTTPException(status_code=404, detail="Student not found in this class.")
        
    if action == "approve":
        student_match["status"] = "Approved"
        student_match["rejection_reason"] = ""
        write_audit_log(principal["username"], "Principal Approve Student", register_number, department, class_name)
        
    elif action == "reject":
        if not rejection_reason or not rejection_reason.strip():
            raise HTTPException(status_code=400, detail="Rejection reason is mandatory.")
        student_match["status"] = "Rejected"
        student_match["rejection_reason"] = rejection_reason.strip()
        write_audit_log(principal["username"], f"Principal Reject Student. Reason: {rejection_reason}", register_number, department, class_name)
        
    # Calculate overall class status
    all_approved = all(s["status"] == "Approved" for s in students)
    all_rejected = all(s["status"] == "Rejected" for s in students)
    
    if all_approved:
        p_state["status"] = "Approved"
    elif all_rejected:
        p_state["status"] = "Rejected"
    else:
        p_state["status"] = "Partially Approved"
        
    p_state["approval_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    p_state["certificate_count"] = sum(1 for s in students if s["status"] == "Approved")
    
    save_principal_state(department, class_name, p_state)
    
    # Regenerate certificates for approved students
    approved_regs = [s["register_number"] for s in students if s["status"] == "Approved"]
    regenerate_final_certificates(department, class_name, approved_regs)
    generate_final_zip(department, class_name)
    
    class_name_param = class_name.replace(" ", "_")
    return RedirectResponse(url=f"/principal/class/{department}/{class_name_param}", status_code=303)

@app.get("/principal/download-final-zip/{department}/{class_name}")
def download_final_zip(request: Request, department: str, class_name: str):
    principal = request.session.get("principal")
    if not principal:
        return RedirectResponse(url="/principal/login")
        
    real_class_name = class_name.replace("_", " ")
    zip_path = generate_final_zip(department, real_class_name)
    
    download_filename = get_class_zip_filename(real_class_name, "final")
    
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Final ZIP file could not be generated.")
        
    # Log download action
    write_audit_log(principal["username"], "Download Final ZIP", None, department, real_class_name)
    
    return FileResponse(
        path=zip_path,
        media_type="application/x-zip-compressed",
        filename=download_filename
    )

@app.get("/principal/preview/html/{department}/{class_name}/{register_number}", response_class=HTMLResponse)
def principal_preview_html_in_browser(department: str, class_name: str, register_number: str, request: Request):
    """
    Renders the student certificate HTML file for the Principal in the browser.
    If the student is approved by the Principal, it loads the actual signature.
    Otherwise, it loads the placeholder signature.
    """
    principal = request.session.get("principal")
    if not principal:
        return HTMLResponse(content="<h3>Unauthorized</h3>", status_code=401)
        
    real_class_name = class_name.replace("_", " ")
    p_state = load_principal_state(department, real_class_name)
    student_match = next((s for s in p_state.get("students", []) if s["register_number"] == register_number), None)
    
    # Determine which folder to load HTML from (final or advisor)
    is_final_approved = student_match and student_match["status"] == "Approved"
    
    if is_final_approved:
        class_dir = get_final_class_folder(department, real_class_name)
        html_path = class_dir / "html" / f"{register_number}.html"
        preview_photo_prefix = f"/generated/final/{department}/{class_name}/preview/"
    else:
        class_dir = get_advisor_class_folder(department, real_class_name)
        html_path = class_dir / "html" / f"{register_number}.html"
        preview_photo_prefix = f"/generated/advisor/{department}/{class_name}/preview/"
        
    if not html_path.exists():
        # Fall back to advisor's HTML if final approved HTML was not generated yet
        class_dir = get_advisor_class_folder(department, real_class_name)
        html_path = class_dir / "html" / f"{register_number}.html"
        preview_photo_prefix = f"/generated/advisor/{department}/{class_name}/preview/"
        
    if not html_path.exists():
        return HTMLResponse(content="<h3>Certificate HTML not generated yet.</h3>", status_code=404)
        
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # Support both relative path styles for static assets (CSS, seal, logo, watermark)
    # MUST replace '../../static/' BEFORE '../static/' to avoid mangling '../../static/' into '..//static/'
    html_content = html_content.replace("../../static/", "/static/")
    html_content = html_content.replace("../static/", "/static/")

    html_content = html_content.replace(
        "../preview/",
        preview_photo_prefix
    )

    approved = is_batch_principal_approved(department, real_class_name)
    html_content = sanitize_html_approval_state(html_content, approved)
    html_content = inject_preview_styles(html_content)

    return HTMLResponse(
        content=html_content,
        media_type="text/html; charset=utf-8"
    )



# ================= OFFICE PORTAL =================

def get_logged_in_office(request: Request):
    """Dependency to retrieve logged in office user from session."""
    office = request.session.get("office")
    if not office:
        raise HTTPException(status_code=307, detail="Not logged in")
    return office

@app.get("/office/login", response_class=HTMLResponse)
def office_login_page(request: Request):
    if request.session.get("office"):
        return RedirectResponse(url="/office")
    return templates.TemplateResponse(request=request, name="office_login.html", context={"error": None})

@app.post("/office/login")
def office_login(
    request: Request, 
    username: str = Form(...), 
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    office_match = db.query(DBUser).filter(
        DBUser.username == username,
        DBUser.password == password,
        DBUser.role == "office"
    ).first()
            
    if office_match:
        request.session["office"] = {
            "username": office_match.username,
            "name": office_match.name
        }
        return RedirectResponse(url="/office", status_code=303)
    else:
        return templates.TemplateResponse(request=request, name="office_login.html", context={"error": "Invalid username or password."})

@app.get("/office/logout")
def office_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


@app.get("/office")
def office_dashboard(request: Request):
    office = request.session.get("office")
    if not office:
        return RedirectResponse(url="/office/login")
        
    batches = get_all_batches()
    stats = get_office_stats()
    rejected_students = get_all_rejected_students()
    
    upload_errors = request.session.pop("office_upload_errors", None)
    upload_success = request.session.pop("office_upload_success", None)
    notify_success = request.session.pop("office_notify_success", None)
    
    return templates.TemplateResponse(
        request=request,
        name="office_dashboard.html",
        context={
            "request": request,
            "office": office,
            "batches": batches,
            "stats": stats,
            "rejected_students": rejected_students,
            "upload_errors": upload_errors,
            "upload_success": upload_success,
            "notify_success": notify_success
        }
    )

@app.post("/office/upload")
def office_upload_csv(
    request: Request,
    department: str = Form(...),
    class_name: str = Form(...),
    students_csv: UploadFile = File(...),
    photos_zip: UploadFile = File(None)
):
    office = request.session.get("office")
    if not office:
        return RedirectResponse(url="/office/login", status_code=303)
        
    dept = department.strip().upper()
    c_name = class_name.strip()
    
    class_dir = get_class_folder(dept, c_name)
    (class_dir / "csv").mkdir(parents=True, exist_ok=True)
    (class_dir / "html").mkdir(parents=True, exist_ok=True)
    (class_dir / "pdf").mkdir(parents=True, exist_ok=True)
    (class_dir / "preview").mkdir(parents=True, exist_ok=True)
    
    csv_path = class_dir / "csv" / "students.csv"
    with open(csv_path, "wb") as buffer:
        shutil.copyfileobj(students_csv.file, buffer)
        
    errors = validate_csv_data(csv_path)
    if errors:
        if csv_path.exists():
            csv_path.unlink()
        request.session["office_upload_errors"] = errors
        return RedirectResponse(url="/office", status_code=303)
        
    if photos_zip and photos_zip.filename:
        temp_zip = class_dir / "temp_photos.zip"
        with open(temp_zip, "wb") as buffer:
            shutil.copyfileobj(photos_zip.file, buffer)
        try:
            with zipfile.ZipFile(temp_zip, "r") as zip_ref:
                zip_ref.extractall(class_dir / "preview")
            static_images_dir = Path("static/images")
            static_images_dir.mkdir(parents=True, exist_ok=True)
            dept_images_dir = Path("generated/advisor") / dept / "static" / "images"
            dept_images_dir.mkdir(parents=True, exist_ok=True)
            for f in (class_dir / "preview").iterdir():
                if f.is_file() and f.suffix.lower() in [".jpg", ".jpeg", ".png"]:
                    shutil.copy(f, static_images_dir / f.name)
                    shutil.copy(f, dept_images_dir / f.name)
        except Exception as e:
            request.session["office_upload_errors"] = [f"Failed to extract photo zip: {str(e)}"]
            return RedirectResponse(url="/office", status_code=303)
        finally:
            if temp_zip.exists():
                temp_zip.unlink()
                
    dept_static = Path("generated/advisor") / dept / "static"
    shutil.copytree("static", dept_static, dirs_exist_ok=True)
    shutil.copy("static/images/principal_placeholder.jpg", dept_static / "images" / "principal.jpg")
    
    students = load_students_from_csv(dept, c_name)
    for s in students:
        reg_no = s.get("register_number", "")
        photo_filename = s.get("student_photo", "")
        preview_photo = class_dir / "preview" / photo_filename
        reg_photo = class_dir / "preview" / f"{reg_no}.jpg"
        if preview_photo.exists() and photo_filename:
            s["student_photo"] = photo_filename
        elif reg_photo.exists():
            s["student_photo"] = f"{reg_no}.jpg"
        else:
            s["student_photo"] = "principal.jpg"
            
    temp_csv_backup = Path("data/students_backup.csv")
    main_csv = Path("data/students.csv")
    if main_csv.exists():
        shutil.copy(main_csv, temp_csv_backup)
    try:
        shutil.copy(csv_path, main_csv)
        generate_certificates(students, str(class_dir / "html"), str(class_dir / "pdf"))
    finally:
        if temp_csv_backup.exists():
            shutil.copy(temp_csv_backup, main_csv)
            temp_csv_backup.unlink()
            
    # Automatically submit Office Direct Upload to Principal (Workflow B)
    submit_office_batch_to_principal(dept, c_name, office["username"])
    
    write_audit_log(office["username"], "Office Upload CSV & Photos (Direct to Principal)", None, dept, c_name)
    request.session["office_upload_success"] = f"Batch '{c_name}' ({dept}) submitted to Principal — Waiting for Principal approval"
    return RedirectResponse(url="/office", status_code=303)


@app.post("/office/submit-to-principal")
def office_submit_to_principal(
    request: Request,
    department: str = Form(...),
    class_name: str = Form(...)
):
    office = request.session.get("office")
    if not office:
        return RedirectResponse(url="/office/login", status_code=303)
        
    submit_office_batch_to_principal(department, class_name, office["username"])
    write_audit_log(office["username"], "Office Submit Batch Direct to Principal", None, department, class_name)
    return RedirectResponse(url="/office", status_code=303)

@app.get("/office/class/{department}/{class_name}")
def office_class_detail(request: Request, department: str, class_name: str):
    office = request.session.get("office")
    if not office:
        return RedirectResponse(url="/office/login")
        
    real_class_name = class_name.replace("_", " ")
    advisor_folder = get_class_folder(department, real_class_name)
    
    submission_file = advisor_folder / "submission.json"
    submission = None
    if submission_file.exists():
        with open(submission_file, "r") as f:
            submission = json.load(f)
            
    students = load_students_status(department, real_class_name)
    
    total = len(students)
    approved = sum(1 for s in students if s.get("status") == "Approved")
    rejected = sum(1 for s in students if s.get("status") == "Rejected")
    
    class_stats = {
        "total": total,
        "approved": approved,
        "rejected": rejected
    }
    
    return templates.TemplateResponse(
        request=request,
        name="office_class_detail.html",
        context={
            "request": request,
            "office": office,
            "department": department,
            "class_name": real_class_name,
            "submission": submission,
            "students": students,
            "class_stats": class_stats
        }
    )

@app.get("/office/download-final-zip/{department}/{class_name}")
def office_download_final_zip(request: Request, department: str, class_name: str):
    office = request.session.get("office")
    if not office:
        return RedirectResponse(url="/office/login")
        
    real_class_name = class_name.replace("_", " ")
    zip_path = generate_final_zip(department, real_class_name)
    
    if not zip_path.exists():
        class_dir = get_class_folder(department, real_class_name)
        zip_path = class_dir / f"{real_class_name.replace(' ', '_')}.zip"
        if not zip_path.exists():
            generate_class_zip(department, real_class_name)
            
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="ZIP file not found.")
        
    download_filename = get_class_zip_filename(real_class_name, "final")
    write_audit_log(office["username"], "Office Download Final ZIP", None, department, real_class_name)
    
    return FileResponse(
        path=zip_path,
        media_type="application/x-zip-compressed",
        filename=download_filename
    )

@app.post("/office/notify-advisor")
def office_notify_advisor(
    request: Request,
    student_name: str = Form(...),
    identifier: str = Form(...),
    department: str = Form(...),
    class_name: str = Form(...),
    rejection_reason: str = Form(...)
):
    office = request.session.get("office")
    if not office:
        return RedirectResponse(url="/office/login", status_code=303)
        
    send_rejection_notification(
        office_user=office["username"],
        student_name=student_name,
        identifier=identifier,
        department=department,
        class_name=class_name,
        rejection_reason=rejection_reason
    )
    
    write_audit_log(office["username"], f"Office Notify Advisor for {student_name}", identifier, department, class_name)
    request.session["office_notify_success"] = True
    return RedirectResponse(url="/office", status_code=303)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)