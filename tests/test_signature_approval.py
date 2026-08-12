import json
import unittest
import shutil
import zipfile
import io
from pathlib import Path
from fastapi.testclient import TestClient
import sys

sys.path.append(str(Path(__file__).parent.parent))

from app import app
from services.advisor.advisor_dashboard_service import get_class_folder
from services.advisor.hod_dashboard_service import get_hod_class_folder
from services.advisor.principal_dashboard_service import get_final_class_folder, get_audit_log_file

class TestSignatureApproval(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.dept = "CSE"
        self.class_name = "IV BE CSE A"
        self.reg_no = "727823TUCS701"

        
        self.class_dir = get_class_folder(self.dept, self.class_name)
        self.hod_dir = get_hod_class_folder(self.dept, self.class_name)
        self.final_dir = get_final_class_folder(self.dept, self.class_name)
        
        for d in [self.class_dir, self.hod_dir, self.final_dir]:
            if d.exists():
                shutil.rmtree(d)

    def tearDown(self):
        for d in [self.class_dir, self.hod_dir, self.final_dir]:
            if d.exists():
                shutil.rmtree(d)

    def test_principal_signature_and_seal_only_after_approval(self):
        class_param = self.class_name.replace(" ", "_")

        # 1. Advisor uploads CSV + photos (Workflow A)
        self.client.post("/login", data={"username": "advisor_cse_a", "password": "adv_cse_pswd_a"}, follow_redirects=False)

        csv_content = (
            "tc_number,umis_number,admission_number,student_name,parent_name,gender,dob,dob_words,"
            "nationality,course,roll_number,register_number,class_leaving,admission_date,medium,"
            "last_attended,reason_leaving,conduct,certificate_date,student_photo\n"
            "TC701,UMIS701,ADM-SIG-01,Grace Hopper,Charles Hopper,Female,09/12/2005,NINTH DECEMBER TWO THOUSAND AND FIVE,"
            "INDIAN,B.E. CSE,23CS701,727823TUCS701,2024-2028-CSE-SIGNTEST,12-08-2023,ENGLISH,"
            "20-04-2026,COURSE COMPLETED,Good,12-07-2026,727823TUCS701.jpg\n"
        )
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            zip_file.writestr("727823TUCS701.jpg", b"fake_image")
        zip_data = zip_buffer.getvalue()
        files = {
            "students_csv": ("students.csv", csv_content, "text/csv"),
            "photos_zip": ("photos.zip", zip_data, "application/zip")
        }



        response = self.client.post("/advisor/upload", files=files, follow_redirects=False)

        self.assertEqual(response.status_code, 303)

        # Advisor generates certificates
        response = self.client.post("/advisor/generate", follow_redirects=False)
        self.assertEqual(response.status_code, 303)

        # Advisor submits to HOD
        response = self.client.post("/advisor/submit", follow_redirects=False)
        self.assertEqual(response.status_code, 303)



        # TEST CASE 1: Before Principal Approval — Advisor View
        # Check Advisor Preview
        response = self.client.get(f"/advisor/preview/html/{self.dept}/{class_param}/{self.reg_no}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("pending_signature.jpg", response.text)
        self.assertIn("pending_seal.jpg", response.text)
        self.assertNotIn("principal.jpeg", response.text)
        self.assertNotIn("seal.jpeg", response.text)

        # Check Advisor HTML Download
        response = self.client.get(f"/advisor/download-html/{self.reg_no}?department={self.dept}&class_name={class_param}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("data:image/jpeg;base64,", response.text)


        # TEST CASE 2: Before Principal Approval — HOD View
        self.client.post("/hod/login", data={"username": "hod_CSE", "password": "hod_cse_pswd"}, follow_redirects=False)
        response = self.client.get(f"/hod/preview/html/{self.dept}/{class_param}/{self.reg_no}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("pending_signature.jpg", response.text)
        self.assertIn("pending_seal.jpg", response.text)
        self.assertNotIn("principal.jpeg", response.text)
        self.assertNotIn("seal.jpeg", response.text)

        # HOD approves batch
        self.client.post(
            "/hod/action/class",
            data={"department": self.dept, "class_name": self.class_name, "action": "approve_all"},
            follow_redirects=False
        )

        # TEST CASE 3: Before Principal Approval — Office View
        self.client.post("/office/login", data={"username": "office", "password": "password123"}, follow_redirects=False)
        response = self.client.get(f"/tc/preview/html/{self.dept}/{class_param}/{self.reg_no}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("pending_signature.jpg", response.text)
        self.assertIn("pending_seal.jpg", response.text)

        # TEST CASE 4: Principal Approves Class
        self.client.post("/principal/login", data={"username": "principal", "password": "password123"}, follow_redirects=False)
        response = self.client.post(
            "/principal/action/class",
            data={"department": self.dept, "class_name": self.class_name, "action": "approve_all"},
            follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)

        # TEST CASE 5 & 6: After Principal Approval — Check All Views
        # Principal Preview
        response = self.client.get(f"/principal/preview/html/{self.dept}/{class_param}/{self.reg_no}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("principal.jpeg", response.text)
        self.assertIn("seal.jpeg", response.text)
        self.assertNotIn("pending_signature.jpg", response.text)
        self.assertNotIn("pending_seal.jpg", response.text)

        # Office Preview
        self.client.post("/office/login", data={"username": "office", "password": "password123"}, follow_redirects=False)
        response = self.client.get(f"/tc/preview/html/{self.dept}/{class_param}/{self.reg_no}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("principal.jpeg", response.text)
        self.assertIn("seal.jpeg", response.text)

        # Advisor HTML Download
        self.client.post("/login", data={"username": "advisor_cse_a", "password": "adv_cse_pswd_a"}, follow_redirects=False)
        response = self.client.get(f"/tc/download-html/{self.dept}/{class_param}/{self.reg_no}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("data:image/jpeg;base64,", response.text)
        self.assertNotIn("pending_signature.jpg", response.text)


        # PDF Download
        response = self.client.get(f"/tc/download-pdf/{self.dept}/{class_param}/{self.reg_no}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")

if __name__ == "__main__":
    unittest.main()
