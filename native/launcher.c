#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* ==========================================
 * Function: Launch the native Linux client from its installed or portable location.
 * Method: Resolve the ELF path and exec the system Python with an isolated module path.
 * ========================================== */
int main(int argc, char **argv) {
    char executable[PATH_MAX], directory[PATH_MAX], payload[PATH_MAX], probe[PATH_MAX];
    ssize_t length = readlink("/proc/self/exe", executable, sizeof(executable) - 1);
    if (length < 0 || (size_t)length >= sizeof(executable) - 1) {
        fprintf(stderr, "TeleMail: cannot resolve Linux executable path\n");
        return 1;
    }
    executable[length] = '\0';
    memcpy(directory, executable, (size_t)length + 1);
    char *slash = strrchr(directory, '/');
    if (!slash) return 1;
    *slash = '\0';
    int written = snprintf(payload, sizeof(payload), "%s/app", directory);
    if (written < 0 || (size_t)written >= sizeof(payload)) return 1;
    written = snprintf(probe, sizeof(probe), "%s/maildesk/desktop.py", payload);
    if (written < 0 || (size_t)written >= sizeof(probe) || access(probe, R_OK) != 0) {
        fprintf(stderr, "TeleMail: app payload is missing; keep the TeleMail file and app directory together\n");
        return 1;
    }
    if (setenv("TELEMAIL_LAUNCHER", executable, 1) != 0) return 1;
    const char *bootstrap =
        "import sys; "
        "sys.path.insert(0,sys.argv.pop(1)); "
        "from maildesk.desktop import main; "
        "raise SystemExit(main())";
    char **arguments = calloc((size_t)argc + 6, sizeof(char *));
    if (!arguments) return 1;
    arguments[0] = "/usr/bin/python3";
    arguments[1] = "-I";
    arguments[2] = "-c";
    arguments[3] = (char *)bootstrap;
    arguments[4] = payload;
    for (int i = 1; i < argc; i++) arguments[i + 4] = argv[i];
    arguments[argc + 4] = NULL;
    execv(arguments[0], arguments);
    fprintf(stderr, "TeleMail: cannot start Linux Python 3.12+: %s\n", strerror(errno));
    free(arguments);
    return 1;
}
