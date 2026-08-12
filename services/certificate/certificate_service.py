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
    pdf_folder,
    is_principal_approved: bool = False
):
    if students is None:
        students = get_students("data/students.csv")

    for student in students:

        student["student_photo"] = "/static/images/" + student["student_photo"]
        if is_principal_approved:
            student["principal_signature"] = "/static/images/principal.jpeg"
            student["college_seal"] = "/static/images/seal.jpeg"
            student["is_approved"] = True
        else:
            student["principal_signature"] = "/static/images/pending_signature.jpg"
            student["college_seal"] = "/static/images/pending_seal.jpg"
            student["is_approved"] = False

        html_file = save_html(
                student,
                html_folder
            )

        pdf_file = Path(pdf_folder) / (
            str(student["register_number"]) + ".pdf"
        )

        generate_pdf(
            html_file,
            str(pdf_file)
        )