import json
from pathlib import Path


def get_all_batches():

    batches = []

    base = Path("generated/advisor")

    if not base.exists():
        return batches

    for dept in base.iterdir():

        if dept.is_dir():

            for batch in dept.iterdir():

                metadata = batch / "metadata.json"

                if metadata.exists():

                    with open(metadata) as f:

                        batches.append(json.load(f))

    return batches