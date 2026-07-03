# ambient-package-update-script

Script to update all Ambient packages via the ambient-package-update.

## Usage

Ensure all packages in `../ambient-packages/` have an active `.venv` and a `.ambient-package-update/metadata.py` config,
then run:

```bash
python update_projects.py
```

The script will process each package: render templates, update dependencies, lint, bump the patch version, create a
`maintenance/v{version}` branch, tag the commit as `v{version}`, and push both to origin. Pull requests must be created
manually afterward.