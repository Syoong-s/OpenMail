# Private DOC reader

Antiword is a separate on-demand GPL-2.0-or-later executable, upstream copyright Adri van Os. Its complete unchanged corresponding source is source.tar.gz, pinned by SOURCE.json. LICENSE contains the full upstream license. The source archive includes its Makefiles, resource mappings, documentation and test document. No upstream code modifications are made.

Maildesk invokes plain UTF-8 text extraction with `-m UTF-8.txt -w 0`, a private resource directory, disposable input/output files and an eight-second child timeout. It does not invoke Word, scripts, macros, cloud conversion, or PostScript/PDF rendering.

Build environment: existing llvm-mingw20261006 UCRT amd64 compiler, GNU make; no global package installation. The project build calls tools/build_legacy_doc.py from tools/build_windows.py. Equivalent recipe inside the extracted source: `make -f Makefile.cygming -j4 CC=path/to/x86_64-w64-mingw32-gcc LD=path/to/x86_64-w64-mingw32-gcc 'CFLAGS=-O2 -D__CYGMING__ -DNDEBUG -Wno-implicit-function-declaration' LDFLAGS=-s`. The obsolete -mno-cygwin flag is replaced through command-line build variables; source/Makefiles remain unchanged.

Native application source includes this wrapper/build script; the portable Windows runtime includes antiword.exe, Resources, this notice, provenance and the full original source archive. Conversion is a read-only text preview and does not reproduce all original document formatting/embedded objects.
