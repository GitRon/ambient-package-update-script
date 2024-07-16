import os
import subprocess
from pathlib import Path


class PackageUpdater:
    """
    Script to perform the recurring update tasks for multiple packages.
    This script assumes that all packages are located in one directory.
    """

    PACKAGE_DIR = Path(__file__).parent.parent.parent / "ambient-packages"
    ENVS_DIR = Path(r"C:\Users\ronny\.virtualenvs")

    # Internal commands
    _PIP_SELF_UPDATE = "-m pip install --upgrade pip"
    _PIP_UPDATE_AMBIENT_UPDATER = "-m pip install -U ambient-package-update"
    _AMBIENT_UPDATER_RENDER_TEMPLATES = "-m ambient_package_update.cli render-templates"
    _PACKAGE_RUFF_LINTING = "pre-commit run --all-files --hook-stage push"
    _PACKAGE_TESTS = "-m pytest --ds settings tests"

    def _print_red(self, text):
        print(f"\033[91m{text}\033[0m")
        exit(1)

    def _print_green(self, text):
        print(f"\033[92m{text}\033[0m")

    def _print_cyan(self, text):
        print(f"\033[96m{text}\033[0m")

    def _run_command(self, command):
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            self._print_green(f"> {result.stdout}")
        else:
            if result.stderr:
                self._print_red(f"> {result.stderr}")
            else:
                self._print_red(f"> {result.stdout}")

    def process(self):
        for directory in self.PACKAGE_DIR.iterdir():
            if directory.is_dir() and (Path(directory) / ".ambient-package-update").is_dir():
                self._print_cyan(f"Processing {directory.name}...")
                venv_exec = self.ENVS_DIR / directory.name / "Scripts/python.exe"
                if not venv_exec.exists():
                    self._print_red("> Venv not found. Aborting.")

                # Switching into package directory
                os.chdir(directory)

                print("> Self-updating pip")
                self._run_command(f"{venv_exec} {self._PIP_SELF_UPDATE}")

                print("> Updating ambient package updater")
                self._run_command(f"{venv_exec} {self._PIP_UPDATE_AMBIENT_UPDATER}")

                print("> Rendering configuration templates")
                self._run_command(f"{venv_exec} {self._AMBIENT_UPDATER_RENDER_TEMPLATES}")

                # It's OK if the linting fails, the auto-formatter is still doing the job
                print("> Running Ruff linting and formatting")
                linting = subprocess.run(self._PACKAGE_RUFF_LINTING, capture_output=True, text=True)
                print(linting.stdout)

                print("> Running unit-tests")
                self._run_command(f"{venv_exec} {self._PACKAGE_TESTS}")


pu = PackageUpdater()
pu.process()
