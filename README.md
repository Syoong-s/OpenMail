# TeleMail

> [中文版](README-CN.md)

A desktop email client featuring multiple inbox layout modes and unified multi-account management. Supporting Windows 11 (x64) and Linux (x86-64), TeleMail processes all email data, account credentials, and attachment previews locally without relying on proprietary cloud services or telemetry uploads. Key features include IMAP/SMTP multi-account management, smart inbox categorization, custom filtering rules, conversation thread views, an address book, scheduled sending, and offline document preview powered by bundled PDF.js.

---

## Usage

### 1. Installation & Launch

Download the release package for your platform from GitHub Releases (current version: `0.55.3`), or run directly from source on Linux:

| Release package | Runtime dependencies | Installed automatically? |
| --- | --- | --- |
| Windows 11 x64 ZIP | Python, GTK, OpenSSL and Antiword are bundled; Microsoft Edge WebView2 Evergreen Runtime must be available on the system. | WebView2 is preinstalled on standard Windows 11 systems. If missing, install it manually; TeleMail does not install it automatically. Fully extract the ZIP before launching. |
| Debian / Ubuntu amd64 DEB | Python 3.12+, GTK 3.24+, Fontconfig, OpenSSL 3, WebKitGTK 4.1, SVG loader (`librsvg2-common`) and glibc >= 2.34; optional `antiword` for legacy `.doc` previews. | `sudo apt install ./telemail-desktop_0.55.3_amd64.deb` installs declared dependencies when compatible versions are available from configured repositories. `antiword` is not declared and must be installed separately for `.doc` previews. |
| Linux x86-64 portable tar.gz | Python 3.12+, GTK 3.24+, Fontconfig, OpenSSL 3, WebKitGTK 4.1, an SVG loader and glibc >= 2.34; optional `antiword` for legacy `.doc` previews. | No. Install missing system dependencies manually before launching; extracting or running the archive does not install them. |

The actual minimum glibc version depends on the build host; compatibility with older Linux distributions is not guaranteed. See the [build guide](docs/BUILDING.md).

* **Windows 11 (x64)**
Extract `telemail-0.55.3-windows-amd64.zip` (keeping the complete directory structure intact) and double-click `TeleMail-Windows-amd64/TeleMail.exe`. The archive bundles the required Python and GTK runtimes—neither a local Python installation nor WSL is needed. Only the Microsoft Edge WebView2 Evergreen Runtime is required on the host system.
* **Debian / Ubuntu (amd64)**
Install `telemail-desktop_0.55.3_amd64.deb` (the system package manager will resolve dependencies automatically). Once installed, launch the app from your desktop application menu or run `telemail` in a terminal:
```bash
sudo apt install ./telemail-desktop_0.55.3_amd64.deb

```


* **Linux Portable Archive (x86-64)**
Extract `telemail-0.55.3-linux-amd64.tar.gz` and run the `TeleMail` executable inside (requires system installations of Python 3.12+, GTK 3.24+, Fontconfig, OpenSSL 3, WebKitGTK 4.1, and `glibc >= 2.34`):
```bash
tar -xzf telemail-0.55.3-linux-amd64.tar.gz
./TeleMail-Linux-amd64/TeleMail
# Optional: register a desktop shortcut for the current user
./TeleMail-Linux-amd64/TeleMail --install-user

```


* **Run from Source (Linux)**
Once the Linux runtime dependencies listed above are satisfied, launch directly from the repository root:
```bash
./run.sh
# Or enter demo mode using synthetic emails (does not connect to real mailboxes or send outgoing mail)
./run.sh --demo

```



### 2. Account Configuration & Common Commands

* **Adding Accounts**: On first launch, add your email account via the setup wizard or navigate to **Settings → Accounts**. Built-in configuration templates are provided for Gmail, Outlook, Microsoft 365, and generic IMAP/SMTP servers. Authentication supports standard passwords, app-specific passwords, or self-registered OAuth 2.0 client IDs (this project does not ship with pre-embedded public Google/Microsoft OAuth client IDs).
* **Command-Line Arguments**:
```bash
TeleMail --demo                              # Demo mode (uses an isolated demo directory and synthetic emails)
TeleMail --config <file> --data <dir>        # Specify custom configuration file and local data directory
TeleMail mailto:user@example.com             # Open an unsent draft window with the recipient pre-filled
TeleMail --version                           # Display current version and platform information

```



### 3. Important Notes

* **Interface Font Size & Sidebar**: Choose **Settings → Appearance → 界面字号** from 10–32 (default 14). Changes preview immediately, with Save and Cancel controlling persistence. Popup widths and heights follow the chosen font within the available window. The fixed navigation rail is 40 logical pixels wide and gives pinned folders the remaining window height; scrolling is needed only when they exceed that space. Expanded folder/mailbox sidebars now default to 300 logical pixels and remain draggable; saved widths are preserved. Email body text and PDF zoom retain their own settings.

* **Windows Multiple Displays**: Windows system-aware whole-window scaling keeps windows, text and floating editors consistent across 100%, 150% and 200% displays. Fractional scaling on other displays may look slightly softer. Large editors can temporarily expand the main window, refit to the current monitor, and restore automatic growth on close while preserving manual resizes.

> **Important (Auto-Cleanup Policy)**: After connecting a real email account, please review the automatic cleanup policy under **Settings → Storage** first. By default, **unpinned inbox emails older than 365 days** are moved to the server Trash folder (which your email provider may subsequently purge permanently). To keep all inbox messages indefinitely, disable this option or adjust the retention period immediately after setup.

* **Offline PDF Viewer**: PDF attachments are rendered offline via localhost loopback using the bundled PDF.js 6.4.299 engine. It supports continuous scrolling, zooming, text selection, full-text search highlighting, and password unlocking without uploading documents to external servers (OCR is not provided for scanned PDFs).
* **Send Later & Read Receipts**: Scheduled emails require the application to remain running; tasks that come due while the application is closed will be processed upon the next launch. Read receipts depend on whether the recipient's email client supports and responds to receipt requests.
* **Further Documentation**: See [Privacy & Data Policy](https://www.google.com/search?q=docs/PRIVACY.md), [Build & Testing Guide](https://www.google.com/search?q=docs/BUILDING.md), and [Developer Guide](https://www.google.com/search?q=Develop.md) for details.

---

## License

* **First-Party Code**: TeleMail's original application code, native adaptation layers, and build scripts are licensed under the **[MIT License](https://www.google.com/search?q=LICENSE)**.
* **Third-Party Components**: Bundled or referenced third-party components (including PDF.js, Noto Sans CJK SC fonts, CPython, MSYS2/GTK runtimes, Microsoft WebView2 Loader, etc.) retain their original licenses and copyright notices. See [NOTICE](https://www.google.com/search?q=NOTICE) and [Third-Party Components](https://www.google.com/search?q=docs/THIRD_PARTY.md) for full details.
* **Windows Combined Binary Distribution**: The Windows release archive includes the standalone subprocess utility Antiword (`GPL-2.0-or-later`) and indirectly loads JBIG-KIT (`GPL-2.0-or-later`) via GdkPixbuf/libtiff. Consequently, the combined Windows binary distribution as a whole is provided under the terms of **GPLv3 or later (`GPL-3.0-or-later`)** accompanied by the corresponding source code, while TeleMail's own original code remains available under the MIT License. Please refer to [Windows Combined Distribution Licensing](https://www.google.com/search?q=docs/WINDOWS_LICENSE.md) for details.
