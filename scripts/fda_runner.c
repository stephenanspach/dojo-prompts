// fda_runner: stable launcher for launchd jobs that need Full Disk Access.
//
// macOS ties Full Disk Access to the exact binary path, and Homebrew's Python
// lives in a versioned Cellar folder that changes on every update. Grant FDA to
// this binary once instead: it spawns the given command as a child (not exec),
// so the child inherits this process's TCC responsibility.
//
// Build (keep the binary off iCloud):
//   clang -O2 -o ~/Library/Application\ Support/mattvsjapan/fda-runner fda_runner.c
//   codesign -f -s - -i com.mattvsjapan.fda-runner ~/Library/Application\ Support/mattvsjapan/fda-runner
// Usage in a launchd plist: ProgramArguments = [fda-runner, /opt/homebrew/bin/python3, script.py]
// Rebuilding changes the code hash, so FDA must be re-granted afterwards.

#include <spawn.h>
#include <stdio.h>
#include <string.h>
#include <sys/wait.h>

extern char **environ;

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "usage: fda-runner <program> [args...]\n");
        return 64;
    }
    pid_t pid;
    int rc = posix_spawn(&pid, argv[1], NULL, NULL, &argv[1], environ);
    if (rc != 0) {
        fprintf(stderr, "fda-runner: spawn %s: %s\n", argv[1], strerror(rc));
        return 127;
    }
    int status;
    while (waitpid(pid, &status, 0) < 0) {}
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    return 128 + WTERMSIG(status);
}
