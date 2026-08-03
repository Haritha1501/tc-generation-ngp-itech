from services.certificate.csv_reader import get_students
from services.certificate.pdf_generator import generate_pdf
from services.certificate.tc_generator import save_html
from services.certificate.tc_generator import render_certificate
from pathlib import Path


def generate_preview():
    students = get_students("data/students.csv")

    if not students:
        return None

    student = dict(students[0])
    photo_val = str(student.get("student_photo", ""))
    if not photo_val.startswith("/static/images/"):
        student["student_photo"] = "/static/images/" + photo_val.lstrip("/")

    student["principal_signature"] = "/static/images/principal_placeholder.jpg"

    html = render_certificate(student)

    return html


def generate_certificates(
    students,
    html_folder,
    pdf_folder,
    is_final_principal_approval=False
):
    if students is None:
        students = get_students("data/students.csv")

    for student in students:
        student_record = dict(student)
        photo_val = str(student_record.get("student_photo", ""))
        if not photo_val.startswith("/static/images/"):
            student_record["student_photo"] = "/static/images/" + photo_val.lstrip("/")

        if is_final_principal_approval:
            student_record["principal_signature"] = "/static/images/principal.jpeg"
        else:
            student_record["principal_signature"] = "/static/images/principal_placeholder.jpg"

        html_file = save_html(
            student_record,
            html_folder
        )

        pdf_file = Path(pdf_folder) / (
            str(student_record["register_number"]) + ".pdf"
        )

        generate_pdf(
            html_file,
            str(pdf_file)
        )