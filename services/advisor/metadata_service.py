import json

from datetime import datetime


def create_metadata(

    batch_path,

    department,

    class_name,

    total_students

):

    metadata = {

        "department":department,

        "class":class_name,

        "status":"GENERATED",

        "generated_at":

            datetime.now().strftime(

                "%d-%m-%Y %H:%M"

            ),

        "total_students":total_students

    }

    with open(

        batch_path/"metadata.json",

        "w"

    ) as f:

        json.dump(

            metadata,

            f,

            indent=4

        )