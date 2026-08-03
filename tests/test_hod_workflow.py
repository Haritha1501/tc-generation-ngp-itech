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

class TestHODWorkflow(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.username = "hod_CSE"
        self.password = "hod_cse_pswd"
        self.dept = "CSE"
        self.class_name = "IV BE CSE A"
        self.class_dir = get_class_folder(self.dept, self.class_name)
        self.hod_dir = get_hod_class_folder(self.dept, self.class_name)
        
        # Clean up existing class folders if any
        if self.class_dir.exists():
            shutil.rmtree(self.class_dir)
        if self.hod_dir.exists():
            shutil.rmtree(self.hod_dir)
            
        # Create a mock submitted class from advisor side first
        self.class_dir.mkdir(parents=True, exist_ok=True)
        (self.class_dir / "csv").mkdir(exist_ok=True)
        (self.class_dir / "html").mkdir(exist_ok=True)
        (self.class_dir / "pdf").mkdir(exist_ok=True)
        (self.class_dir / "preview").mkdir(exist_ok=True)
        
        # CSV with two students, one of whom has Poor conduct
        self.csv_content = (
            "tc_number,umis_number,admission_number,student_name,parent_name,gender,dob,dob_words,"
            "nationality,course,roll_number,register_number,class_leaving,admission_date,medium,"
            "last_attended,reason_leaving,conduct,certificate_date,student_photo\n"
            "TC101,UMIS001,ADM-221,Alice,Robert,Female,12/03/2005,TWELFTH MARCH TWO THOUSAND AND FIVE,"
            "INDIAN,B.E. CSE,23CS101,727823TUCS101,IV BE CSE A,12-08-2023,ENGLISH,"
            "20-04-2026,COURSE COMPLETED,Good,12-07-2026,101.jpg\n"
            "TC102,UMIS002,ADM-222,Bob,Albert,Male,09/11/2005,NINTH NOVEMBER TWO THOUSAND AND FIVE,"
            "INDIAN,B.E. CSE,23CS102,727823TUCS102,IV BE CSE A,12-08-2023,ENGLISH,"
            "20-04-2026,COURSE COMPLETED,Poor,12-07-2026,102.jpg\n"
        )
        
        with open(self.class_dir / "csv" / "students.csv", "w", encoding="utf-8") as f:
            f.write(self.csv_content)
            
        # Save mock advisor students status
        self.advisor_status = [
            {"register_number": "727823TUCS101", "student_name": "Alice", "status": "Generated", "student_photo": "101.jpg"},
            {"register_number": "727823TUCS102", "student_name": "Bob", "status": "Generated", "student_photo": "102.jpg"}
        ]
        with open(self.class_dir / "students_status.json", "w", encoding="utf-8") as f:
            json.dump(self.advisor_status, f, indent=4)
            
        # Create submission.json mock
        self.submission_metadata = {
            "advisor": "advisor_cse",
            "department": self.dept,
            "class": self.class_name,
            "submitted_time": "2026-07-13 22:00:00",
            "student_count": 2,
            "status": "Submitted to HOD"
        }
        with open(self.class_dir / "submission.json", "w", encoding="utf-8") as f:
            json.dump(self.submission_metadata, f, indent=4)
            
        # Write dummy HTML and PDF files
        (self.class_dir / "html" / "727823TUCS101.html").write_text("Alice HTML")
        (self.class_dir / "html" / "727823TUCS102.html").write_text("Bob HTML")
        (self.class_dir / "pdf" / "727823TUCS101.pdf").write_text("Alice PDF")
        (self.class_dir / "pdf" / "727823TUCS102.pdf").write_text("Bob PDF")

    def tearDown(self):
        # Clean up
        if self.class_dir.exists():
            shutil.rmtree(self.class_dir)
        if self.hod_dir.exists():
            shutil.rmtree(self.hod_dir)

    def test_hod_portal_workflow(self):
        # 1. HOD Dashboard redirect when unauthenticated
        response = self.client.get("/hod", follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertTrue(response.headers["location"].endswith("/hod/login"))

        # 2. Login HOD with valid credentials
        response = self.client.post("/hod/login", data={"username": self.username, "password": self.password}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].endswith("/hod"))

        # 3. Access HOD Dashboard and verify stats
        response = self.client.get("/hod")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Dr. Praveena V (HOD - CSE)", response.text)
        self.assertIn("IV BE CSE A", response.text)
        self.assertIn("Pending Classes", response.text)

        # 4. View Class Detail Page
        class_param = self.class_name.replace(" ", "_")
        response = self.client.get(f"/hod/class/{self.dept}/{class_param}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Alice", response.text)
        self.assertIn("Bob", response.text)
        self.assertIn("Poor", response.text) # Since Bob has Poor conduct

        # 5. Save remarks and parent meeting for Bob (Poor conduct)
        response = self.client.post(
            "/hod/action/student",
            data={
                "department": self.dept,
                "class_name": self.class_name,
                "register_number": "727823TUCS102",
                "action": "save_remarks",
                "parent_meeting": "true",
                "remarks": "Meet HOD before approval"
            },
            follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        
        # Verify approval state updated
        with open(self.hod_dir / "approval.json", "r", encoding="utf-8") as f:
            app_state = json.load(f)
            bob_state = next(s for s in app_state["students"] if s["register_number"] == "727823TUCS102")
            self.assertTrue(bob_state["parent_meeting_required"])
            self.assertEqual(bob_state["remarks"], "Meet HOD before approval")

        # 6. Approve Alice individually
        response = self.client.post(
            "/hod/action/student",
            data={
                "department": self.dept,
                "class_name": self.class_name,
                "register_number": "727823TUCS101",
                "action": "approve"
            },
            follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        
        # Verify Alice is approved
        with open(self.hod_dir / "approval.json", "r", encoding="utf-8") as f:
            app_state = json.load(f)
            alice_state = next(s for s in app_state["students"] if s["register_number"] == "727823TUCS101")
            self.assertEqual(alice_state["status"], "Approved")
            
        # Verify approved ZIP contains Alice but NOT Bob
        zip_path = self.hod_dir / f"{class_param}_approved.zip"
        self.assertTrue(zip_path.exists())
        with zipfile.ZipFile(zip_path, "r") as z:
            namelist = z.namelist()
            self.assertIn("pdf/727823TUCS101.pdf", namelist)
            self.assertNotIn("html/727823TUCS101.html", namelist)
            self.assertNotIn("pdf/727823TUCS102.pdf", namelist)

        # 7. Reject Bob individually (should fail if rejection reason is missing)
        response = self.client.post(
            "/hod/action/student",
            data={
                "department": self.dept,
                "class_name": self.class_name,
                "register_number": "727823TUCS102",
                "action": "reject"
            },
            follow_redirects=False
        )
        # It throws 400 since reason is mandatory
        self.assertEqual(response.status_code, 400)

        # Reject Bob with reason
        response = self.client.post(
            "/hod/action/student",
            data={
                "department": self.dept,
                "class_name": self.class_name,
                "register_number": "727823TUCS102",
                "action": "reject",
                "rejection_reason": "Poor conduct without parent review"
            },
            follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        
        # Verify Bob is rejected with reason in approval.json
        with open(self.hod_dir / "approval.json", "r", encoding="utf-8") as f:
            app_state = json.load(f)
            bob_state = next(s for s in app_state["students"] if s["register_number"] == "727823TUCS102")
            self.assertEqual(bob_state["status"], "Rejected")
            self.assertEqual(bob_state["rejection_reason"], "Poor conduct without parent review")

        # 8. Approve entire class
        response = self.client.post(
            "/hod/action/class",
            data={
                "department": self.dept,
                "class_name": self.class_name,
                "action": "approve_all"
            },
            follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        
        # Verify all approved in approval.json
        with open(self.hod_dir / "approval.json", "r", encoding="utf-8") as f:
            app_state = json.load(f)
            self.assertEqual(app_state["status"], "Approved")
            for s in app_state["students"]:
                self.assertEqual(s["status"], "Approved")

        # Verify approved ZIP contains both Alice and Bob now
        with zipfile.ZipFile(zip_path, "r") as z:
            namelist = z.namelist()
            self.assertIn("pdf/727823TUCS101.pdf", namelist)
            self.assertIn("pdf/727823TUCS102.pdf", namelist)
            self.assertNotIn("html/727823TUCS101.html", namelist)

        # 9. Download approved ZIP endpoint
        response = self.client.get(f"/hod/download-approved-zip/{self.dept}/{class_param}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/x-zip-compressed")
        self.assertIn("2024-2028-CSE-A_approved.zip", response.headers.get("content-disposition", ""))

if __name__ == "__main__":
    unittest.main()
