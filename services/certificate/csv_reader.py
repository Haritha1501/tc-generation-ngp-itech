import pandas as pd


def get_students(csv_path):

    df = pd.read_csv(csv_path)

    return df.to_dict(orient="records")