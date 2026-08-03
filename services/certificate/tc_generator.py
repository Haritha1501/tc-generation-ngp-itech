from pathlib import Path

from jinja2 import Environment, FileSystemLoader


env = Environment(

    loader=FileSystemLoader("templates")

)

template = env.get_template("tc_template.html")


def render_certificate(student):

    return template.render(

        **student

    )

def save_html(student, html_folder):

    html = render_certificate(student)

    html = html.replace(
        '/static/css/style.css',
        '../../static/css/style.css'
    )

    html = html.replace(
        '/static/images/',
        '../../static/images/'
    )

    filename = student["register_number"] + ".html"

    path = Path(

        html_folder

    )

    path.mkdir(

        parents=True,

        exist_ok=True

    )

    html_file = path / filename

    html_file.write_text(

        html,

        encoding="utf-8"

    )

    return str(

        html_file

    )