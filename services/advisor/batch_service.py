from pathlib import Path


def create_batch(
    department,
    class_name
):

    batch_name = class_name.replace(
        " ",
        "_"
    )

    batch_path = Path(
        f"generated/advisor/{department}/{batch_name}"
    )

    (
        batch_path / "pdf"
    ).mkdir(
        parents=True,
        exist_ok=True
    )

    (
        batch_path / "html"
    ).mkdir(
        exist_ok=True
    )

    (
        batch_path / "photos"
    ).mkdir(
        exist_ok=True
    )

    (
        batch_path / "csv"
    ).mkdir(
        exist_ok=True
    )

    return batch_path