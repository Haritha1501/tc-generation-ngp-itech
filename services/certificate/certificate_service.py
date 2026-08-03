from services.certificate.csv_reader import get_students
from services.certificate.pdf_generator import generate_pdf
from services.certificate.tc_generator import save_html
from services.certificate.tc_generator import render_certificate
from pathlib import Path


def generate_preview():
    students = get_students("data/students.csv")

    if not students:
        return None

    student = students[0]

    student["student_photo"] = "/static/images/" + student["student_photo"]
    student["principal_signature"] = "/static/images/principal.jpeg"

    html = render_certificate(student)

    return html


def generate_certificates(
    students,
    html_folder,
    pdf_folder
):
    if students is None:
        students = get_students("data/students.csv")

    for student in students:

        student["student_photo"] = "/static/images/" + student["student_photo"]
        student["principal_signature"] = "/static/images/principal.jpeg"

        html_file = save_html(
                student,
                html_folder
            )

        pdf_file = Path(pdf_folder) / (
            student["register_number"] + ".pdf"
        )

        generate_pdf(
            html_file,
            str(pdf_file)
        )