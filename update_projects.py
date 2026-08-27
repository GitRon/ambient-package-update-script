import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


class PackageUpdater:
    """
    Script to perform the recurring update tasks for multiple packages.
    This script assumes that all packages are located in one directory.
    """

    SCRIPT_DIR = Path(__file__).parent
    PACKAGE_DIR = SCRIPT_DIR.parent / "ambient-packages"
    REVIEW_FILE = SCRIPT_DIR / "changelog_review.json"

    # Internal commands
    _GIT_DIFF = "git diff --quiet"
    _UV_REQUIRED_PACKAGES = "-U uv ambient-package-update"
    _AMBIENT_UPDATER_RENDER_TEMPLATES = "-m ambient_package_update.cli render-templates"

    def __init__(self):
        self._review_entries = []

    def _print_red(self, text):
        print(f"\033[91m{text}\033[0m")

    def _print_green(self, text):
        print(f"\033[92m{text}\033[0m")

    def _print_cyan(self, text):
        print(f"\033[96m{text}\033[0m")

    def _run_command(self, command, *, ignore_return_code=False):
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0 or ignore_return_code:
            self._print_green(f"> {result.stdout}")
        else:
            if result.stderr:
                self._print_red(f"> {result.stderr}")
            else:
                self._print_red(f"> {result.stdout}")
            exit(1)

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

    # -------------------------------------------------------------------------
    # ambient-package-update changelog
    # -------------------------------------------------------------------------

    def _get_apu_version_from_lock(self) -> str | None:
        lock_path = Path("uv.lock")
        if not lock_path.exists():
            return None
        # The lock may pin several ambient-package-update versions behind
        # Python markers, so collect them all and report the newest one.
        current_name = None
        versions = []
        for line in lock_path.read_text(encoding="utf-8").splitlines():
            name_match = re.match(r'^name\s*=\s*"([^"]+)"', line)
            version_match = re.match(r'^version\s*=\s*"([^"]+)"', line)
            if name_match:
                current_name = name_match.group(1)
            elif version_match and current_name == "ambient-package-update":
                versions.append(version_match.group(1))
        versions = [v for v in versions if re.fullmatch(r"\d+\.\d+\.\d+", v)]
        if not versions:
            return None
        return max(versions, key=self._parse_version)

    def _http_get(self, url: str) -> bytes:
        req = urllib.request.Request(
            url, headers={"User-Agent": "ambient-package-updater"}
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            return response.read()

    def _get_apu_min_python(self) -> tuple[int, int, int] | None:
        """
        Return the minimum Python version required by the latest
        ambient-package-update release on PyPI, parsed from its
        ``requires_python`` metadata (e.g. ``">=3.11"`` -> ``(3, 11, 0)``).
        Returns None if it can't be determined.
        """
        try:
            data = json.loads(
                self._http_get("https://pypi.org/pypi/ambient-package-update/json")
            )
        except Exception as e:
            print(f"> Failed to fetch ambient-package-update metadata: {e}")
            return None
        requires_python = (data.get("info") or {}).get("requires_python") or ""
        match = re.search(r">=\s*(\d+)\.(\d+)(?:\.(\d+))?", requires_python)
        if not match:
            print(
                f"> Could not parse requires_python ({requires_python!r}) —"
                " skipping Python version check"
            )
            return None
        return (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3) or 0),
        )

    def _get_venv_python_version(self, venv_exec: Path) -> tuple[int, int, int] | None:
        """Return the (major, minor, patch) version of the given venv Python."""
        result = subprocess.run(
            [
                str(venv_exec),
                "-c",
                "import sys; print('%d.%d.%d' % sys.version_info[:3])",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        match = re.match(r"(\d+)\.(\d+)\.(\d+)", result.stdout.strip())
        if not match:
            return None
        return (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        )

    def _fetch_apu_changelog(self) -> str | None:
        """Fetches CHANGES.md via PyPI metadata → GitHub raw URL."""
        try:
            data = json.loads(
                self._http_get("https://pypi.org/pypi/ambient-package-update/json")
            )
            github_url = None
            for val in (data.get("info", {}).get("project_urls") or {}).values():
                if "github.com" in (val or "").lower():
                    github_url = val
                    break
            if not github_url:
                print(
                    "> Could not find GitHub URL on PyPI — falling back to generic entry"
                )
                return None
            match = re.search(r"github\.com/([^/]+)/([^/\s#?]+)", github_url)
            if not match:
                print(
                    f"> Could not parse GitHub URL ({github_url}) — falling back to generic entry"
                )
                return None
            owner = match.group(1)
            repo = re.sub(r"\.git$", "", match.group(2))
            for branch in ("main", "master"):
                raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/CHANGES.md"
                try:
                    return self._http_get(raw_url).decode("utf-8")
                except Exception:
                    continue
            print(
                f"> Could not fetch CHANGES.md from {owner}/{repo} — falling back to generic entry"
            )
            return None
        except Exception as e:
            print(f"> Failed to fetch changelog: {e} — falling back to generic entry")
            return None

    @staticmethod
    def _parse_version(v: str) -> tuple[int, int, int]:
        major, minor, patch = v.split(".")
        return (int(major), int(minor), int(patch))

    def _extract_changelog_sections(
        self, content: str, old_version: str, new_version: str
    ) -> str:
        """Return changelog sections with old_version < section <= new_version."""
        old_v = self._parse_version(old_version)
        new_v = self._parse_version(new_version)
        sections = re.split(r"(?=^\*\*\d+\.\d+\.\d+)", content, flags=re.MULTILINE)
        relevant = []
        for section in sections:
            header = re.match(r"^\*\*(\d+\.\d+\.\d+)", section)
            if not header:
                continue
            v = self._parse_version(header.group(1))
            if old_v < v <= new_v:
                body = section[section.index("\n") :].strip()
                if body:
                    relevant.append(body)
        return "\n\n".join(relevant)

    def _prepare_changelog_entry(
        self, version: str, old_apu_version: str | None, new_apu_version: str | None
    ) -> tuple[str, str]:
        """
        Build the changelog entry from the relevant ambient-package-update
        CHANGES.md sections. Returns the entry together with a label describing
        where its content came from. Entries are written unattended and are meant
        to be reworked afterwards, guided by the summary in ``REVIEW_FILE``.
        """
        header = f"**{version}** ({datetime.date.today()})"
        apu_sections = ""

        if old_apu_version and new_apu_version and old_apu_version != new_apu_version:
            print(
                f"> Fetching ambient-package-update changelog"
                f" ({old_apu_version} → {new_apu_version})"
            )
            raw = self._fetch_apu_changelog()
            if raw:
                apu_sections = self._extract_changelog_sections(
                    raw, old_apu_version, new_apu_version
                )
                if not apu_sections:
                    print(
                        "> No matching sections found in CHANGES.md — falling back to generic entry"
                    )

        if apu_sections:
            return (
                f"{header}\n\n{apu_sections}\n",
                "ambient-package-update CHANGES.md",
            )

        return (
            f"{header}\n  * Maintenance updates via ambient-package-update\n",
            "generic fallback",
        )

    def _update_changelog(self, file_path: str, content: str):
        try:
            with open(file_path) as f:
                lines = f.readlines()
        except FileNotFoundError:
            raise RuntimeError("Changelog file not found.")

        while len(lines) < 3:
            lines.append("\n")

        lines.insert(2, content.rstrip() + "\n\n")

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

    def get_dependency_groups_from_config(self, file_path: str):
        """Extract all keys from the optional_dependencies dictionary in the metadata file."""
        import importlib.util

        # Load the module from the file path
        spec = importlib.util.spec_from_file_location("metadata", file_path)
        if spec is None or spec.loader is None:
            return []

        module = importlib.util.module_from_spec(spec)
        sys.modules["metadata"] = module
        spec.loader.exec_module(module)

        # Get the METADATA object and extract optional_dependencies keys
        if hasattr(module, "METADATA") and hasattr(
            module.METADATA, "optional_dependencies"
        ):
            optional_deps = module.METADATA.optional_dependencies
            if isinstance(optional_deps, dict):
                return list(optional_deps.keys())

        return []

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

    def _write_review_summary(self):
        """
        List the changelog entries that were written and dump them to
        ``REVIEW_FILE``, so they can be reworked once the run is through.
        """
        if not self._review_entries:
            self._print_cyan("> No changelog entries were written — nothing to review.")
            return

        self.REVIEW_FILE.write_text(
            json.dumps(self._review_entries, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        line = "#" * 78
        self._print_cyan(f"{line}\n# Changelog review\n{line}")
        for entry in self._review_entries:
            self._print_cyan(
                f"* {entry['package']} v{entry['version']}"
                f" [{entry['branch']}] — {entry['entry_source']}"
            )
            print(f"  {entry['changelog_path']}")
        self._print_cyan(f"\n> Details written to {self.REVIEW_FILE}")
        self._print_cyan(
            "> All branches are committed and pushed already. After reworking a"
            " changelog, amend and force-push it:"
        )
        print(
            '  git commit -a --amend --no-verify -m "Maintenance (v<version>)"'
            " && git push --force-with-lease --no-verify"
        )

    def process(self):
        path_to_metadata = "./.ambient-package-update/metadata.py"

        print("> Updating ambient-package-update for this script's environment")
        self._run_command(f"uv lock --upgrade --directory {self.SCRIPT_DIR}")
        self._run_command(
            f"uv sync --directory {self.SCRIPT_DIR} --python {sys.executable} --frozen"
        )

        min_python = self._get_apu_min_python()
        if min_python:
            self._print_cyan(
                "> Latest ambient-package-update requires Python >= "
                f"{'.'.join(map(str, min_python))}"
            )

        for directory in self.PACKAGE_DIR.iterdir():
            if (
                directory.is_dir()
                and (Path(directory) / ".ambient-package-update").is_dir()
            ):
                self._create_header(package_name=directory.name)

                venv_exec = directory / ".venv/Scripts/python.exe"
                if not venv_exec.exists():
                    self._print_red("> Venv not found. Aborting.")
                    exit(1)

                if min_python:
                    venv_python = self._get_venv_python_version(venv_exec)
                    if venv_python is None:
                        self._print_red(
                            "> Could not determine venv Python version. Aborting."
                        )
                        exit(1)
                    if venv_python < min_python:
                        self._print_red(
                            f"> Venv Python {'.'.join(map(str, venv_python))} in"
                            f" '{directory.name}' is older than the"
                            f" {'.'.join(map(str, min_python))} required by the latest"
                            " ambient-package-update. Recreate this package's venv with"
                            f" Python >= {'.'.join(map(str, min_python))} and re-run."
                            " Aborting."
                        )
                        exit(1)

                # Switching into package directory
                os.chdir(directory)

                print("> Check if repo is clean and contains no uncommitted changes")
                self._run_command(self._GIT_DIFF)

                print(
                    "> Uninstall ambient-package-update to ensure we get the version from PyPI"
                )
                self._run_command(
                    f"uv pip uninstall --python {venv_exec} ambient-package-update"
                )

                print("> Updating required packages")
                self._run_command(
                    f"uv pip install --python {venv_exec} {self._UV_REQUIRED_PACKAGES}"
                )

                print("> Fetching main branch name from config")
                main_branch = self.get_main_branch_from_config(
                    file_path=path_to_metadata
                )

                print(f"> Ensure we're on the {main_branch} branch")
                self._run_command(f"git checkout {main_branch}")

                package_name = self.get_package_name_from_config(
                    file_path=path_to_metadata
                )
                version = self._get_next_version(
                    file_path=f"./{package_name.replace('-', '_')}/__init__.py"
                )
                branch_name = f"maintenance/v{version}"
                print("> Check if branch already exists")
                branch_already_exists = False
                if self._check_branch_exists(branch_name=branch_name):
                    print("> Switching to existing git branch")
                    self._run_command(f"git checkout {branch_name}")
                    init_path = f"./{package_name.replace('-', '_')}/__init__.py"
                    with open(init_path) as f:
                        if f'__version__ = "{version}"' in f.read():
                            branch_already_exists = True
                        else:
                            print(
                                "> Version not yet incremented on branch — treating as new"
                            )
                else:
                    print("> Creating and switching to new git branch")
                    self._run_command(f"git switch -c {branch_name}")

                print("> Rendering configuration templates")
                self._run_command(
                    f"{venv_exec} {self._AMBIENT_UPDATER_RENDER_TEMPLATES}"
                )

                old_apu_version = self._get_apu_version_from_lock()

                print("> Updating and locking dependencies")
                self._run_command("uv lock --upgrade")

                new_apu_version = self._get_apu_version_from_lock()

                print("> Installing dependencies")
                dependency_groups = self.get_dependency_groups_from_config(
                    file_path=path_to_metadata
                )
                groups_args = " ".join(
                    f"--extra {group}" for group in dependency_groups
                )
                uv_sync_command = f"uv sync --python {venv_exec} --frozen {groups_args}"
                self._run_command(uv_sync_command)

                print("> Check if something has changed")
                result = subprocess.run(self._GIT_DIFF, capture_output=True, text=True)
                if result.returncode == 0:
                    if not branch_already_exists:
                        print("> Removing newly created local branch")
                        self._run_command(f"git checkout {main_branch}")
                        self._run_command(f"git branch -d {branch_name}")
                    self._print_cyan("> No changes. Skipping package.\n\n")
                    continue
                else:
                    print("\n")

                if not branch_already_exists:
                    print("> Incrementing version patch release")
                    self._increment_version(
                        file_path=f"./{package_name.replace('-', '_')}/__init__.py"
                    )

                    print("> Preparing changelog entry")
                    changelog_content, entry_source = self._prepare_changelog_entry(
                        version=version,
                        old_apu_version=old_apu_version,
                        new_apu_version=new_apu_version,
                    )
                    self._update_changelog(
                        file_path="./CHANGES.md", content=changelog_content
                    )
                    self._review_entries.append(
                        {
                            "package": directory.name,
                            "version": version,
                            "branch": branch_name,
                            "main_branch": main_branch,
                            "package_dir": str(directory.resolve()),
                            "changelog_path": str((directory / "CHANGES.md").resolve()),
                            "entry_source": entry_source,
                            "apu_version_before": old_apu_version,
                            "apu_version_after": new_apu_version,
                            "entry": changelog_content.rstrip(),
                        }
                    )

                print("> Adding changes to git")
                self._run_command("git add .")

                print("> Run pre-commit linters")
                # Run linters only now that the version bump and changelog entry are in
                # place, so their auto-fixes (ruff format, end-of-file-fixer, trailing
                # whitespace) are applied here instead of aborting the commit below.
                self._run_command("pre-commit run --all-files", ignore_return_code=True)

                print("> Re-staging files adjusted by pre-commit")
                self._run_command("git add .")

                print("> Commiting changes")
                # Linters already ran above (line "Run pre-commit linters"). We don't
                # install the git hooks, but pass --no-verify defensively so any hook a
                # repo happens to have installed can't re-run and abort the commit.
                self._run_command(
                    f'git commit -m "Maintenance (v{version})" --no-verify'
                )

                print("> Check if we got all changes")
                self._run_command(self._GIT_DIFF)

                # todo: macht issues bei squashing und für die boa
                # print("> Creating git tag")
                # self._run_command(f"git tag v{version}")

                print("> Pushing changes to origin")
                # --no-verify for the same defensive reason as the commit above: an
                # installed pre-push hook would re-run the linters, leave ruff's
                # auto-fixes uncommitted, and abort the push.
                self._run_command(f"git push -u origin {branch_name} --no-verify")

                # print("> Pushing tag to origin")
                # self._run_command(f"git push origin v{version}")

                print("> Clean previously built versions")
                if os.path.exists("dist"):
                    shutil.rmtree("dist")

                # Since GitHub doesn't provide token rotation, we have to create the PRs manually

                print("\n\n\n")

        self._write_review_summary()


pu = PackageUpdater()
pu.process()
