print("✅ NEW advisor_service.py LOADED")

from services.advisor.batch_service import create_batch
from services.advisor.metadata_service import create_metadata
from services.advisor.upload_service import (
    save_csv,
    extract_photos
)

from services.certificate.csv_reader import get_students
from services.certificate.certificate_service import generate_certificates


def generate_batch(

    department,

    class_name,

    students_csv,

    photos_zip

):

    # Create batch folder

    batch = create_batch(

        department,

        class_name

    )

    # Save uploaded CSV

    csv_path = save_csv(

        students_csv,

        batch

    )

    # Extract uploaded photos

    photo_folder = extract_photos(

        photos_zip,

        batch

    )

    # Read students

    students = get_students(

        str(csv_path)

    )

    # Match photos automatically

    for student in students:

        student["student_photo"] = str(

            photo_folder /

            f"{student['register_number']}.jpg"

        )

    generate_certificates(

        students,

        batch / "html",

        batch / "pdf"

    )

    create_metadata(

        batch,

        department,

        class_name,

        len(students)

    )

    return batch