import json
import unittest
import shutil
import zipfile
from pathlib import Path
from fastapi.testclient import TestClient
import sys

# Ensure project root is in python path
sys.path.append(str(Path(__file__).parent.parent))

from app import app
from services.advisor.advisor_dashboard_service import get_class_folder
from services.advisor.hod_dashboard_service import get_hod_class_folder
from services.advisor.principal_dashboard_service import get_final_class_folder, get_audit_log_file

class TestPrincipalWorkflow(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.username = "principal"
        self.password = "password123"
        self.dept = "CSE"
        self.class_name = "IV BE CSE A"
        
        self.class_dir = get_class_folder(self.dept, self.class_name)
        self.hod_dir = get_hod_class_folder(self.dept, self.class_name)
        self.final_dir = get_final_class_folder(self.dept, self.class_name)
        
        # Clean up existing folders
        for d in [self.class_dir, self.hod_dir, self.final_dir]:
            if d.exists():
                shutil.rmtree(d)
        
        # Reset audit_log.json
        log_file = get_audit_log_file()
        if log_file.exists():
            log_file.unlink()

        # 1. Create advisor folder structure & CSV
        self.class_dir.mkdir(parents=True, exist_ok=True)
        (self.class_dir / "csv").mkdir(exist_ok=True)
        (self.class_dir / "html").mkdir(exist_ok=True)
        (self.class_dir / "pdf").mkdir(exist_ok=True)
        (self.class_dir / "preview").mkdir(exist_ok=True)
        
        self.csv_content = (
            "tc_number,umis_number,admission_number,student_name,parent_name,gender,dob,dob_words,"
            "nationality,course,roll_number,register_number,class_leaving,admission_date,medium,"
            "last_attended,reason_leaving,conduct,certificate_date,student_photo\n"
            "TC101,UMIS001,ADM-221,Alice,Robert,Female,12/03/2005,TWELFTH MARCH TWO THOUSAND AND FIVE,"
            "INDIAN,B.E. CSE,23CS101,727823TUCS101,IV BE CSE A,12-08-2023,ENGLISH,"
            "20-04-2026,COURSE COMPLETED,Good,12-07-2026,101.jpg\n"
        )
        with open(self.class_dir / "csv" / "students.csv", "w", encoding="utf-8") as f:
            f.write(self.csv_content)
            
        self.advisor_status = [
            {"register_number": "727823TUCS101", "student_name": "Alice", "status": "Generated", "student_photo": "101.jpg"}
        ]
        with open(self.class_dir / "students_status.json", "w", encoding="utf-8") as f:
            json.dump(self.advisor_status, f, indent=4)
            
        self.submission_metadata = {
            "advisor": "advisor_cse",
            "department": self.dept,
            "class": self.class_name,
            "submitted_time": "2026-07-13 22:00:00",
            "student_count": 1,
            "status": "Submitted to HOD"
        }
        with open(self.class_dir / "submission.json", "w", encoding="utf-8") as f:
            json.dump(self.submission_metadata, f, indent=4)

        # 2. Create HOD folder structure & approval.json
        self.hod_dir.mkdir(parents=True, exist_ok=True)
        self.hod_approval = {
            "department": self.dept,
            "class": self.class_name,
            "status": "Approved",
            "last_updated": "2026-07-13 22:05:00",
            "students": [
                {
                    "register_number": "727823TUCS101",
                    "student_name": "Alice",
                    "status": "Approved",
                    "conduct": "Good",
                    "parent_meeting_required": False,
                    "remarks": "",
                    "rejection_reason": ""
                }
            ]
        }
        with open(self.hod_dir / "approval.json", "w", encoding="utf-8") as f:
            json.dump(self.hod_approval, f, indent=4)
            
        # Create dummy HOD approved files
        (self.class_dir / "html" / "727823TUCS101.html").write_text("Placeholder HTML")
        (self.class_dir / "pdf" / "727823TUCS101.pdf").write_text("Placeholder PDF")

    def tearDown(self):
        # Clean up folders
        for d in [self.class_dir, self.hod_dir, self.final_dir]:
            if d.exists():
                shutil.rmtree(d)
        log_file = get_audit_log_file()
        if log_file.exists():
            log_file.unlink()

    def test_principal_portal_workflow(self):
        # 1. Access without login
        response = self.client.get("/principal", follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        
        # 2. Login
        response = self.client.post("/principal/login", data={"username": self.username, "password": self.password}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        
        # 3. Stats and dashboard overview
        response = self.client.get("/principal")
        self.assertEqual(response.status_code, 200)
        self.assertIn("IV BE CSE A", response.text)
        self.assertIn("Pending Principal", response.text)

        # 4. View Class Detail Page
        class_param = self.class_name.replace(" ", "_")
        response = self.client.get(f"/principal/class/{self.dept}/{class_param}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Alice", response.text)
        self.assertIn("727823TUCS101", response.text)

        # 5. Approve class (entire class bulk sign)
        response = self.client.post(
            "/principal/action/class",
            data={
                "department": self.dept,
                "class_name": self.class_name,
                "action": "approve_all"
            },
            follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        
        # Verify final HTML and PDF files were created in final directory
        final_html = self.final_dir / "html" / "727823TUCS101.html"
        final_pdf = self.final_dir / "pdf" / "727823TUCS101.pdf"
        self.assertTrue(final_html.exists())
        self.assertTrue(final_pdf.exists())
        
        # Verify principal_approval.json created
        p_metadata = self.final_dir / "principal_approval.json"
        self.assertTrue(p_metadata.exists())
        with open(p_metadata, "r", encoding="utf-8") as f:
            meta = json.load(f)
            self.assertEqual(meta["principal_name"], "Dr. S.U. PRABHA")
            self.assertEqual(meta["status"], "Approved")
            self.assertEqual(meta["certificate_count"], 1)

        # Verify final ZIP exists and contains approved PDF, CSV, and principal_approval.json
        final_zip = self.final_dir / f"{class_param}_final.zip"
        self.assertTrue(final_zip.exists())
        with zipfile.ZipFile(final_zip, "r") as z:
            namelist = z.namelist()
            self.assertNotIn("html/727823TUCS101.html", namelist)
            self.assertIn("pdf/727823TUCS101.pdf", namelist)
            self.assertIn("csv/students.csv", namelist)
            self.assertIn("principal_approval.json", namelist)

        # 6. Verify audit logging
        audit_file = get_audit_log_file()
        self.assertTrue(audit_file.exists())
        with open(audit_file, "r", encoding="utf-8") as f:
            logs = json.load(f)
            self.assertTrue(len(logs) > 0)
            principal_log = next(log for log in logs if log["user"] == "principal")
            self.assertEqual(principal_log["action"], "Principal Approve Entire Class")
            self.assertEqual(principal_log["class"], self.class_name)

        # 7. Download ZIP endpoint
        response = self.client.get(f"/principal/download-final-zip/{self.dept}/{class_param}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/x-zip-compressed")
        self.assertIn("2024-2028-CSE-A_final.zip", response.headers.get("content-disposition", ""))

if __name__ == "__main__":
    unittest.main()
