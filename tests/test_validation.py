import unittest
import csv
from pathlib import Path
import tempfile
import sys

# Ensure project root is in python path
sys.path.append(str(Path(__file__).parent.parent))

from services.advisor.advisor_dashboard_service import validate_csv_data

class TestCSVValidation(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_dir_path = Path(self.test_dir.name)
        
        # Valid header and data row
        self.valid_header = [
            "tc_number", "umis_number", "admission_number", "student_name", "parent_name",
            "gender", "dob", "dob_words", "nationality", "course", "roll_number",
            "register_number", "class_leaving", "admission_date", "medium", "last_attended",
            "reason_leaving", "conduct", "certificate_date", "student_photo"
        ]
        self.valid_row = {
            "tc_number": "TC101",
            "umis_number": "UMIS9988",
            "admission_number": "ADM2026-001",
            "student_name": "Test Student",
            "parent_name": "Test Parent",
            "gender": "Female",
            "dob": "15/08/2005",
            "dob_words": "FIFTEENTH AUGUST TWO THOUSAND AND FIVE",
            "nationality": "INDIAN",
            "course": "B.E. CSE",
            "roll_number": "23CS101",
            "register_number": "727823TUCS101",
            "class_leaving": "IV BE CSE A",
            "admission_date": "10-08-2023",
            "medium": "ENGLISH",
            "last_attended": "20-04-2026",
            "reason_leaving": "COURSE COMPLETED",
            "conduct": "Good",
            "certificate_date": "12-07-2026",
            "student_photo": "student101.jpg"
        }

    def tearDown(self):
        self.test_dir.cleanup()

    def write_csv(self, header, rows):
        csv_path = self.test_dir_path / "test.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            for r in rows:
                writer.writerow(r)
        return str(csv_path)

    def test_valid_csv_passes(self):
        csv_path = self.write_csv(self.valid_header, [self.valid_row])
        errors = validate_csv_data(csv_path)
        self.assertEqual(errors, [])

    def test_missing_fields(self):
        # Remove a required column
        incomplete_header = self.valid_header.copy()
        incomplete_header.remove("register_number")
        
        incomplete_row = self.valid_row.copy()
        del incomplete_row["register_number"]
        
        csv_path = self.write_csv(incomplete_header, [incomplete_row])
        errors = validate_csv_data(csv_path)
        self.assertTrue(any("Missing required columns" in e for e in errors))

    def test_duplicate_register_numbers(self):
        row2 = self.valid_row.copy()
        row2["tc_number"] = "TC102"
        # Duplicate register_number
        row2["register_number"] = self.valid_row["register_number"]
        
        csv_path = self.write_csv(self.valid_header, [self.valid_row, row2])
        errors = validate_csv_data(csv_path)
        self.assertTrue(any("Duplicate Register Numbers found" in e for e in errors))

    def test_invalid_dob_format(self):
        bad_dob_row = self.valid_row.copy()
        bad_dob_row["dob"] = "2005-08-15" # wrong format, should be dd/mm/yyyy
        
        csv_path = self.write_csv(self.valid_header, [bad_dob_row])
        errors = validate_csv_data(csv_path)
        self.assertTrue(any("Invalid Date of Birth format" in e for e in errors))

    def test_invalid_dob_value(self):
        bad_dob_row = self.valid_row.copy()
        bad_dob_row["dob"] = "31/02/2005" # Feb 31 doesn't exist
        
        csv_path = self.write_csv(self.valid_header, [bad_dob_row])
        errors = validate_csv_data(csv_path)
        self.assertTrue(any("Invalid Date of Birth value" in e for e in errors))

    def test_invalid_admission_number(self):
        bad_adm_row = self.valid_row.copy()
        bad_adm_row["admission_number"] = "ADM 2026" # contains spaces
        
        csv_path = self.write_csv(self.valid_header, [bad_adm_row])
        errors = validate_csv_data(csv_path)
        self.assertTrue(any("Invalid Admission Number" in e for e in errors))

    def test_empty_values(self):
        empty_val_row = self.valid_row.copy()
        empty_val_row["student_name"] = "" # Empty student name
        
        csv_path = self.write_csv(self.valid_header, [empty_val_row])
        errors = validate_csv_data(csv_path)
        self.assertTrue(any("Empty values in columns: student_name" in e for e in errors))

if __name__ == "__main__":
    unittest.main()
