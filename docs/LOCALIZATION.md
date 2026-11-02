# Interface languages / 界面语言

TeleMail 0.57.0 includes English and Simplified Chinese. Open **Settings → Appearance → Interface language**, choose a language, click **Save**, and restart the application. The language remains unchanged in the current session, so open editors and drafts are not interrupted.

TeleMail 0.57.0 内置简体中文和完整英文桌面界面。在 **设置 → 外观 → 界面语言** 选择语言，保存后重启生效。当前会话保持原语言，不中断正在编辑的草稿。

## Scope and data boundaries

- The catalog covers the desktop shell, all 16 settings pages, account sign-in, folders, contacts, filters, composer, notifications, application errors and TeleMail-owned PDF viewer controls. English dates do not depend on the Windows regional language.
- Native calendar names also follow the selected language: Windows uses a locale on the application's UI thread, and English Linux sessions use `LC_TIME=C`. The system language and timezone are unchanged. GTK 3 reads Windows calendar names through `GetThreadLocale`, as shown in its [calendar implementation](https://github.com/GNOME/gtk/blob/gtk-3-24/gtk/gtkcalendar.c).
- The saved `interface_language` preference uses stable `zh_CN` / `en` codes. Startup reads the existing preference before creating GTK widgets. Missing or invalid preferences fall back to Simplified Chinese. No mail migration is required.
- Mail contents, contact names, account titles, custom view/folder names, classifier keywords and server folder identities are not translated. Built-in saved view names and application-generated explanations are localized only when displayed.
- Translations are bundled in `maildesk/locales/en.json`; no online translation service or additional Python package is used. Operating-system dialogs and provider error messages use their respective system/provider language.
- README screenshots show actual native windows with synthetic messages in an isolated profile. They contain no real mailbox data. The English and Chinese captures use matching layouts and datasets.

## Maintaining translations

`maildesk/i18n.py` provides explicit text markers, date formatting and the catalog lookup. Mark application-owned Python captions with `text` (conventionally imported as `_tr`); keep mailbox contents and matching keywords as ordinary strings. Marked text resolves at native encoding, interpolation or explicit `str()` conversion, while its canonical source value remains stable for equality, IDs and JSON persistence.

Use `join_text` for lists containing marked captions: Python's ordinary `str.join` copies the underlying canonical value of string subclasses. GtkBuilder localizes fixed presentation properties. Dynamically populated form/compose captions have `translatable="no"` because their explicit UI markers are already rendered and any remaining text belongs to the user. Entry values, widget IDs and model IDs are never translated.

Add the corresponding English value to the JSON catalog whenever adding a caption. Preserve format placeholders and XML/HTML escaping. Catalog tests check source coverage and placeholder contracts. The PDF adapter changes only TeleMail-owned viewer assets, leaving PDF bytes and vendored modules untouched.

## Verification

Local validation uses **CPython 3.14.4 on Linux** and **CPython 3.14.5 on Windows**, with the existing **GTK 3.24** runtime and **WebView2** for native Windows views. Runtime requirements remain those in [BUILDING.md](BUILDING.md); localization adds no dependency. The application targets Windows/Linux desktops, not a cluster job.

Run from the repository root:

```bash
PYTHONPATH=.:tests python3 -B -m unittest test_i18n
python3 -B tools/run_tests.py --output .runtime/localization-tests
python3 -B tools/verify_localization.py --language en --output .runtime/localization-en
python3 -B tools/verify_localization.py --language zh_CN --output .runtime/localization-zh
```

The native checks need the normal desktop GTK/browser dependencies and a graphical session. On Windows, run the same scripts with the packaged `runtime/python/python.exe`; the runner uses that runtime's GTK and font resources while loading the current source checkout. Tests isolate config/data/cache directories and reject real IMAP/SMTP access.

The native scenario visits the main window, mailbox navigation, message actions, every settings page, the composer and the scheduling dialog. It rejects unexpected Chinese text in English widgets, exercises saving the opposite language without changing the open session, and captures the real layouts for review. Unit tests additionally cover persistence, exact English dates, PDF assets and user-provided names that happen to match catalog keys.

The test-only `TELEMAIL_LANGUAGE=en` or `TELEMAIL_LANGUAGE=zh_CN` environment override selects a language before launch. Normal installations should use the saved Settings preference.

For 0.57.0, the source checkout passed **389 backend tests on each platform** (Linux: 6 platform skips; Windows: 5; zero failures/errors) and **22 native checks per language on Windows**. Both language runs made zero real provider calls. Local reports live in `.runtime/v0.57.0-linux-tests/`, `.runtime/v0.57.0-windows-tests/`, `.runtime/i18n-native-en/` and `.runtime/i18n-native-zh/`; these are not release artifacts. CI independently rebuilds and tests the tagged release packages.
