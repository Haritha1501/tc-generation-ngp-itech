import shutil
import zipfile
from pathlib import Path


def save_csv(csv_file, batch_path):

    csv_folder = batch_path / "csv"

    csv_folder.mkdir(
        exist_ok=True
    )

    csv_path = csv_folder / "students.csv"

    with open(csv_path, "wb") as buffer:

        shutil.copyfileobj(
            csv_file.file,
            buffer
        )

    return csv_path


def extract_photos(zip_file, batch_path):

    photo_folder = batch_path / "photos"

    photo_folder.mkdir(
        exist_ok=True
    )

    zip_path = photo_folder / "photos.zip"

    with open(zip_path, "wb") as buffer:

        shutil.copyfileobj(
            zip_file.file,
            buffer
        )

    with zipfile.ZipFile(zip_path, "r") as zip_ref:

        zip_ref.extractall(photo_folder)

    zip_path.unlink()

    return photo_folder