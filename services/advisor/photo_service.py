import zipfile
from pathlib import Path


def extract_photos(zip_path, destination):

    with zipfile.ZipFile(zip_path, "r") as zip_ref:

        zip_ref.extractall(destination)