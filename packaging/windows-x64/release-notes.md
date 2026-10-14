# Logreader v0.8

Portable Windows x64 release for loading logs, analyzing matches, searching,
and working with multiple logs in tabs.

1. Download **Logreader-v0.8-windows-x64.zip** from the release assets.
2. Extract the entire ZIP.
3. Open the **Logreader** folder and double-click **Logreader.exe**.

Keep the `_internal` folder beside the executable. Python does not need to
be installed. This build is unsigned.

To check the download, compare `Get-FileHash .\Logreader-v0.8-windows-x64.zip -Algorithm SHA256`
with **Logreader-v0.8-windows-x64.zip.sha256**.

The ZIP includes the project license, Qt and other dependency notices, and
the matching Logreader source. **Logreader-v0.8-source.zip** is also provided
separately. **THIRD-PARTY-SOURCES.txt** in the release assets lists the
exact-version upstream source downloads for bundled dependencies.

Verified on Windows 11 x64. A clean Windows machine without development
tools has not been tested. File, Settings, Profiles and Help currently
contain disabled "Coming soon..." entries.
