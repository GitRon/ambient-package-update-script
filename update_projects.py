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
    _PIP_UPDATE_REQUIRED_PACKAGES = "-m pip install -U ambient-package-update"
    _AMBIENT_UPDATER_RENDER_TEMPLATES = "-m ambient_package_update.cli render-templates"

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

    def _create_header(self, package_name: str):
        title = f"# Processing {package_name} #"
        max_length = len(title)

        # Erstelle die Ausgabe mit der richtigen Länge
        decorative_line = "#" * max_length

        self._print_cyan(f"{decorative_line}\n{title}\n{decorative_line}")

    def _get_next_version(self, file_path: str):
        if not os.path.exists(file_path):
            raise RuntimeError("Version file not found.")

        with open(file_path) as f:
            content = f.read()

        # Find version and increment it by one
        def update_version(match):
            major, minor, patch = (
                match.group(1),
                match.group(2),
                int(match.group(3)) + 1,
            )
            return f'__version__ = "{major}.{minor}.{patch}"'

        updated_content = re.sub(
            r'__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"', update_version, content
        )

        version_match = re.search(
            r'__version__\s*=\s*"(\d+\.\d+\.\d+)"', updated_content
        )

        if version_match:
            return version_match.group(1)
        else:
            raise RuntimeError("No version found.")

    def _increment_version(self, file_path: str):
        if not os.path.exists(file_path):
            raise RuntimeError("Version file not found.")

        with open(file_path) as f:
            content = f.read()

        updated_content = re.sub(
            r'__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"',
            f'__version__ = "{self._get_next_version(file_path=file_path)}"',
            content,
        )

        with open(file_path, "w") as f:
            f.write(updated_content)

    def _update_changelog(self, file_path: str, version: str):
        if not os.path.exists(file_path):
            raise RuntimeError("Changelog file not found.")

        with open(file_path) as f:
            lines = f.readlines()

        while len(lines) < 3:
            lines.append("\n")

        lines.insert(
            2,
            f"""**{version}** ({datetime.date.today()})
  * Maintenance updates via ambient-package-update\n\n""",
        )

        with open(file_path, "w") as f:
            f.writelines(lines)

    def get_main_branch_from_config(self, file_path: str):
        with open(file_path) as f:
            content = f.read()

        branch_match = re.search(r'main_branch\s*=\s*"([\w-]+)"', content)

        if branch_match:
            return branch_match.group(1)
        else:
            return "master"

    def get_package_name_from_config(self, file_path: str):
        with open(file_path) as f:
            content = f.read()

        module_name_match = re.search(r'module_name\s*=\s*"([\w-]+)"', content)
        if module_name_match:
            return module_name_match.group(1)

        package_name_match = re.search(r'package_name\s*=\s*"([\w-]+)"', content)

        if package_name_match:
            return package_name_match.group(1)
        else:
            raise RuntimeError("No package name found.")

    def _check_branch_exists(self, branch_name: str):
        result = subprocess.run(
            ["git", "branch", "--list", branch_name], capture_output=True, text=True
        )
        return bool(result.stdout.strip())

    def process(self):
        for directory in self.PACKAGE_DIR.iterdir():
            if (
                directory.is_dir()
                and (Path(directory) / ".ambient-package-update").is_dir()
            ):
                self._create_header(package_name=directory.name)

                venv_exec = self.ENVS_DIR / directory.name / "Scripts/python.exe"
                if not venv_exec.exists():
                    self._print_red("> Venv not found. Aborting.")

                # Switching into package directory
                os.chdir(directory)

                print("> Check if repo is clean and contains no uncommitted changes")
                self._run_command(self._GIT_DIFF)

                print("> Self-updating pip")
                self._run_command(f"{venv_exec} {self._PIP_SELF_UPDATE}")

                print("> Updating required packages")
                self._run_command(f"{venv_exec} {self._PIP_UPDATE_REQUIRED_PACKAGES}")

                print("> Fetching main branch name from config")
                main_branch = self.get_main_branch_from_config(
                    file_path="./.ambient-package-update/metadata.py"
                )

                print(f"> Ensure we're on the {main_branch} branch")
                self._run_command(f"git checkout {main_branch}")

                package_name = self.get_package_name_from_config(
                    file_path="./.ambient-package-update/metadata.py"
                )
                version = self._get_next_version(
                    file_path=f"./{package_name.replace('-', '_')}/__init__.py"
                )
                branch_name = f"maintenance/v{version}"
                print("> Check if branch already exists")
                branch_already_exists = False
                if self._check_branch_exists(branch_name=branch_name):
                    print("> Switching to git branch")
                    self._run_command(f"git checkout {branch_name}")
                    branch_already_exists = True
                else:
                    print("> Creating and switching to new git branch")
                    self._run_command(f"git switch -c {branch_name}")

                print("> Rendering configuration templates")
                self._run_command(
                    f"{venv_exec} {self._AMBIENT_UPDATER_RENDER_TEMPLATES}"
                )

                print("> Check if something has changed. If not, we're done here")
                result = subprocess.run(self._GIT_DIFF, capture_output=True, text=True)
                if result.returncode == 0:
                    if not branch_already_exists:
                        print("> Removing newly created local branch")
                        self._run_command(f"git checkout {main_branch}")
                        self._run_command(f"git branch -d {branch_name}")
                    self._print_cyan("> No changes. Skipping package.\n\n")
                    continue

                print("> Incrementing version patch release")
                self._increment_version(
                    file_path=f"./{package_name.replace('-', '_')}/__init__.py"
                )

                print("> Adding release notes to changelog")
                self._update_changelog(file_path="./CHANGES.md", version=version)

                branch_name = f"maintenance/v{version}"
                print("> Check if branch already exists")
                if self._check_branch_exists(branch_name=branch_name):
                    print("> Switching to git branch")
                    self._run_command(f"git checkout {branch_name}")
                else:
                    print("> Creating and switching to new git branch")
                    self._run_command(f"git switch -c {branch_name}")

                print("> Adding changes to git")
                self._run_command("git add .")

                print("> Commiting changes")
                self._run_command(f'git commit -m "Maintenance (v{version})"')

                print("> Check if we got all changes")
                self._run_command(self._GIT_DIFF)

                print("> Pushing changes to origin")
                self._run_command(f"git push -u origin {branch_name}")

                # Since GitHub doesn't provide token rotation, we have to create the PRs manually


pu = PackageUpdater()
pu.process()
