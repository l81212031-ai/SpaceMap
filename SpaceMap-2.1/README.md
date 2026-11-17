# SpaceMap

A small, offline disk-usage explorer for Windows, macOS and Linux. SpaceMap scans a folder, summarizes file sizes, and displays its immediate contents as an interactive treemap.

## Features

- Scan a folder or a drive without modifying its contents
- Browse folders and inspect file details
- Sort and filter the current folder's contents
- View a size-based treemap
- Open files, reveal them in the file manager, or copy their paths
- Export file lists to CSV and scan summaries to HTML
- Switch between light and dark themes
- Cancel a scan while it is running

## Requirements

- Python 3.10 or newer
- Tkinter (normally included with the standard Python installation)

SpaceMap uses only Python's standard library. No `pip install` step is required.

## Run

```bash
python spacemap.py
```

## Tests

Run the basic scanner and size-formatting tests with:

```bash
python -m unittest discover -s tests -v
```

## Notes and limitations

- Symbolic links are skipped to avoid cycles and prevent following links outside the selected folder.
- Files and folders that the operating system does not allow SpaceMap to read are skipped; the number of access errors is shown after scanning.
- The treemap shows the largest entries first. When a folder contains many entries, smaller entries may be grouped as **Other**.
- The HTML report includes up to 5,000 largest files.
- Reported sizes are logical file sizes, not necessarily the amount of physical disk space allocated by the filesystem.

## Safety

SpaceMap is a read-only analyzer. It does not delete, move, rename, or edit scanned files. Opening a file is an explicit action initiated by the user.

## License

MIT. See [LICENSE](LICENSE).
