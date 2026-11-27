from pydoover.docker import run_app

from .application import SiemensMag8000Application


def main():
    """
    Run the Siemens MAG 8000 application.
    """
    run_app(SiemensMag8000Application())
