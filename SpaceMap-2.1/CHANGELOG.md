# Changelog

## 2.1

- Extracted directory scanning into a standalone function so it can be tested independently.
- Changed directory enumeration to process `os.scandir()` entries incrementally instead of first building a list of every entry in a directory.
- Added explicit handling for unexpected scan failures in the interface.
- Added automated tests for size formatting, directory totals, cancellation, and invalid paths.
- Updated project documentation with actual behavior and known limits.

## 2.0 Ultimate

- Initial graphical storage analyzer with folder navigation, treemap, search, sorting, and CSV/HTML export.
