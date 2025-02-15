import datetime
import os
import re
import subprocess
from pathlib import Path


class PackageUpdater:
    """
    Script to perform the recurring update tasks for multiple packages.
    This script assumes that all packages are located in one directory.
    """

    PACKAGE_DIR = Path(__file__).parent.parent / "ambient-packages"
    ENVS_DIR = Path(r"C:\Users\ronny\.virtualenvs")

    # Internal commands
    _GIT_DIFF = "git diff --quiet"
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

    def _increment_version(self, file_path: str):
        if not os.path.exists(file_path):
            raise RuntimeError("Version file not found.")

        with open(file_path, "r") as f:
            content = f.read()

        # Find version and increment it by one
        def update_version(match):
            major, minor, patch = match.group(1), match.group(2), int(match.group(3)) + 1
            return f'__version__ = "{major}.{minor}.{patch}"'

        updated_content = re.sub(r'__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"', update_version, content)

        with open(file_path, "w") as f:
            f.write(updated_content)

        version_match = re.search(r'__version__\s*=\s*"(\d+\.\d+\.\d+)"', updated_content)

        if version_match:
            return version_match.group(1)
        else:
            raise RuntimeError("No version found.")

    def _update_changelog(self, file_path: str, version: str):
        if not os.path.exists(file_path):
            raise RuntimeError("Changelog file not found.")

        with open(file_path, "r") as f:
            lines = f.readlines()

        # Sicherstellen, dass es mindestens 3 Zeilen gibt
        while len(lines) < 3:
            lines.append("\n")

        # Neue Zeile an Position 3 einfügen (Index 2, da 0-basiert)
        lines.insert(2, f"""**{version}** ({datetime.date.today()})
  * Maintenance updates via ambient-package-update\n\n""")

        with open(file_path, "w") as f:
            f.writelines(lines)

    def process(self):
        for directory in self.PACKAGE_DIR.iterdir():
            if directory.is_dir() and (Path(directory) / ".ambient-package-update").is_dir():
                self._print_cyan(f"Processing {directory.name}...")
                venv_exec = self.ENVS_DIR / directory.name / "Scripts/python.exe"
                if not venv_exec.exists():
                    self._print_red("> Venv not found. Aborting.")

                # Switching into package directory
                os.chdir(directory)

                # todo: maybe we should create a PR and not run all those pipeline steps locally

                print("> Check if repo is clean and contains no uncommitted changes")
                self._run_command(self._GIT_DIFF)

                print("> Self-updating pip")
                self._run_command(f"{venv_exec} {self._PIP_SELF_UPDATE}")

                print("> Updating ambient package updater")
                self._run_command(f"{venv_exec} {self._PIP_UPDATE_AMBIENT_UPDATER}")

                print("> Rendering configuration templates")
                self._run_command(f"{venv_exec} {self._AMBIENT_UPDATER_RENDER_TEMPLATES}")

                print("> Incrementing version patch release")
                version = self._increment_version(file_path=f"./{directory.name.replace("-", "_")}/__init__.py")

                print("> Adding release notes to changelog")
                self._update_changelog(file_path=f"./CHANGES.md", version=version)

                # It's OK if the linting fails, the auto-formatter is still doing the job
                print("> Use Ruff to lint and format")
                linting = subprocess.run(self._PACKAGE_RUFF_LINTING, capture_output=True, text=True)
                print(linting.stdout)

                # Now check if we need to fix some linting issues
                print("> Running Ruff linting and formatting")
                self._run_command(self._PACKAGE_RUFF_LINTING)

                print("> Running unit-tests")
                self._run_command(f"{venv_exec} {self._PACKAGE_TESTS}")


pu = PackageUpdater()
pu.process()
