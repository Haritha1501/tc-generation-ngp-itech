import json
import unittest
import shutil
import zipfile
import io
from pathlib import Path
from fastapi.testclient import TestClient
import sys

# Ensure project root is in python path
sys.path.append(str(Path(__file__).parent.parent))

from app import app
from services.advisor.advisor_dashboard_service import get_class_folder
from services.advisor.hod_dashboard_service import get_hod_class_folder
from services.advisor.principal_dashboard_service import get_final_class_folder, get_audit_log_file
from services.office.notification_service import NOTIFICATIONS_FILE

class TestOfficeWorkflow(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.username = "office"
        self.password = "password123"
        self.dept = "CSE"
        self.class_name = "2024-2028-CSE-OFFICE"
        
        self.class_dir = get_class_folder(self.dept, self.class_name)
        self.hod_dir = get_hod_class_folder(self.dept, self.class_name)
        self.final_dir = get_final_class_folder(self.dept, self.class_name)
        
        # Clean up existing folders
        for d in [self.class_dir, self.hod_dir, self.final_dir]:
            if d.exists():
                shutil.rmtree(d)
                
        if NOTIFICATIONS_FILE.exists():
            NOTIFICATIONS_FILE.unlink()

    def tearDown(self):
        for d in [self.class_dir, self.hod_dir, self.final_dir]:
            if d.exists():
                shutil.rmtree(d)
        if NOTIFICATIONS_FILE.exists():
            NOTIFICATIONS_FILE.unlink()

    def test_office_login_and_logout(self):
        # 1. Access office without login -> redirect
        response = self.client.get("/office", follow_redirects=False)
        self.assertEqual(response.status_code, 307)

        # 2. Login invalid credentials
        response = self.client.post("/office/login", data={"username": "office", "password": "wrongpassword"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Invalid username or password", response.text)

        # 3. Login valid credentials
        response = self.client.post("/office/login", data={"username": self.username, "password": self.password}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].endswith("/office"))

        # 4. Access dashboard
        response = self.client.get("/office")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Central Office Portal", response.text)

        # 5. Logout
        response = self.client.get("/office/logout", follow_redirects=False)
        self.assertIn(response.status_code, [302, 303, 307])


    def test_workflow_b_office_direct_upload_and_principal_approval(self):
        # 1. Login as Office
        self.client.post("/office/login", data={"username": self.username, "password": self.password}, follow_redirects=False)

        # 2. Upload CSV & Photos (Workflow B)
        csv_content = (
            "tc_number,umis_number,admission_number,student_name,parent_name,gender,dob,dob_words,"
            "nationality,course,roll_number,register_number,class_leaving,admission_date,medium,"
            "last_attended,reason_leaving,conduct,certificate_date,student_photo\n"
            "TC801,UMIS801,ADM-OFFICE-01,Bob Williams,Charles Williams,Male,15/05/2005,FIFTEENTH MAY TWO THOUSAND AND FIVE,"
            "INDIAN,B.E. CSE,23CS801,727823TUCS801,2024-2028-CSE-OFFICE,12-08-2023,ENGLISH,"
            "20-04-2026,COURSE COMPLETED,Excellent,12-07-2026,727823TUCS801.jpg\n"
        )
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            zip_file.writestr("727823TUCS801.jpg", b"fake_image")
        zip_data = zip_buffer.getvalue()

        files = {
            "students_csv": ("students.csv", csv_content, "text/csv"),
            "photos_zip": ("photos.zip", zip_data, "application/zip")
        }
        data = {
            "department": self.dept,
            "class_name": self.class_name
        }

        response = self.client.post("/office/upload", data=data, files=files, follow_redirects=False)
        self.assertEqual(response.status_code, 303)

        # 3. Direct submit to Principal
        response = self.client.post("/office/submit-to-principal", data=data, follow_redirects=False)
        self.assertEqual(response.status_code, 303)

        # 4. Login as Principal and verify batch appears
        self.client.post("/principal/login", data={"username": "principal", "password": "password123"}, follow_redirects=False)
        response = self.client.get("/principal")
        self.assertEqual(response.status_code, 200)
        self.assertIn("2024-2028-CSE-OFFICE", response.text)

        # 5. Principal approves the class
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

        # 6. Login back as Office and verify batch is approved and downloadable
        self.client.post("/office/login", data={"username": self.username, "password": self.password}, follow_redirects=False)
        response = self.client.get("/office")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Principal Approved", response.text)

        # 7. Download Final ZIP from Office
        class_param = self.class_name.replace(" ", "_")
        response = self.client.get(f"/office/download-final-zip/{self.dept}/{class_param}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/x-zip-compressed")

    def test_rejection_and_advisor_notification(self):
        # 1. Setup a rejected student in HOD approval state
        self.hod_dir.mkdir(parents=True, exist_ok=True)
        hod_approval = {
            "department": self.dept,
            "class": self.class_name,
            "status": "Partially Approved",
            "last_updated": "2026-08-08 12:00:00",
            "students": [
                {
                    "register_number": "727823TUCS999",
                    "student_name": "Dave Reject",
                    "status": "Rejected",
                    "conduct": "Poor",
                    "parent_meeting_required": True,
                    "remarks": "Low attendance",
                    "rejection_reason": "Low attendance and fee dues"
                }
            ]
        }
        with open(self.hod_dir / "approval.json", "w", encoding="utf-8") as f:
            json.dump(hod_approval, f, indent=4)

        # 2. Office views rejected students
        self.client.post("/office/login", data={"username": self.username, "password": self.password}, follow_redirects=False)
        response = self.client.get("/office")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Dave Reject", response.text)
        self.assertIn("Low attendance and fee dues", response.text)

        # 3. Office sends notification to Advisor
        response = self.client.post(
            "/office/notify-advisor",
            data={
                "student_name": "Dave Reject",
                "identifier": "727823TUCS999",
                "department": self.dept,
                "class_name": self.class_name,
                "rejection_reason": "Low attendance and fee dues"
            },
            follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)

        # 4. Login as Advisor for CSE department and check dashboard notification alert
        self.client.post("/login", data={"username": "advisor_cse_a", "password": "adv_cse_pswd_a"}, follow_redirects=False)
        response = self.client.get("/advisor")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Rejection Notifications from Central Office", response.text)
        self.assertIn("Dave Reject", response.text)
        self.assertIn("Low attendance and fee dues", response.text)

    def test_end_to_end_office_direct_workflow_and_tc_access(self):
        # STEP 1: Login as Office
        response = self.client.post("/office/login", data={"username": self.username, "password": self.password}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)

        # STEP 2 - 7: Upload & Process Batch (Workflow B)
        class_name = "2024-2028-CSE-E2E"
        class_dir = get_class_folder("CSE", class_name)
        final_dir = get_final_class_folder("CSE", class_name)

        csv_content = (
            "tc_number,umis_number,admission_number,student_name,parent_name,gender,dob,dob_words,"
            "nationality,course,roll_number,register_number,class_leaving,admission_date,medium,"
            "last_attended,reason_leaving,conduct,certificate_date,student_photo\n"
            "TC901,UMIS901,ADM-E2E-01,Emma Watson,Chris Watson,Female,20/04/2005,TWENTIETH APRIL TWO THOUSAND AND FIVE,"
            "INDIAN,B.E. CSE,23CS901,727823TUCS901,2024-2028-CSE-E2E,12-08-2023,ENGLISH,"
            "20-04-2026,COURSE COMPLETED,Good,12-07-2026,727823TUCS901.jpg\n"
        )
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            zip_file.writestr("727823TUCS901.jpg", b"fake_image")
        zip_data = zip_buffer.getvalue()

        files = {
            "students_csv": ("students.csv", csv_content, "text/csv"),
            "photos_zip": ("photos.zip", zip_data, "application/zip")
        }
        data = {
            "department": "CSE",
            "class_name": class_name
        }

        response = self.client.post("/office/upload", data=data, files=files, follow_redirects=False)
        self.assertEqual(response.status_code, 303)

        # STEP 8: After successful processing, Office sees status message "Waiting for Principal approval"
        response = self.client.get("/office")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Waiting for Principal approval", response.text)

        # STEP 9: Logout from Office
        response = self.client.get("/office/logout", follow_redirects=False)
        self.assertIn(response.status_code, [302, 303, 307])

        # STEP 10: Login as Principal
        response = self.client.post("/principal/login", data={"username": "principal", "password": "password123"}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)

        # STEP 11 & 12: Open "Office Direct Requests — Pending Approval" and verify batch appears
        response = self.client.get("/principal")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Office Direct Requests — Pending Approval", response.text)
        self.assertIn("2024-2028-CSE-E2E", response.text)

        # STEP 13 & 14: Principal reviews and approves batch
        response = self.client.post(
            "/principal/action/class",
            data={
                "department": "CSE",
                "class_name": class_name,
                "action": "approve_all"
            },
            follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)

        # STEP 15: Logout from Principal
        response = self.client.get("/principal/logout", follow_redirects=False)
        self.assertIn(response.status_code, [302, 303, 307])

        # STEP 16: Login as Office again
        response = self.client.post("/office/login", data={"username": self.username, "password": self.password}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)

        # STEP 17: Batch appears as Approved / Final TCs
        response = self.client.get("/office")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Principal Approved", response.text)

        # STEP 18: Office opens TC - Preview, HTML, and PDF MUST work without 401 or login redirect
        class_param = class_name.replace(" ", "_")
        reg_no = "727823TUCS901"

        # 18a: Preview
        response = self.client.get(f"/tc/preview/html/CSE/{class_param}/{reg_no}")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Unauthorized", response.text)
        self.assertIn("Emma Watson", response.text)

        # 18b: HTML Download
        response = self.client.get(f"/tc/download-html/CSE/{class_param}/{reg_no}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Emma Watson", response.text)

        # 18c: PDF Download
        response = self.client.get(f"/tc/download-pdf/CSE/{class_param}/{reg_no}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")

        # Cleanup E2E test folders
        hod_dir = get_hod_class_folder("CSE", class_name)
        for d in [class_dir, hod_dir, final_dir]:
            if d.exists():
                shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()

