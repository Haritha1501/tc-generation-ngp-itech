import json
import unittest
import shutil
from pathlib import Path
from fastapi.testclient import TestClient
import sys

# Ensure project root is in python path
sys.path.append(str(Path(__file__).parent.parent))

from app import app
from services.advisor.advisor_dashboard_service import get_class_folder

class TestAdvisorWorkflow(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.username = "advisor_cse_a"
        self.password = "adv_cse_pswd_a"
        self.dept = "CSE"
        self.class_name = "IV BE CSE A"
        self.class_dir = get_class_folder(self.dept, self.class_name)
        
        # Clean up existing class folder if any, to start fresh
        if self.class_dir.exists():
            shutil.rmtree(self.class_dir)

    def tearDown(self):
        # Clean up after test
        if self.class_dir.exists():
            shutil.rmtree(self.class_dir)

    def test_full_workflow(self):
        # 1. Access Dashboard (should redirect to login)
        response = self.client.get("/advisor", follow_redirects=False)
        self.assertIn(response.status_code, [302, 307])
        self.assertTrue(response.headers["location"].endswith("/login"))

        # 2. Perform Login with invalid credentials
        response = self.client.post("/login", data={"username": self.username, "password": "wrongpassword"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Invalid username or password", response.text)

        # 3. Perform Login with correct credentials
        # TestClient maintains session cookies
        response = self.client.post("/login", data={"username": self.username, "password": self.password}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].endswith("/advisor"))

        # 4. Access Dashboard (should succeed now that we are logged in)
        response = self.client.get("/advisor")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Class Advisor Workspace", response.text)
        self.assertIn("IV BE CSE A", response.text)
        self.assertIn("No student data loaded", response.text)

        # 5. Upload CSV & Photos ZIP
        # Prepare a valid CSV content
        csv_content = (
            "tc_number,umis_number,admission_number,student_name,parent_name,gender,dob,dob_words,"
            "nationality,course,roll_number,register_number,class_leaving,admission_date,medium,"
            "last_attended,reason_leaving,conduct,certificate_date,student_photo\n"
            "TC101,UMIS001,ADM-2023-001,Alice Smith,Robert Smith,Female,12/03/2005,TWELFTH MARCH TWO THOUSAND AND FIVE,"
            "INDIAN,B.E. COMPUTER SCIENCE AND ENGINEERING,23CS101,727823TUCS101,IV BE CSE A,12-08-2023,ENGLISH,"
            "20-04-2026,COURSE COMPLETED,Excellent,12-07-2026,727823TUCS101.jpg\n"
        )
        
        # We don't necessarily need a real zip for photos to verify flow, an empty or simple zip works.
        # Let's create a minimal zip file in memory/disk
        import zipfile
        import io
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            zip_file.writestr("727823TUCS101.jpg", b"fake_image_data")
        zip_data = zip_buffer.getvalue()

        files = {
            "students_csv": ("students.csv", csv_content, "text/csv"),
            "photos_zip": ("photos.zip", zip_data, "application/zip")
        }
        
        response = self.client.post("/advisor/upload", files=files, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].endswith("/advisor"))

        # 6. Verify Dashboard lists the student now
        response = self.client.get("/advisor")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Alice Smith", response.text)
        self.assertIn("727823TUCS101", response.text)
        self.assertIn("Not Generated", response.text)

        # 7. Generate Certificates
        response = self.client.post("/advisor/generate", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].endswith("/advisor"))

        # Verify HTML and PDF files were generated
        html_file = self.class_dir / "html" / "727823TUCS101.html"
        pdf_file = self.class_dir / "pdf" / "727823TUCS101.pdf"
        
        self.assertTrue(html_file.exists())
        self.assertTrue(pdf_file.exists())

        # Verify student status is updated to Generated
        response = self.client.get("/advisor")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Generated", response.text)

        # 8. Submit to HOD
        response = self.client.post("/advisor/submit", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].endswith("/advisor"))

        # Verify freezing (submission.json and zip exist)
        submission_json = self.class_dir / "submission.json"
        class_zip = self.class_dir / "IV_BE_CSE_A.zip"
        
        self.assertTrue(submission_json.exists())
        self.assertTrue(class_zip.exists())
        
        with open(submission_json, "r") as f:
            sub_meta = json.load(f)
            self.assertEqual(sub_meta["status"], "Submitted to HOD")
            self.assertEqual(sub_meta["student_count"], 1)

        # 9. Verify dashboard shows frozen state
        response = self.client.get("/advisor")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Batch Frozen", response.text)
        self.assertIn("Submitted to HOD", response.text)

        # 10. Simulate HOD Approval
        response = self.client.post("/advisor/simulate-hod", data={"action": "approve"}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        
        response = self.client.get("/advisor")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Approved by HOD", response.text)

        # 11. Download ZIP
        response = self.client.get("/advisor/download-zip")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/x-zip-compressed")
        self.assertIn("2024-2028-CSE-A.zip", response.headers.get("content-disposition", ""))

        # 12. Simulate reset (unfreeze)
        response = self.client.post("/advisor/simulate-hod", data={"action": "reset"}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        
        response = self.client.get("/advisor")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Batch Frozen", response.text)

if __name__ == "__main__":
    unittest.main()
