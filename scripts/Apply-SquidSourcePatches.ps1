[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$resolvedSourceRoot = [System.IO.Path]::GetFullPath($SourceRoot)
if (-not (Test-Path -LiteralPath $resolvedSourceRoot)) {
    throw "Squid source root was not found at $resolvedSourceRoot."
}

$patchResults = [System.Collections.Generic.List[PSCustomObject]]::new()

$crtdMessageHeaderPath = Join-Path $resolvedSourceRoot 'src\ssl\crtd_message.h'
if (-not (Test-Path -LiteralPath $crtdMessageHeaderPath)) {
    throw "Expected Squid source file was not found at $crtdMessageHeaderPath."
}

$crtdMessageHeader = Get-Content -Raw -LiteralPath $crtdMessageHeaderPath
$mingwErrorPatchMarker = '#if defined(_SQUID_MINGW_) && defined(ERROR)'
$crtdMessagePatched = $false

if (-not $crtdMessageHeader.Contains($mingwErrorPatchMarker)) {
    $newline = if ($crtdMessageHeader.Contains("`r`n")) { "`r`n" } else { "`n" }
    $parseResultPattern = [regex]'(?m)^(\s*/// Parse result codes\.\r?\n)(\s*enum ParseResult \{)'
    $updatedCrtdMessageHeader = $parseResultPattern.Replace(
        $crtdMessageHeader,
        {
            param($match)

            $match.Groups[1].Value +
            "#if defined(_SQUID_MINGW_) && defined(ERROR)$newline#undef ERROR$newline#endif$newline" +
            $match.Groups[2].Value
        },
        1
    )

    if ($updatedCrtdMessageHeader -eq $crtdMessageHeader) {
        throw "Failed to apply the MinGW ERROR macro workaround to $crtdMessageHeaderPath."
    }

    [System.IO.File]::WriteAllText(
        $crtdMessageHeaderPath,
        $updatedCrtdMessageHeader,
        [System.Text.UTF8Encoding]::new($false)
    )
    $crtdMessagePatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-crtd-message-error-macro'
    Path = $crtdMessageHeaderPath
    Applied = $crtdMessagePatched
})

$rfc1035SourcePath = Join-Path $resolvedSourceRoot 'src\dns\rfc1035.cc'
if (-not (Test-Path -LiteralPath $rfc1035SourcePath)) {
    throw "Expected Squid source file was not found at $rfc1035SourcePath."
}

$rfc1035Source = Get-Content -Raw -LiteralPath $rfc1035SourcePath
$rfc1035Patched = $false
$rfc1035Newline = if ($rfc1035Source.Contains("`r`n")) { "`r`n" } else { "`n" }

foreach ($assertPattern in @(
    'assert\(sz >= 12\);',
    'assert\(sz >= len \+ 1\);'
)) {
    if ($rfc1035Source -notmatch "\(void\)sz;\s+$assertPattern") {
        $updatedRfc1035Source = [regex]::Replace(
            $rfc1035Source,
            $assertPattern,
            "(void)sz;$rfc1035Newline    " + ($assertPattern -replace '\\', ''),
            1
        )

        if ($updatedRfc1035Source -eq $rfc1035Source) {
            throw "Failed to apply the MinGW unused-parameter workaround to $rfc1035SourcePath."
        }

        $rfc1035Source = $updatedRfc1035Source
        $rfc1035Patched = $true
    }
}

if ($rfc1035Patched) {
    [System.IO.File]::WriteAllText(
        $rfc1035SourcePath,
        $rfc1035Source,
        [System.Text.UTF8Encoding]::new($false)
    )
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-rfc1035-unused-parameter'
    Path = $rfc1035SourcePath
    Applied = $rfc1035Patched
})

$osdetectPath = Join-Path $resolvedSourceRoot 'compat\osdetect.h'
if (-not (Test-Path -LiteralPath $osdetectPath)) {
    throw "Expected Squid source file was not found at $osdetectPath."
}

$osdetectSource = Get-Content -Raw -LiteralPath $osdetectPath
$legacyOsdetectPatchMarker = '#define _SQUID_WINDOWS_ 1 /* squid4win-mingw-is-windows */'
$osdetectPatched = $false

if ($osdetectSource.Contains($legacyOsdetectPatchMarker)) {
    $updatedOsdetectSource = [regex]::Replace(
        $osdetectSource,
        '(?m)^#define _SQUID_WINDOWS_ 1 /\* squid4win-mingw-is-windows \*/\r?\n',
        '',
        1
    )

    if ($updatedOsdetectSource -eq $osdetectSource) {
        throw "Failed to remove the broad MinGW Windows OS-detection workaround from $osdetectPath."
    }

    [System.IO.File]::WriteAllText(
        $osdetectPath,
        $updatedOsdetectSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $osdetectPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-remove-broad-windows-define'
    Path = $osdetectPath
    Applied = $osdetectPatched
})

$mingwCompatPath = Join-Path $resolvedSourceRoot 'compat\os\mingw.h'
if (-not (Test-Path -LiteralPath $mingwCompatPath)) {
    throw "Expected Squid source file was not found at $mingwCompatPath."
}

$mingwCompatSource = Get-Content -Raw -LiteralPath $mingwCompatPath
$mingwPipePatchMarker = '#define pipe(a) Squid::pipe(a) /* squid4win-mingw-binary-pipe */'
$mingwCompatPatched = $false

if (-not $mingwCompatSource.Contains($mingwPipePatchMarker)) {
    $newline = if ($mingwCompatSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $mingwPipePatch = @'
#if HAVE_FCNTL_H
#include <fcntl.h>
#endif

#if defined(__cplusplus)
namespace Squid
{
inline int
pipe(int pipefd[2])
{
    return _pipe(pipefd,4096,_O_BINARY);
}
}
#define pipe(a) Squid::pipe(a) /* squid4win-mingw-binary-pipe */
#else
#define pipe(a) _pipe((a),4096,_O_BINARY) /* squid4win-mingw-binary-pipe */
#endif

'@ -replace "`r?`n", $newline

    $updatedMingwCompatSource = [regex]::Replace(
        $mingwCompatSource,
        '(?m)^#define mkdir\(p,F\) mkdir\(\(p\)\)$',
        $mingwPipePatch + '#define mkdir(p,F) mkdir((p))',
        1
    )

    if ($updatedMingwCompatSource -eq $mingwCompatSource) {
        throw "Failed to apply the MinGW binary pipe workaround to $mingwCompatPath."
    }

    [System.IO.File]::WriteAllText(
        $mingwCompatPath,
        $updatedMingwCompatSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $mingwCompatPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-binary-pipe-shim'
    Path = $mingwCompatPath
    Applied = $mingwCompatPatched
})

$mingwKillCompatSource = Get-Content -Raw -LiteralPath $mingwCompatPath
$mingwKillCompatMarker = 'kill(pid_t pid, int sig) /* squid4win-mingw-kill-compat */'
$mingwKillCompatPatched = $false
$mingwKillCompatPattern = [regex]'(?ms)^static inline int\r?\nkill\(pid_t pid, int sig\) /\* squid4win-mingw-kill-compat \*/\r?\n\{.*?^\}\r?\n(?:\r?\n)?'

if ($mingwKillCompatPattern.Matches($mingwKillCompatSource).Count -ne 1) {
    $newline = if ($mingwKillCompatSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $mingwKillCompatPatch = @'
static inline int
kill(pid_t pid, int sig) /* squid4win-mingw-kill-compat */
{
    if (sig == 0) {
        HANDLE hProcess = OpenProcess(PROCESS_QUERY_INFORMATION, FALSE, pid);
        if (!hProcess)
            return -1;
        CloseHandle(hProcess);
    }
    return 0;
}

'@ -replace "`r?`n", $newline

    if ($mingwKillCompatSource.Contains($mingwKillCompatMarker)) {
        $mingwKillCompatSource = $mingwKillCompatPattern.Replace($mingwKillCompatSource, '')
    }

    $updatedMingwKillCompatSource = [regex]::Replace(
        $mingwKillCompatSource,
        '(?m)^#if !HAVE_FSYNC\r?\n',
        $mingwKillCompatPatch + '#if !HAVE_FSYNC' + $newline,
        1
    )

    if ($updatedMingwKillCompatSource -eq $mingwKillCompatSource) {
        throw "Failed to apply the MinGW kill compatibility shim to $mingwCompatPath."
    }

    [System.IO.File]::WriteAllText(
        $mingwCompatPath,
        $updatedMingwKillCompatSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $mingwKillCompatPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-kill-compat'
    Path = $mingwCompatPath
    Applied = $mingwKillCompatPatched
})

$mingwStdioCompatSource = Get-Content -Raw -LiteralPath $mingwCompatPath
$mingwStdioCompatMarker = '#include <stdarg.h> /* squid4win-mingw-syslog-compat */'
$mingwStdioCompatPatched = $false

if (-not $mingwStdioCompatSource.Contains($mingwStdioCompatMarker)) {
    $newline = if ($mingwStdioCompatSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $mingwStdioCompatPatch = @'
#if HAVE_STDARG_H
#include <stdarg.h> /* squid4win-mingw-syslog-compat */
#endif

#if HAVE_STDIO_H
#include <stdio.h> /* squid4win-mingw-syslog-compat */
#endif

'@ -replace "`r?`n", $newline

    $updatedMingwStdioCompatSource = [regex]::Replace(
        $mingwStdioCompatSource,
        '(?ms)#if HAVE_IO_H\r?\n#include <io\.h>\r?\n#endif\r?\n',
        '$0' + $mingwStdioCompatPatch,
        1
    )

    if ($updatedMingwStdioCompatSource -eq $mingwStdioCompatSource) {
        throw "Failed to add MinGW stdio/stdarg includes to $mingwCompatPath."
    }

    [System.IO.File]::WriteAllText(
        $mingwCompatPath,
        $updatedMingwStdioCompatSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $mingwStdioCompatPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-syslog-includes'
    Path = $mingwCompatPath
    Applied = $mingwStdioCompatPatched
})

$mingwSignalCompatSource = Get-Content -Raw -LiteralPath $mingwCompatPath
$mingwSignalCompatMarker = '#include <signal.h> /* squid4win-mingw-signal-compat */'
$mingwSignalCompatPatched = $false

if (-not $mingwSignalCompatSource.Contains($mingwSignalCompatMarker)) {
    $newline = if ($mingwSignalCompatSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $mingwSignalCompatPatch = @'
#if HAVE_SIGNAL_H
#include <signal.h> /* squid4win-mingw-signal-compat */
#endif

'@ -replace "`r?`n", $newline

    $updatedMingwSignalCompatSource = [regex]::Replace(
        $mingwSignalCompatSource,
        '(?ms)#if HAVE_STDIO_H\r?\n#include <stdio\.h> /\* squid4win-mingw-syslog-compat \*/\r?\n#endif\r?\n',
        '$0' + $mingwSignalCompatPatch,
        1
    )

    if ($updatedMingwSignalCompatSource -eq $mingwSignalCompatSource) {
        throw "Failed to add the MinGW signal include to $mingwCompatPath."
    }

    [System.IO.File]::WriteAllText(
        $mingwCompatPath,
        $updatedMingwSignalCompatSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $mingwSignalCompatPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-signal-includes'
    Path = $mingwCompatPath
    Applied = $mingwSignalCompatPatched
})

$mingwSignalConstantsSource = Get-Content -Raw -LiteralPath $mingwCompatPath
$mingwSignalConstantsMarker = '#define SIGUSR1 30 /* squid4win-mingw-signal-compat */'
$mingwSignalConstantsPatched = $false

if (-not $mingwSignalConstantsSource.Contains($mingwSignalConstantsMarker)) {
    $newline = if ($mingwSignalConstantsSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $mingwSignalConstantsPatch = @'
#ifndef SIGHUP
#define SIGHUP 1 /* squid4win-mingw-signal-compat */
#endif
#ifndef SIGKILL
#define SIGKILL 9 /* squid4win-mingw-signal-compat */
#endif
#ifndef SIGBUS
#define SIGBUS 10 /* squid4win-mingw-signal-compat */
#endif
#ifndef SIGPIPE
#define SIGPIPE 13 /* squid4win-mingw-signal-compat */
#endif
#ifndef SIGCHLD
#define SIGCHLD 20 /* squid4win-mingw-signal-compat */
#endif
#ifndef SIGUSR1
#define SIGUSR1 30 /* squid4win-mingw-signal-compat */
#endif
#ifndef SIGUSR2
#define SIGUSR2 31 /* squid4win-mingw-signal-compat */
#endif

'@ -replace "`r?`n", $newline

    $updatedMingwSignalConstantsSource = ([regex]'(?ms)#if HAVE_SIGNAL_H\r?\n#include <signal\.h> /\* squid4win-mingw-signal-compat \*/\r?\n#endif\r?\n').Replace(
        $mingwSignalConstantsSource,
        '$0' + $mingwSignalConstantsPatch,
        1
    )

    if ($updatedMingwSignalConstantsSource -eq $mingwSignalConstantsSource) {
        throw "Failed to add MinGW signal constants to $mingwCompatPath."
    }

    [System.IO.File]::WriteAllText(
        $mingwCompatPath,
        $updatedMingwSignalConstantsSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $mingwSignalConstantsPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-signal-constants'
    Path = $mingwCompatPath
    Applied = $mingwSignalConstantsPatched
})

$mingwDevNullCompatSource = Get-Content -Raw -LiteralPath $mingwCompatPath
$mingwDevNullCompatMarker = '#define _PATH_DEVNULL "NUL" /* squid4win-mingw-devnull */'
$mingwDevNullCompatPatched = $false

if (-not $mingwDevNullCompatSource.Contains($mingwDevNullCompatMarker)) {
    $newline = if ($mingwDevNullCompatSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $mingwDevNullCompatPatch = @'
#ifndef _PATH_DEVNULL
#define _PATH_DEVNULL "NUL" /* squid4win-mingw-devnull */
#endif

'@ -replace "`r?`n", $newline

    $updatedMingwDevNullCompatSource = ([regex]'(?m)^static inline int\r?\nkill\(pid_t pid, int sig\) /\* squid4win-mingw-kill-compat \*/\r?\n').Replace(
        $mingwDevNullCompatSource,
        $mingwDevNullCompatPatch + 'static inline int' + $newline + 'kill(pid_t pid, int sig) /* squid4win-mingw-kill-compat */' + $newline,
        1
    )

    if ($updatedMingwDevNullCompatSource -eq $mingwDevNullCompatSource) {
        throw "Failed to add the MinGW _PATH_DEVNULL fallback to $mingwCompatPath."
    }

    [System.IO.File]::WriteAllText(
        $mingwCompatPath,
        $updatedMingwDevNullCompatSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $mingwDevNullCompatPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-devnull-fallback'
    Path = $mingwCompatPath
    Applied = $mingwDevNullCompatPatched
})

$mingwUserCompatSource = Get-Content -Raw -LiteralPath $mingwCompatPath
$mingwUserCompatMarker = 'getpwnam(const char *unused) /* squid4win-mingw-user-compat */'
$mingwUserCompatPatched = $false

if (-not $mingwUserCompatSource.Contains($mingwUserCompatMarker)) {
    $newline = if ($mingwUserCompatSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $mingwUserCompatPatch = @'
#if !HAVE_PWD_H
struct passwd {
    char *pw_name;
    char *pw_passwd;
    uid_t pw_uid;
    gid_t pw_gid;
    char *pw_gecos;
    char *pw_dir;
    char *pw_shell;
};
#endif

#if !HAVE_GRP_H
struct group {
    char *gr_name;
    char *gr_passwd;
    gid_t gr_gid;
    char **gr_mem;
};
#endif

#if !HAVE_PWD_H
static inline struct passwd *
getpwnam(const char *unused) /* squid4win-mingw-user-compat */
{
    static struct passwd pwd = {0, 0, 100, 100, 0, 0, 0};
    (void)unused;
    return &pwd;
}
#endif

#if !HAVE_GRP_H
static inline struct group *
getgrnam(const char *unused) /* squid4win-mingw-user-compat */
{
    static struct group grp = {0, 0, 100, 0};
    (void)unused;
    return &grp;
}
#endif

#if !HAVE_SETEUID
static inline uid_t
geteuid(void) /* squid4win-mingw-user-compat */
{
    return 100;
}
static inline int
seteuid(uid_t euid) /* squid4win-mingw-user-compat */
{
    (void)euid;
    return 0;
}
#endif

#if !HAVE_SETUID
static inline uid_t
getuid(void) /* squid4win-mingw-user-compat */
{
    return 100;
}
static inline int
setuid(uid_t uid) /* squid4win-mingw-user-compat */
{
    (void)uid;
    return 0;
}
#endif

#if !HAVE_SETEGID
static inline gid_t
getegid(void) /* squid4win-mingw-user-compat */
{
    return 100;
}
static inline int
setegid(gid_t egid) /* squid4win-mingw-user-compat */
{
    (void)egid;
    return 0;
}
#endif

#if !HAVE_SETGID
static inline gid_t
getgid(void) /* squid4win-mingw-user-compat */
{
    return 100;
}
static inline int
setgid(gid_t gid) /* squid4win-mingw-user-compat */
{
    (void)gid;
    return 0;
}
#endif

'@ -replace "`r?`n", $newline

    $updatedMingwUserCompatSource = ([regex]'(?m)^static inline int\r?\nkill\(pid_t pid, int sig\) /\* squid4win-mingw-kill-compat \*/\r?\n').Replace(
        $mingwUserCompatSource,
        $mingwUserCompatPatch + 'static inline int' + $newline + 'kill(pid_t pid, int sig) /* squid4win-mingw-kill-compat */' + $newline,
        1
    )

    if ($updatedMingwUserCompatSource -eq $mingwUserCompatSource) {
        throw "Failed to add the MinGW user/group compatibility shims to $mingwCompatPath."
    }

    [System.IO.File]::WriteAllText(
        $mingwCompatPath,
        $updatedMingwUserCompatSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $mingwUserCompatPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-user-group-compat'
    Path = $mingwCompatPath
    Applied = $mingwUserCompatPatched
})

$mingwLegacyInitgroupsSource = Get-Content -Raw -LiteralPath $mingwCompatPath
$mingwLegacyInitgroupsMarker = 'initgroups(const char *user, gid_t group) /* squid4win-mingw-user-compat */'
$mingwLegacyInitgroupsPatched = $false

if ($mingwLegacyInitgroupsSource.Contains($mingwLegacyInitgroupsMarker)) {
    $updatedMingwLegacyInitgroupsSource = [regex]::Replace(
        $mingwLegacyInitgroupsSource,
        '(?ms)^#if !HAVE_INITGROUPS\r?\nstatic inline int\r?\ninitgroups\(const char \*user, gid_t group\) /\* squid4win-mingw-user-compat \*/\r?\n\{\r?\n\s*\(void\)user;\r?\n\s*\(void\)group;\r?\n\s*return 0;\r?\n\}\r?\n#endif\r?\n?',
        '',
        1
    )

    if ($updatedMingwLegacyInitgroupsSource -eq $mingwLegacyInitgroupsSource) {
        throw "Failed to remove the legacy MinGW initgroups compatibility shim from $mingwCompatPath."
    }

    [System.IO.File]::WriteAllText(
        $mingwCompatPath,
        $updatedMingwLegacyInitgroupsSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $mingwLegacyInitgroupsPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-remove-inline-initgroups-compat'
    Path = $mingwCompatPath
    Applied = $mingwLegacyInitgroupsPatched
})

$mingwGetPageSizeSource = Get-Content -Raw -LiteralPath $mingwCompatPath
$mingwGetPageSizeMarker = 'getpagesize(void) /* squid4win-mingw-getpagesize */'
$mingwGetPageSizePatched = $false

if (-not $mingwGetPageSizeSource.Contains($mingwGetPageSizeMarker)) {
    $newline = if ($mingwGetPageSizeSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $mingwGetPageSizePatch = @'
static inline size_t
getpagesize(void) /* squid4win-mingw-getpagesize */
{
    SYSTEM_INFO systemInfo;
    GetSystemInfo(&systemInfo);
    return systemInfo.dwPageSize;
}

'@ -replace "`r?`n", $newline

    $updatedMingwGetPageSizeSource = ([regex]'(?m)^static inline int\r?\nkill\(pid_t pid, int sig\) /\* squid4win-mingw-kill-compat \*/\r?\n').Replace(
        $mingwGetPageSizeSource,
        $mingwGetPageSizePatch + 'static inline int' + $newline + 'kill(pid_t pid, int sig) /* squid4win-mingw-kill-compat */' + $newline,
        1
    )

    if ($updatedMingwGetPageSizeSource -eq $mingwGetPageSizeSource) {
        throw "Failed to add the MinGW getpagesize compatibility shim to $mingwCompatPath."
    }

    [System.IO.File]::WriteAllText(
        $mingwCompatPath,
        $updatedMingwGetPageSizeSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $mingwGetPageSizePatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-getpagesize-compat'
    Path = $mingwCompatPath
    Applied = $mingwGetPageSizePatched
})

$mingwFcntlSource = Get-Content -Raw -LiteralPath $mingwCompatPath
$mingwFcntlMarker = 'fcntl(int fd, int cmd, ...) /* squid4win-mingw-fcntl */'
$mingwFcntlPatched = $false

if (-not $mingwFcntlSource.Contains($mingwFcntlMarker)) {
    $newline = if ($mingwFcntlSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $mingwFcntlPatch = @'
#ifndef O_NONBLOCK
#define O_NONBLOCK 0x0004 /* squid4win-mingw-fcntl */
#endif
#ifndef O_NDELAY
#define O_NDELAY O_NONBLOCK /* squid4win-mingw-fcntl */
#endif
#ifndef FD_CLOEXEC
#define FD_CLOEXEC 0x0001 /* squid4win-mingw-fcntl */
#endif
#ifndef F_GETFD
#define F_GETFD 1 /* squid4win-mingw-fcntl */
#endif
#ifndef F_SETFD
#define F_SETFD 2 /* squid4win-mingw-fcntl */
#endif
#ifndef F_GETFL
#define F_GETFL 3 /* squid4win-mingw-fcntl */
#endif
#ifndef F_SETFL
#define F_SETFL 4 /* squid4win-mingw-fcntl */
#endif

static inline int
fcntl(int fd, int cmd, ...) /* squid4win-mingw-fcntl */
{
    va_list args;
    int flags = 0;

    va_start(args, cmd);
    if (cmd == F_SETFL || cmd == F_SETFD)
        flags = va_arg(args, int);
    else if (cmd != F_GETFL && cmd != F_GETFD)
        (void)va_arg(args, void *);
    va_end(args);

    switch (cmd) {
    case F_GETFD:
    case F_GETFL:
        return 0;

    case F_SETFD:
        return 0;

    case F_SETFL: {
        u_long nonblocking = (flags & (O_NONBLOCK | O_NDELAY)) ? 1UL : 0UL;
        if (ioctlsocket(fd, FIONBIO, &nonblocking) == 0)
            return 0;
        if (WSAGetLastError() == WSAENOTSOCK)
            return 0;
        errno = EINVAL;
        return -1;
    }

    default:
        errno = EINVAL;
        return -1;
    }
}

'@ -replace "`r?`n", $newline

    $updatedMingwFcntlSource = ([regex]'(?m)^static inline int\r?\nkill\(pid_t pid, int sig\) /\* squid4win-mingw-kill-compat \*/\r?\n').Replace(
        $mingwFcntlSource,
        $mingwFcntlPatch + 'static inline int' + $newline + 'kill(pid_t pid, int sig) /* squid4win-mingw-kill-compat */' + $newline,
        1
    )

    if ($updatedMingwFcntlSource -eq $mingwFcntlSource) {
        throw "Failed to add the MinGW fcntl compatibility shim to $mingwCompatPath."
    }

    [System.IO.File]::WriteAllText(
        $mingwCompatPath,
        $updatedMingwFcntlSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $mingwFcntlPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-fcntl-compat'
    Path = $mingwCompatPath
    Applied = $mingwFcntlPatched
})

$mingwSyslogCompatSource = Get-Content -Raw -LiteralPath $mingwCompatPath
$mingwSyslogCompatMarker = 'syslog(int priority, const char *fmt, ...) /* squid4win-mingw-syslog-compat */'
$mingwSyslogCompatPatched = $false

if (-not $mingwSyslogCompatSource.Contains($mingwSyslogCompatMarker)) {
    $newline = if ($mingwSyslogCompatSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $mingwSyslogCompatPatch = @'
#if !HAVE_SYSLOG
#ifndef LOG_PID
#define LOG_PID     0x01
#endif
#ifndef LOG_CONS
#define LOG_CONS    0x02
#endif
#ifndef LOG_NDELAY
#define LOG_NDELAY  0x08
#endif
#ifndef LOG_EMERG
#define LOG_EMERG   0
#endif
#ifndef LOG_ALERT
#define LOG_ALERT   1
#endif
#ifndef LOG_CRIT
#define LOG_CRIT    2
#endif
#ifndef LOG_ERR
#define LOG_ERR     3
#endif
#ifndef LOG_WARNING
#define LOG_WARNING 4
#endif
#ifndef LOG_NOTICE
#define LOG_NOTICE  5
#endif
#ifndef LOG_INFO
#define LOG_INFO    6
#endif
#ifndef LOG_DEBUG
#define LOG_DEBUG   7
#endif
#ifndef LOG_KERN
#define LOG_KERN    (0<<3)
#endif
#ifndef LOG_USER
#define LOG_USER    (1<<3)
#endif
#ifndef LOG_MAIL
#define LOG_MAIL    (2<<3)
#endif
#ifndef LOG_DAEMON
#define LOG_DAEMON  (3<<3)
#endif
#ifndef LOG_AUTH
#define LOG_AUTH    (4<<3)
#endif
#ifndef LOG_SYSLOG
#define LOG_SYSLOG  (5<<3)
#endif
#ifndef LOG_LPR
#define LOG_LPR     (6<<3)
#endif
#ifndef LOG_NEWS
#define LOG_NEWS    (7<<3)
#endif
#ifndef LOG_UUCP
#define LOG_UUCP    (8<<3)
#endif
#ifndef LOG_CRON
#define LOG_CRON    (9<<3)
#endif
#ifndef LOG_AUTHPRIV
#define LOG_AUTHPRIV (10<<3)
#endif
#ifndef LOG_LOCAL0
#define LOG_LOCAL0  (16<<3)
#endif
#ifndef LOG_LOCAL1
#define LOG_LOCAL1  (17<<3)
#endif
#ifndef LOG_LOCAL2
#define LOG_LOCAL2  (18<<3)
#endif
#ifndef LOG_LOCAL3
#define LOG_LOCAL3  (19<<3)
#endif
#ifndef LOG_LOCAL4
#define LOG_LOCAL4  (20<<3)
#endif
#ifndef LOG_LOCAL5
#define LOG_LOCAL5  (21<<3)
#endif
#ifndef LOG_LOCAL6
#define LOG_LOCAL6  (22<<3)
#endif
#ifndef LOG_LOCAL7
#define LOG_LOCAL7  (23<<3)
#endif

static inline void
openlog(const char *ident, int logopt, int facility) /* squid4win-mingw-syslog-compat */
{
    (void)ident;
    (void)logopt;
    (void)facility;
}

static inline void
closelog(void) /* squid4win-mingw-syslog-compat */
{
}

static inline void
syslog(int priority, const char *fmt, ...) /* squid4win-mingw-syslog-compat */
{
    va_list args;
    (void)priority;
    va_start(args, fmt);
    vfprintf(stderr, fmt, args);
    fputc('\n', stderr);
    fflush(stderr);
    va_end(args);
}
#endif

#ifndef WIFEXITED
#define WIFEXITED(status) ((status) >= 0) /* squid4win-mingw-wait-status */
#endif
#ifndef WEXITSTATUS
#define WEXITSTATUS(status) (status) /* squid4win-mingw-wait-status */
#endif
#ifndef WIFSIGNALED
#define WIFSIGNALED(status) (0) /* squid4win-mingw-wait-status */
#endif
#ifndef WTERMSIG
#define WTERMSIG(status) (0) /* squid4win-mingw-wait-status */
#endif

'@ -replace "`r?`n", $newline

    $updatedMingwSyslogCompatSource = [regex]::Replace(
        $mingwSyslogCompatSource,
        '(?m)^#if !HAVE_FSYNC\r?\n',
        $mingwSyslogCompatPatch + '#if !HAVE_FSYNC' + $newline,
        1
    )

    if ($updatedMingwSyslogCompatSource -eq $mingwSyslogCompatSource) {
        throw "Failed to apply the MinGW syslog and wait-status compatibility shims to $mingwCompatPath."
    }

    [System.IO.File]::WriteAllText(
        $mingwCompatPath,
        $updatedMingwSyslogCompatSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $mingwSyslogCompatPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-syslog-wait-compat'
    Path = $mingwCompatPath
    Applied = $mingwSyslogCompatPatched
})

$win32HeaderPath = Join-Path $resolvedSourceRoot 'src\win32.h'
if (-not (Test-Path -LiteralPath $win32HeaderPath)) {
    throw "Expected Squid source file was not found at $win32HeaderPath."
}

$win32HeaderSource = Get-Content -Raw -LiteralPath $win32HeaderPath
$win32MapErrorMarker = 'void WIN32_maperror(unsigned long WIN32_oserrno); /* squid4win-mingw-win32-maperror */'
$win32HeaderPatched = $false
$newline = if ($win32HeaderSource.Contains("`r`n")) { "`r`n" } else { "`n" }

if (-not $win32HeaderSource.Contains($win32MapErrorMarker)) {
    $win32MapErrorDeclaration = @'
#if _SQUID_WINDOWS_ || _SQUID_MINGW_
void WIN32_maperror(unsigned long WIN32_oserrno); /* squid4win-mingw-win32-maperror */
#endif

'@ -replace "`r?`n", $newline

    $updatedWin32HeaderSource = [regex]::Replace(
        $win32HeaderSource,
        '(?m)^#if _SQUID_WINDOWS_\r?\n',
        $win32MapErrorDeclaration + '#if _SQUID_WINDOWS_' + $newline,
        1
    )

    if ($updatedWin32HeaderSource -eq $win32HeaderSource) {
        throw "Failed to expose WIN32_maperror for MinGW in $win32HeaderPath."
    }

    [System.IO.File]::WriteAllText(
        $win32HeaderPath,
        $updatedWin32HeaderSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $win32HeaderPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-win32-maperror-declaration'
    Path = $win32HeaderPath
    Applied = $win32HeaderPatched
})

$win32DeclarationsMarker = '#if _SQUID_WINDOWS_ || _SQUID_MINGW_ /* squid4win-mingw-win32-declarations */'
$win32DeclarationsPatched = $false

if (-not $win32HeaderSource.Contains($win32DeclarationsMarker)) {
    $win32HeaderSource = Get-Content -Raw -LiteralPath $win32HeaderPath
    $updatedWin32HeaderDeclarations = [regex]::Replace(
        $win32HeaderSource,
        '(?m)^#if _SQUID_WINDOWS_\r?\n',
        $win32DeclarationsMarker + $newline,
        1
    )

    if ($updatedWin32HeaderDeclarations -eq $win32HeaderSource) {
        throw "Failed to expose the Win32 helper declarations for MinGW in $win32HeaderPath."
    }

    [System.IO.File]::WriteAllText(
        $win32HeaderPath,
        $updatedWin32HeaderDeclarations,
        [System.Text.UTF8Encoding]::new($false)
    )
    $win32DeclarationsPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-win32-declarations'
    Path = $win32HeaderPath
    Applied = $win32DeclarationsPatched
})

$win32FdSetMarker = '#if _SQUID_WINDOWS_ /* squid4win-mingw-win32-wsafd */'
$win32FdSetPatched = $false

if (-not $win32HeaderSource.Contains($win32FdSetMarker)) {
    $win32HeaderSource = Get-Content -Raw -LiteralPath $win32HeaderPath
    $updatedWin32FdSetHeader = $win32HeaderSource.Replace(
        'int Win32__WSAFDIsSet(int fd, fd_set* set);',
        $win32FdSetMarker + $newline +
        'int Win32__WSAFDIsSet(int fd, fd_set* set);' + $newline +
        '#endif'
    )

    if ($updatedWin32FdSetHeader -eq $win32HeaderSource) {
        throw "Failed to keep Win32-specific fd_set helpers Windows-only in $win32HeaderPath."
    }

    [System.IO.File]::WriteAllText(
        $win32HeaderPath,
        $updatedWin32FdSetHeader,
        [System.Text.UTF8Encoding]::new($false)
    )
    $win32FdSetPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-win32-wsafd-header'
    Path = $win32HeaderPath
    Applied = $win32FdSetPatched
})

$win32SourcePath = Join-Path $resolvedSourceRoot 'src\win32.cc'
if (-not (Test-Path -LiteralPath $win32SourcePath)) {
    throw "Expected Squid source file was not found at $win32SourcePath."
}

$win32Source = Get-Content -Raw -LiteralPath $win32SourcePath
$win32SourceMarker = '#if _SQUID_WINDOWS_ || _SQUID_MINGW_ /* squid4win-mingw-win32-impl */'
$win32SourcePatched = $false

if (-not $win32Source.Contains($win32SourceMarker)) {
    $newline = if ($win32Source.Contains("`r`n")) { "`r`n" } else { "`n" }
    $updatedWin32Source = [regex]::Replace(
        $win32Source,
        '(?m)^#if _SQUID_WINDOWS_\r?\n',
        $win32SourceMarker + $newline,
        1
    )

    if ($updatedWin32Source -eq $win32Source) {
        throw "Failed to expose the Win32 helper implementations for MinGW in $win32SourcePath."
    }

    [System.IO.File]::WriteAllText(
        $win32SourcePath,
        $updatedWin32Source,
        [System.Text.UTF8Encoding]::new($false)
    )
    $win32SourcePatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-win32-impl'
    Path = $win32SourcePath
    Applied = $win32SourcePatched
})

$win32WsafdSourceMarker = '#if _SQUID_WINDOWS_ /* squid4win-mingw-win32-wsafd */'
$win32WsafdSourcePatched = $false

if (-not $win32Source.Contains($win32WsafdSourceMarker)) {
    $win32Source = Get-Content -Raw -LiteralPath $win32SourcePath
    $win32WsafdBlock = @'
int
Win32__WSAFDIsSet(int fd, fd_set FAR * set)
{
    fde *F = &fd_table[fd];
    SOCKET s = F->win32.handle;

    return __WSAFDIsSet(s, set);
}
'@ -replace "`r?`n", $newline

    $updatedWin32WsafdSource = $win32Source.Replace(
        $win32WsafdBlock,
        $win32WsafdSourceMarker + $newline +
        $win32WsafdBlock +
        $newline +
        '#endif' + $newline
    )

    if ($updatedWin32WsafdSource -eq $win32Source) {
        throw "Failed to keep Win32-specific WSAFD helpers Windows-only in $win32SourcePath."
    }

    [System.IO.File]::WriteAllText(
        $win32SourcePath,
        $updatedWin32WsafdSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $win32WsafdSourcePatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-win32-wsafd-impl'
    Path = $win32SourcePath
    Applied = $win32WsafdSourcePatched
})

$win32SourceFormattingPatched = $false
$win32Source = Get-Content -Raw -LiteralPath $win32SourcePath
if ($win32Source.Contains('}#endif')) {
    $updatedWin32Formatting = $win32Source.Replace('}#endif', '}' + $newline + '#endif')

    [System.IO.File]::WriteAllText(
        $win32SourcePath,
        $updatedWin32Formatting,
        [System.Text.UTF8Encoding]::new($false)
    )
    $win32SourceFormattingPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-win32-wsafd-format'
    Path = $win32SourcePath
    Applied = $win32SourceFormattingPatched
})

$win32MingwSupportPatched = $false
$win32Source = Get-Content -Raw -LiteralPath $win32SourcePath
$newline = if ($win32Source.Contains("`r`n")) { "`r`n" } else { "`n" }
$win32MapErrorImplPattern = [regex]'(?ms)^#if _SQUID_MINGW_\r?\nLPCRITICAL_SECTION dbg_mutex = nullptr; /\* squid4win-mingw-dbg-mutex \*/\r?\n\r?\nvoid\r?\nWIN32_maperror\(unsigned long WIN32_oserrno\) /\* squid4win-mingw-win32-maperror-impl \*/\r?\n\{.*?^\}\r?\n#endif\r?\n(?:\r?\n)?'
$win32MapErrorImpl = @'
#if _SQUID_MINGW_
LPCRITICAL_SECTION dbg_mutex = nullptr; /* squid4win-mingw-dbg-mutex */

void
WIN32_maperror(unsigned long WIN32_oserrno) /* squid4win-mingw-win32-maperror-impl */
{
    static const struct {
        unsigned long win32Code;
        int posixErrno;
    } errorTable[] = {
        {ERROR_INVALID_FUNCTION, EINVAL},
        {ERROR_FILE_NOT_FOUND, ENOENT},
        {ERROR_PATH_NOT_FOUND, ENOENT},
        {ERROR_TOO_MANY_OPEN_FILES, EMFILE},
        {ERROR_ACCESS_DENIED, EACCES},
        {ERROR_INVALID_HANDLE, EBADF},
        {ERROR_ARENA_TRASHED, ENOMEM},
        {ERROR_NOT_ENOUGH_MEMORY, ENOMEM},
        {ERROR_INVALID_BLOCK, ENOMEM},
        {ERROR_BAD_ENVIRONMENT, E2BIG},
        {ERROR_BAD_FORMAT, ENOEXEC},
        {ERROR_INVALID_ACCESS, EINVAL},
        {ERROR_INVALID_DATA, EINVAL},
        {ERROR_INVALID_DRIVE, ENOENT},
        {ERROR_CURRENT_DIRECTORY, EACCES},
        {ERROR_NOT_SAME_DEVICE, EXDEV},
        {ERROR_NO_MORE_FILES, ENOENT},
        {ERROR_LOCK_VIOLATION, EACCES},
        {ERROR_BAD_NETPATH, ENOENT},
        {ERROR_NETWORK_ACCESS_DENIED, EACCES},
        {ERROR_BAD_NET_NAME, ENOENT},
        {ERROR_FILE_EXISTS, EEXIST},
        {ERROR_CANNOT_MAKE, EACCES},
        {ERROR_FAIL_I24, EACCES},
        {ERROR_INVALID_PARAMETER, EINVAL},
        {ERROR_NO_PROC_SLOTS, EAGAIN},
        {ERROR_DRIVE_LOCKED, EACCES},
        {ERROR_BROKEN_PIPE, EPIPE},
        {ERROR_DISK_FULL, ENOSPC},
        {ERROR_INVALID_TARGET_HANDLE, EBADF},
        {ERROR_WAIT_NO_CHILDREN, ECHILD},
        {ERROR_CHILD_NOT_COMPLETE, ECHILD},
        {ERROR_DIRECT_ACCESS_HANDLE, EBADF},
        {ERROR_NEGATIVE_SEEK, EINVAL},
        {ERROR_SEEK_ON_DEVICE, EACCES},
        {ERROR_DIR_NOT_EMPTY, ENOTEMPTY},
        {ERROR_NOT_LOCKED, EACCES},
        {ERROR_BAD_PATHNAME, ENOENT},
        {ERROR_MAX_THRDS_REACHED, EAGAIN},
        {ERROR_LOCK_FAILED, EACCES},
        {ERROR_ALREADY_EXISTS, EEXIST},
        {ERROR_FILENAME_EXCED_RANGE, ENOENT},
        {ERROR_NESTING_NOT_ALLOWED, EAGAIN},
        {ERROR_NOT_ENOUGH_QUOTA, ENOMEM},
        {WSAEINTR, EINTR},
        {WSAEBADF, EBADF},
        {WSAEACCES, EACCES},
        {WSAEFAULT, EFAULT},
        {WSAEINVAL, EINVAL},
        {WSAEMFILE, EMFILE},
        {WSAEWOULDBLOCK, EWOULDBLOCK},
        {WSAEINPROGRESS, EINPROGRESS},
        {WSAEALREADY, EALREADY},
        {WSAENOTSOCK, ENOTSOCK},
        {WSAEDESTADDRREQ, EDESTADDRREQ},
        {WSAEMSGSIZE, EMSGSIZE},
        {WSAEPROTOTYPE, EPROTOTYPE},
        {WSAENOPROTOOPT, ENOPROTOOPT},
        {WSAEPROTONOSUPPORT, EPROTONOSUPPORT},
        {WSAEOPNOTSUPP, EOPNOTSUPP},
        {WSAEAFNOSUPPORT, EAFNOSUPPORT},
        {WSAEADDRINUSE, EADDRINUSE},
        {WSAEADDRNOTAVAIL, EADDRNOTAVAIL},
        {WSAENETDOWN, ENETDOWN},
        {WSAENETUNREACH, ENETUNREACH},
        {WSAENETRESET, ENETRESET},
        {WSAECONNABORTED, ECONNABORTED},
        {WSAECONNRESET, ECONNRESET},
        {WSAENOBUFS, ENOBUFS},
        {WSAEISCONN, EISCONN},
        {WSAENOTCONN, ENOTCONN},
        {WSAETIMEDOUT, ETIMEDOUT},
        {WSAECONNREFUSED, ECONNREFUSED},
        {WSAEHOSTUNREACH, EHOSTUNREACH}
    };

    for (const auto &entry : errorTable) {
        if (WIN32_oserrno == entry.win32Code) {
            errno = entry.posixErrno;
            return;
        }
    }

    if (WIN32_oserrno >= ERROR_WRITE_PROTECT && WIN32_oserrno <= ERROR_SHARING_BUFFER_EXCEEDED)
        errno = EACCES;
    else if (WIN32_oserrno >= ERROR_INVALID_STARTING_CODESEG && WIN32_oserrno <= ERROR_INFLOOP_IN_RELOC_CHAIN)
        errno = ENOEXEC;
    else
        errno = EINVAL;
}
#endif

'@ -replace "`r?`n", $newline

$existingWin32MapErrorMatches = $win32MapErrorImplPattern.Matches($win32Source)
if ($existingWin32MapErrorMatches.Count -ne 1) {
    if ($existingWin32MapErrorMatches.Count -gt 0) {
        $win32Source = $win32MapErrorImplPattern.Replace($win32Source, '')
    }

    $updatedWin32Source = ([regex]'(?m)^static LPTOP_LEVEL_EXCEPTION_FILTER Win32_Old_ExceptionHandler = nullptr;\r?\n').Replace(
        $win32Source,
        'static LPTOP_LEVEL_EXCEPTION_FILTER Win32_Old_ExceptionHandler = nullptr;' + $newline + $newline + $win32MapErrorImpl,
        1
    )

    if ($updatedWin32Source -eq $win32Source) {
        throw "Failed to add the MinGW Win32 error mapper to $win32SourcePath."
    }

    [System.IO.File]::WriteAllText(
        $win32SourcePath,
        $updatedWin32Source,
        [System.Text.UTF8Encoding]::new($false)
    )
    $win32MingwSupportPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-win32-maperror-impl'
    Path = $win32SourcePath
    Applied = $win32MingwSupportPatched
})

$globalsHeaderPath = Join-Path $resolvedSourceRoot 'src\globals.h'
if (-not (Test-Path -LiteralPath $globalsHeaderPath)) {
    throw "Expected Squid source file was not found at $globalsHeaderPath."
}

$globalsHeaderSource = Get-Content -Raw -LiteralPath $globalsHeaderPath
$globalsHeaderPatchMarker = '#if _SQUID_WINDOWS_ || _SQUID_MINGW_ /* squid4win-mingw-win32-globals */'
$globalsHeaderPatched = $false

if (-not $globalsHeaderSource.Contains($globalsHeaderPatchMarker)) {
    $newline = if ($globalsHeaderSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $updatedGlobalsHeaderSource = [regex]::Replace(
        $globalsHeaderSource,
        '(?m)^#if _SQUID_WINDOWS_\r?\n',
        $globalsHeaderPatchMarker + $newline,
        2
    )

    if ($updatedGlobalsHeaderSource -eq $globalsHeaderSource) {
        throw "Failed to expose the Win32 globals for MinGW in $globalsHeaderPath."
    }

    [System.IO.File]::WriteAllText(
        $globalsHeaderPath,
        $updatedGlobalsHeaderSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $globalsHeaderPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-win32-globals'
    Path = $globalsHeaderPath
    Applied = $globalsHeaderPatched
})

$enumsHeaderPath = Join-Path $resolvedSourceRoot 'src\enums.h'
if (-not (Test-Path -LiteralPath $enumsHeaderPath)) {
    throw "Expected Squid source file was not found at $enumsHeaderPath."
}

$enumsHeaderSource = Get-Content -Raw -LiteralPath $enumsHeaderPath
$enumsHeaderPatchMarker = '#if _SQUID_WINDOWS_ || _SQUID_MINGW_ /* squid4win-mingw-win32-os-enum */'
$enumsHeaderPatched = $false

if (-not $enumsHeaderSource.Contains($enumsHeaderPatchMarker)) {
    $newline = if ($enumsHeaderSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $updatedEnumsHeaderSource = [regex]::Replace(
        $enumsHeaderSource,
        '(?m)^#if _SQUID_WINDOWS_\r?\n',
        $enumsHeaderPatchMarker + $newline,
        1
    )

    if ($updatedEnumsHeaderSource -eq $enumsHeaderSource) {
        throw "Failed to expose the Win32 OS enum for MinGW in $enumsHeaderPath."
    }

    [System.IO.File]::WriteAllText(
        $enumsHeaderPath,
        $updatedEnumsHeaderSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $enumsHeaderPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-win32-os-enum'
    Path = $enumsHeaderPath
    Applied = $enumsHeaderPatched
})

$definesHeaderPath = Join-Path $resolvedSourceRoot 'src\defines.h'
if (-not (Test-Path -LiteralPath $definesHeaderPath)) {
    throw "Expected Squid source file was not found at $definesHeaderPath."
}

$definesHeaderSource = Get-Content -Raw -LiteralPath $definesHeaderPath
$definesHeaderPatchMarker = '#if _SQUID_WINDOWS_ || _SQUID_MINGW_ /* squid4win-mingw-service-defines */'
$definesHeaderPatched = $false

if (-not $definesHeaderSource.Contains($definesHeaderPatchMarker)) {
    $newline = if ($definesHeaderSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $updatedDefinesHeaderSource = [regex]::Replace(
        $definesHeaderSource,
        '(?m)^#if _SQUID_WINDOWS_\r?\n',
        $definesHeaderPatchMarker + $newline,
        1
    )

    if ($updatedDefinesHeaderSource -eq $definesHeaderSource) {
        throw "Failed to expose the Win32 service defines for MinGW in $definesHeaderPath."
    }

    [System.IO.File]::WriteAllText(
        $definesHeaderPath,
        $updatedDefinesHeaderSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $definesHeaderPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-service-defines'
    Path = $definesHeaderPath
    Applied = $definesHeaderPatched
})

$windowsServiceHeaderPath = Join-Path $resolvedSourceRoot 'src\windows_service.h'
if (-not (Test-Path -LiteralPath $windowsServiceHeaderPath)) {
    throw "Expected Squid source file was not found at $windowsServiceHeaderPath."
}

$windowsServiceHeaderSource = Get-Content -Raw -LiteralPath $windowsServiceHeaderPath
$windowsServiceHeaderPatchMarker = '#if _SQUID_WINDOWS_ || _SQUID_MINGW_ /* squid4win-mingw-windows-service */'
$windowsServiceHeaderPatched = $false

if (-not $windowsServiceHeaderSource.Contains($windowsServiceHeaderPatchMarker)) {
    $newline = if ($windowsServiceHeaderSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $updatedWindowsServiceHeaderSource = [regex]::Replace(
        $windowsServiceHeaderSource,
        '(?m)^#if _SQUID_WINDOWS_\r?\n',
        $windowsServiceHeaderPatchMarker + $newline,
        1
    )

    if ($updatedWindowsServiceHeaderSource -eq $windowsServiceHeaderSource) {
        throw "Failed to expose the Win32 service declarations for MinGW in $windowsServiceHeaderPath."
    }

    [System.IO.File]::WriteAllText(
        $windowsServiceHeaderPath,
        $updatedWindowsServiceHeaderSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $windowsServiceHeaderPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-windows-service-header'
    Path = $windowsServiceHeaderPath
    Applied = $windowsServiceHeaderPatched
})

$windowsServiceSourcePath = Join-Path $resolvedSourceRoot 'src\windows_service.cc'
if (-not (Test-Path -LiteralPath $windowsServiceSourcePath)) {
    throw "Expected Squid source file was not found at $windowsServiceSourcePath."
}

$windowsServiceSource = Get-Content -Raw -LiteralPath $windowsServiceSourcePath
$windowsServiceSourcePatchMarker = '#if _SQUID_WINDOWS_ || _SQUID_MINGW_ /* squid4win-mingw-windows-service-includes */'
$windowsServiceSourcePatched = $false

if (-not $windowsServiceSource.Contains($windowsServiceSourcePatchMarker)) {
    $newline = if ($windowsServiceSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $updatedWindowsServiceSource = [regex]::Replace(
        $windowsServiceSource,
        '(?m)^#if _SQUID_WINDOWS_\r?\n',
        $windowsServiceSourcePatchMarker + $newline,
        1
    )

    if ($updatedWindowsServiceSource -eq $windowsServiceSource) {
        throw "Failed to expose the Win32 service includes for MinGW in $windowsServiceSourcePath."
    }

    [System.IO.File]::WriteAllText(
        $windowsServiceSourcePath,
        $updatedWindowsServiceSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $windowsServiceSourcePatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-windows-service-includes'
    Path = $windowsServiceSourcePath
    Applied = $windowsServiceSourcePatched
})

$compatMswindowsSourcePath = Join-Path $resolvedSourceRoot 'compat\mswindows.cc'
if (-not (Test-Path -LiteralPath $compatMswindowsSourcePath)) {
    throw "Expected Squid source file was not found at $compatMswindowsSourcePath."
}

$compatMswindowsSource = Get-Content -Raw -LiteralPath $compatMswindowsSourcePath
$compatMswindowsPatchMarker = '#if (_SQUID_WINDOWS_ || _SQUID_MINGW_) && !_SQUID_CYGWIN_'
$compatMswindowsPatched = $false

if ($compatMswindowsSource.Contains($compatMswindowsPatchMarker)) {
    $updatedCompatMswindowsSource = $compatMswindowsSource.Replace(
        $compatMswindowsPatchMarker,
        '#if _SQUID_WINDOWS_ && !_SQUID_CYGWIN_'
    )

    if ($updatedCompatMswindowsSource -eq $compatMswindowsSource) {
        throw "Failed to restore the original compat/mswindows.cc guard at $compatMswindowsSourcePath."
    }

    [System.IO.File]::WriteAllText(
        $compatMswindowsSourcePath,
        $updatedCompatMswindowsSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $compatMswindowsPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-revert-compat-mswindows-support'
    Path = $compatMswindowsSourcePath
    Applied = $compatMswindowsPatched
})

$aiopsWin32SourcePath = Join-Path $resolvedSourceRoot 'src\DiskIO\DiskThreads\aiops_win32.cc'
if (-not (Test-Path -LiteralPath $aiopsWin32SourcePath)) {
    throw "Expected Squid source file was not found at $aiopsWin32SourcePath."
}

$aiopsWin32Source = Get-Content -Raw -LiteralPath $aiopsWin32SourcePath
$aiopsWin32AllocatorMarker = '#include "mem/Allocator.h" /* squid4win-mingw-mem-allocator */'
$aiopsWin32Patched = $false
$newline = if ($aiopsWin32Source.Contains("`r`n")) { "`r`n" } else { "`n" }
$aiopsWin32MapErrorPattern = [regex]'(?ms)^static void\r?\nsquidaio_maperror\(unsigned long win32Error\) /\* squid4win-mingw-maperror \*/\r?\n\{.*?^\}\r?\n(?:\r?\n)?'
$aiopsWin32MapErrorHelper = @'
static void
squidaio_maperror(unsigned long win32Error) /* squid4win-mingw-maperror */
{
    static const struct {
        unsigned long win32Code;
        int posixErrno;
    } errorTable[] = {
        {ERROR_INVALID_FUNCTION, EINVAL},
        {ERROR_FILE_NOT_FOUND, ENOENT},
        {ERROR_PATH_NOT_FOUND, ENOENT},
        {ERROR_TOO_MANY_OPEN_FILES, EMFILE},
        {ERROR_ACCESS_DENIED, EACCES},
        {ERROR_INVALID_HANDLE, EBADF},
        {ERROR_ARENA_TRASHED, ENOMEM},
        {ERROR_NOT_ENOUGH_MEMORY, ENOMEM},
        {ERROR_INVALID_BLOCK, ENOMEM},
        {ERROR_BAD_ENVIRONMENT, E2BIG},
        {ERROR_BAD_FORMAT, ENOEXEC},
        {ERROR_INVALID_ACCESS, EINVAL},
        {ERROR_INVALID_DATA, EINVAL},
        {ERROR_INVALID_DRIVE, ENOENT},
        {ERROR_CURRENT_DIRECTORY, EACCES},
        {ERROR_NOT_SAME_DEVICE, EXDEV},
        {ERROR_NO_MORE_FILES, ENOENT},
        {ERROR_LOCK_VIOLATION, EACCES},
        {ERROR_BAD_NETPATH, ENOENT},
        {ERROR_NETWORK_ACCESS_DENIED, EACCES},
        {ERROR_BAD_NET_NAME, ENOENT},
        {ERROR_FILE_EXISTS, EEXIST},
        {ERROR_CANNOT_MAKE, EACCES},
        {ERROR_FAIL_I24, EACCES},
        {ERROR_INVALID_PARAMETER, EINVAL},
        {ERROR_NO_PROC_SLOTS, EAGAIN},
        {ERROR_DRIVE_LOCKED, EACCES},
        {ERROR_BROKEN_PIPE, EPIPE},
        {ERROR_DISK_FULL, ENOSPC},
        {ERROR_INVALID_TARGET_HANDLE, EBADF},
        {ERROR_WAIT_NO_CHILDREN, ECHILD},
        {ERROR_CHILD_NOT_COMPLETE, ECHILD},
        {ERROR_DIRECT_ACCESS_HANDLE, EBADF},
        {ERROR_NEGATIVE_SEEK, EINVAL},
        {ERROR_SEEK_ON_DEVICE, EACCES},
        {ERROR_DIR_NOT_EMPTY, ENOTEMPTY},
        {ERROR_NOT_LOCKED, EACCES},
        {ERROR_BAD_PATHNAME, ENOENT},
        {ERROR_MAX_THRDS_REACHED, EAGAIN},
        {ERROR_LOCK_FAILED, EACCES},
        {ERROR_ALREADY_EXISTS, EEXIST},
        {ERROR_FILENAME_EXCED_RANGE, ENOENT},
        {ERROR_NESTING_NOT_ALLOWED, EAGAIN},
        {ERROR_NOT_ENOUGH_QUOTA, ENOMEM}
    };

    for (const auto &entry : errorTable) {
        if (win32Error == entry.win32Code) {
            errno = entry.posixErrno;
            return;
        }
    }

    if (win32Error >= ERROR_WRITE_PROTECT && win32Error <= ERROR_SHARING_BUFFER_EXCEEDED)
        errno = EACCES;
    else if (win32Error >= ERROR_INVALID_STARTING_CODESEG && win32Error <= ERROR_INFLOOP_IN_RELOC_CHAIN)
        errno = ENOEXEC;
    else
        errno = EINVAL;
}

'@ -replace "`r?`n", $newline

if (-not $aiopsWin32Source.Contains($aiopsWin32AllocatorMarker)) {
    $updatedAiopsWin32Source = [regex]::Replace(
        $aiopsWin32Source,
        '(?m)^#include "fd\.h"\r?\n#include "mem/Pool\.h"\r?\n',
        '#include "fd.h"' + $newline +
        '#include "mem/Allocator.h" /* squid4win-mingw-mem-allocator */' + $newline +
        '#include "mem/Pool.h"' + $newline +
        '#include "win32.h"' + $newline,
        1
    )

    if ($updatedAiopsWin32Source -eq $aiopsWin32Source) {
        throw "Failed to add MinGW allocator and win32 includes to $aiopsWin32SourcePath."
    }

    [System.IO.File]::WriteAllText(
        $aiopsWin32SourcePath,
        $updatedAiopsWin32Source,
        [System.Text.UTF8Encoding]::new($false)
    )
    $aiopsWin32Patched = $true
    $aiopsWin32Source = $updatedAiopsWin32Source
}

$updatedAiopsWin32Source = $aiopsWin32Source.Replace('WIN32_maperror(GetLastError())', 'squidaio_maperror(GetLastError())')
if ($updatedAiopsWin32Source -ne $aiopsWin32Source) {
    $aiopsWin32Patched = $true
    $aiopsWin32Source = $updatedAiopsWin32Source
}

$existingAiopsMapErrorMatches = $aiopsWin32MapErrorPattern.Matches($aiopsWin32Source)
if ($existingAiopsMapErrorMatches.Count -ne 1) {
    if ($existingAiopsMapErrorMatches.Count -gt 0) {
        $aiopsWin32Source = $aiopsWin32MapErrorPattern.Replace($aiopsWin32Source, '')
    }

    $updatedAiopsWin32Source = [regex]::Replace(
        $aiopsWin32Source,
        '(?m)^static HANDLE main_thread;\r?\n',
        'static HANDLE main_thread;' + $newline + $newline + $aiopsWin32MapErrorHelper,
        1
    )

    if ($updatedAiopsWin32Source -eq $aiopsWin32Source) {
        throw "Failed to normalize the MinGW Win32 error mapper in $aiopsWin32SourcePath."
    }

    $aiopsWin32Source = $updatedAiopsWin32Source
    $aiopsWin32Patched = $true
}

if ($aiopsWin32Patched) {
    [System.IO.File]::WriteAllText(
        $aiopsWin32SourcePath,
        $aiopsWin32Source,
        [System.Text.UTF8Encoding]::new($false)
    )
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-aiops-win32-includes'
    Path = $aiopsWin32SourcePath
    Applied = $aiopsWin32Patched
})

$aioWin32SourcePath = Join-Path $resolvedSourceRoot 'src\DiskIO\AIO\aio_win32.cc'
if (-not (Test-Path -LiteralPath $aioWin32SourcePath)) {
    throw "Expected Squid source file was not found at $aioWin32SourcePath."
}

$aioWin32Source = Get-Content -Raw -LiteralPath $aioWin32SourcePath
$aioWin32SourceGuardMarker = '#if _SQUID_WINDOWS_ || _SQUID_MINGW_ /* squid4win-mingw-aio-win32 */'
$aioWin32IntptrMarker = '#include <cstdint> /* squid4win-mingw-aio-intptr */'
$aioWin32SourcePatched = $false
$newline = if ($aioWin32Source.Contains("`r`n")) { "`r`n" } else { "`n" }

if (-not $aioWin32Source.Contains($aioWin32SourceGuardMarker)) {
    $updatedAioWin32Source = ([regex]'(?m)^#if _SQUID_WINDOWS_\r?\n').Replace(
        $aioWin32Source,
        $aioWin32SourceGuardMarker + $newline,
        1
    )

    if ($updatedAioWin32Source -eq $aioWin32Source) {
        throw "Failed to expose Win32 AIO implementations for MinGW in $aioWin32SourcePath."
    }

    [System.IO.File]::WriteAllText(
        $aioWin32SourcePath,
        $updatedAioWin32Source,
        [System.Text.UTF8Encoding]::new($false)
    )
    $aioWin32Source = $updatedAioWin32Source
    $aioWin32SourcePatched = $true
}

if (-not $aioWin32Source.Contains($aioWin32IntptrMarker)) {
    $updatedAioWin32Source = $aioWin32Source.Replace(
        '#include <cerrno>',
        '#include <cerrno>' + $newline + '#include <cstdint> /* squid4win-mingw-aio-intptr */'
    )

    if ($updatedAioWin32Source -eq $aioWin32Source) {
        throw "Failed to add pointer-width integer support to $aioWin32SourcePath."
    }

    $aioWin32Source = $updatedAioWin32Source
    $aioWin32SourcePatched = $true
}

$updatedAioWin32Source = $aioWin32Source.Replace(
    '_open_osfhandle((long) hndl, 0)',
    '_open_osfhandle(reinterpret_cast<intptr_t>(hndl), 0)'
)
if ($updatedAioWin32Source -ne $aioWin32Source) {
    $aioWin32Source = $updatedAioWin32Source
    $aioWin32SourcePatched = $true
}

if ($aioWin32SourcePatched) {
    [System.IO.File]::WriteAllText(
        $aioWin32SourcePath,
        $aioWin32Source,
        [System.Text.UTF8Encoding]::new($false)
    )
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-aio-win32-impl'
    Path = $aioWin32SourcePath
    Applied = $aioWin32SourcePatched
})

$aioDiskFileSourcePath = Join-Path $resolvedSourceRoot 'src\DiskIO\AIO\AIODiskFile.cc'
if (-not (Test-Path -LiteralPath $aioDiskFileSourcePath)) {
    throw "Expected Squid source file was not found at $aioDiskFileSourcePath."
}

$aioDiskFileSource = Get-Content -Raw -LiteralPath $aioDiskFileSourcePath
$aioDiskFileMarker = '#if _SQUID_WINDOWS_ || _SQUID_MINGW_ /* squid4win-mingw-aio-disk-file */'
$aioDiskFilePatched = $false
$newline = if ($aioDiskFileSource.Contains("`r`n")) { "`r`n" } else { "`n" }

if (-not $aioDiskFileSource.Contains($aioDiskFileMarker)) {
    $updatedAioDiskFileSource = ([regex]'(?m)^#if _SQUID_WINDOWS_\r?\n').Replace(
        $aioDiskFileSource,
        $aioDiskFileMarker + $newline,
        2
    )

    if ($updatedAioDiskFileSource -eq $aioDiskFileSource) {
        throw "Failed to route AIODiskFile through Win32 AIO on MinGW in $aioDiskFileSourcePath."
    }

    [System.IO.File]::WriteAllText(
        $aioDiskFileSourcePath,
        $updatedAioDiskFileSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $aioDiskFilePatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-aio-disk-file'
    Path = $aioDiskFileSourcePath
    Applied = $aioDiskFilePatched
})

$ipcWin32SourcePath = Join-Path $resolvedSourceRoot 'src\ipc_win32.cc'
if (-not (Test-Path -LiteralPath $ipcWin32SourcePath)) {
    throw "Expected Squid source file was not found at $ipcWin32SourcePath."
}

$ipcWin32Source = Get-Content -Raw -LiteralPath $ipcWin32SourcePath
$ipcWin32WinsockMarker = 'ipcWinSockGetSockName(SOCKET fd, struct sockaddr *addr, AddrLen *addrLen) /* squid4win-mingw-ipc-winsock */'
$ipcWin32Patched = $false

if (-not $ipcWin32Source.Contains($ipcWin32WinsockMarker)) {
    $newline = if ($ipcWin32Source.Contains("`r`n")) { "`r`n" } else { "`n" }
    $ipcWin32WinsockHelpers = @'
template <typename AddrLen>
static int
ipcWinSockGetSockName(SOCKET fd, struct sockaddr *addr, AddrLen *addrLen) /* squid4win-mingw-ipc-winsock */
{
#if _SQUID_MINGW_
    int winsockAddrLen = static_cast<int>(*addrLen);
    const int result = getsockname(fd, addr, &winsockAddrLen);
    *addrLen = static_cast<AddrLen>(winsockAddrLen);
    return result;
#else
    return getsockname(fd, addr, addrLen);
#endif
}

static int
ipcWinSockRecv(SOCKET fd, void *buf, int len) /* squid4win-mingw-ipc-winsock */
{
#if _SQUID_MINGW_
    return recv(fd, static_cast<char *>(buf), len, 0);
#else
    return recv(fd, buf, len, 0);
#endif
}

static int
ipcWinSockSend(SOCKET fd, const void *buf, int len) /* squid4win-mingw-ipc-winsock */
{
#if _SQUID_MINGW_
    return send(fd, static_cast<const char *>(buf), len, 0);
#else
    return send(fd, buf, len, 0);
#endif
}

'@ -replace "`r?`n", $newline

    $updatedIpcWin32Source = [regex]::Replace(
        $ipcWin32Source,
        '(?m)^static char hello_buf\[HELLO_BUF_SZ\];\r?\n',
        'static char hello_buf[HELLO_BUF_SZ];' + $newline + $newline + $ipcWin32WinsockHelpers,
        1
    )

    if ($updatedIpcWin32Source -eq $ipcWin32Source) {
        throw "Failed to add the MinGW ipc_win32 Winsock helpers to $ipcWin32SourcePath."
    }

    $ipcWin32Source = $updatedIpcWin32Source.Replace(
        'getsockname(pwfd, aiPS->ai_addr, &(aiPS->ai_addrlen) )',
        'ipcWinSockGetSockName(pwfd, aiPS->ai_addr, &(aiPS->ai_addrlen) )'
    )
    $ipcWin32Source = $ipcWin32Source.Replace(
        'getsockname(crfd, aiCS->ai_addr, &(aiCS->ai_addrlen) )',
        'ipcWinSockGetSockName(crfd, aiCS->ai_addr, &(aiCS->ai_addrlen) )'
    )
    $ipcWin32Source = $ipcWin32Source.Replace(
        'getsockname(pwfd_ipc, aiPS_ipc->ai_addr, &(aiPS_ipc->ai_addrlen))',
        'ipcWinSockGetSockName(pwfd_ipc, aiPS_ipc->ai_addr, &(aiPS_ipc->ai_addrlen))'
    )
    $ipcWin32Source = $ipcWin32Source.Replace(
        'getsockname(crfd_ipc, aiCS_ipc->ai_addr, &(aiCS_ipc->ai_addrlen))',
        'ipcWinSockGetSockName(crfd_ipc, aiCS_ipc->ai_addr, &(aiCS_ipc->ai_addrlen))'
    )
    $ipcWin32Source = $ipcWin32Source.Replace(
        'recv(prfd, (void *)hello_buf, HELLO_BUF_SZ - 1, 0)',
        'ipcWinSockRecv(prfd, hello_buf, HELLO_BUF_SZ - 1)'
    )
    $ipcWin32Source = $ipcWin32Source.Replace(
        'send(pwfd, (const void *)ok_string, strlen(ok_string), 0)',
        'ipcWinSockSend(pwfd, ok_string, strlen(ok_string))'
    )
    $ipcWin32Source = $ipcWin32Source.Replace(
        'send(cwfd, (const void *)buf, len, 0)',
        'ipcWinSockSend(cwfd, buf, len)'
    )
    $ipcWin32Source = $ipcWin32Source.Replace(
        'send(cwfd, (const void *)hello_string, strlen(hello_string) + 1, 0)',
        'ipcWinSockSend(cwfd, hello_string, strlen(hello_string) + 1)'
    )
    $ipcWin32Source = $ipcWin32Source.Replace(
        'recv(crfd, (void *)buf1, bufSz-1, 0)',
        'ipcWinSockRecv(crfd, buf1, bufSz-1)'
    )
    $ipcWin32Source = $ipcWin32Source.Replace(
        'send(pwfd_ipc, (const void *)ok_string, strlen(ok_string), 0)',
        'ipcWinSockSend(pwfd_ipc, ok_string, strlen(ok_string))'
    )
    $ipcWin32Source = $ipcWin32Source.Replace(
        'recv(prfd_ipc, (void *)(buf1 + 200), bufSz -1 - 200, 0)',
        'ipcWinSockRecv(prfd_ipc, buf1 + 200, bufSz -1 - 200)'
    )
    $ipcWin32Source = $ipcWin32Source.Replace(
        'send(pwfd_ipc, (const void *)buf1, x, 0)',
        'ipcWinSockSend(pwfd_ipc, buf1, x)'
    )
    $ipcWin32Source = $ipcWin32Source.Replace(
        'send(crfd_ipc, (const void *)shutdown_string, strlen(shutdown_string), 0)',
        'ipcWinSockSend(crfd_ipc, shutdown_string, strlen(shutdown_string))'
    )
    $ipcWin32Source = $ipcWin32Source.Replace(
        'recv(rfd, (void *)buf2, bufSz-1, 0)',
        'ipcWinSockRecv(rfd, buf2, bufSz-1)'
    )
    $ipcWin32Source = $ipcWin32Source.Replace(
        'send(send_fd, (const void *)buf2, x, 0)',
        'ipcWinSockSend(send_fd, buf2, x)'
    )

    [System.IO.File]::WriteAllText(
        $ipcWin32SourcePath,
        $ipcWin32Source,
        [System.Text.UTF8Encoding]::new($false)
    )
    $ipcWin32Patched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-ipc-win32-winsock'
    Path = $ipcWin32SourcePath
    Applied = $ipcWin32Patched
})

$fdSourcePath = Join-Path $resolvedSourceRoot 'src\fd.cc'
if (-not (Test-Path -LiteralPath $fdSourcePath)) {
    throw "Expected Squid source file was not found at $fdSourcePath."
}

$fdSource = Get-Content -Raw -LiteralPath $fdSourcePath
$fdMsghdrMarker = 'recvmsg(int fd, msghdr *msg, int flags) /* squid4win-mingw-fd-msghdr */'
$fdPatched = $false

if (-not $fdSource.Contains($fdMsghdrMarker)) {
    $newline = if ($fdSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $updatedFdSource = [regex]::Replace(
        $fdSource,
        '(?m)^#include "globals\.h"\r?\n',
        '#include "globals.h"' + $newline +
        '#include "compat/cmsg.h" /* squid4win-mingw-fd-msghdr */' + $newline +
        '#include "win32.h"' + $newline +
        '#include <vector>' + $newline,
        1
    )

    $fdMsghdrCompat = @'
#ifndef MSG_DONTWAIT
#define MSG_DONTWAIT 0 /* squid4win-mingw-fd-msghdr */
#endif

#if _SQUID_MINGW_
#if !defined(WSAID_WSASENDMSG)
typedef INT (WSAAPI *LPFN_WSASENDMSG)(SOCKET s, LPWSAMSG lpMsg, DWORD dwFlags,
                                      LPDWORD lpNumberOfBytesSent,
                                      LPWSAOVERLAPPED lpOverlapped,
                                      LPWSAOVERLAPPED_COMPLETION_ROUTINE lpCompletionRoutine);
#define WSAID_WSASENDMSG {0xa441e712,0x754f,0x43ca,{0x84,0xa7,0x0d,0xee,0x44,0xcf,0x60,0x6d}}
#endif

namespace {
template <class Extension>
static Extension
fdLoadWinsockExtension(const SOCKET fd, const GUID &guid) /* squid4win-mingw-fd-msghdr */
{
    Extension extension = nullptr;
    DWORD bytes = 0;
    if (WSAIoctl(fd, SIO_GET_EXTENSION_FUNCTION_POINTER,
                 const_cast<GUID *>(&guid), sizeof(guid),
                 &extension, sizeof(extension), &bytes,
                 nullptr, nullptr) == SOCKET_ERROR) {
        WIN32_maperror(WSAGetLastError());
        return nullptr;
    }
    return extension;
}

static void
fdCopyMsgHdrToWsaMsg(const msghdr &msg, WSAMSG &wsaMsg, std::vector<WSABUF> &buffers) /* squid4win-mingw-fd-msghdr */
{
    buffers.clear();
    buffers.reserve(msg.msg_iovlen);
    for (size_t i = 0; i < msg.msg_iovlen; ++i) {
        WSABUF buffer;
        buffer.buf = static_cast<char *>(msg.msg_iov[i].iov_base);
        buffer.len = static_cast<ULONG>(msg.msg_iov[i].iov_len);
        buffers.push_back(buffer);
    }

    wsaMsg.name = static_cast<LPSOCKADDR>(msg.msg_name);
    wsaMsg.namelen = static_cast<INT>(msg.msg_namelen);
    wsaMsg.lpBuffers = buffers.empty() ? nullptr : buffers.data();
    wsaMsg.dwBufferCount = static_cast<DWORD>(buffers.size());
    wsaMsg.Control.buf = static_cast<char *>(msg.msg_control);
    wsaMsg.Control.len = static_cast<ULONG>(msg.msg_controllen);
    wsaMsg.dwFlags = static_cast<DWORD>(msg.msg_flags);
}
} // namespace

static int
recvmsg(int fd, msghdr *msg, int flags) /* squid4win-mingw-fd-msghdr */
{
    static LPFN_WSARECVMSG receiveMessage = nullptr;
    if (!receiveMessage) {
        const GUID receiveMessageGuid = WSAID_WSARECVMSG;
        receiveMessage = fdLoadWinsockExtension<LPFN_WSARECVMSG>(fd, receiveMessageGuid);
        if (!receiveMessage)
            return -1;
    }

    std::vector<WSABUF> buffers;
    WSAMSG wsaMsg;
    memset(&wsaMsg, 0, sizeof(wsaMsg));
    fdCopyMsgHdrToWsaMsg(*msg, wsaMsg, buffers);
    wsaMsg.dwFlags = static_cast<DWORD>(flags);

    DWORD bytesReceived = 0;
    if (receiveMessage(fd, &wsaMsg, &bytesReceived, nullptr, nullptr) == SOCKET_ERROR) {
        WIN32_maperror(WSAGetLastError());
        return -1;
    }

    msg->msg_namelen = static_cast<socklen_t>(wsaMsg.namelen);
    msg->msg_controllen = static_cast<size_t>(wsaMsg.Control.len);
    msg->msg_flags = static_cast<int>(wsaMsg.dwFlags);
    return static_cast<int>(bytesReceived);
}

static int
sendmsg(int fd, const msghdr *msg, int flags) /* squid4win-mingw-fd-msghdr */
{
    static LPFN_WSASENDMSG sendMessage = nullptr;
    if (!sendMessage) {
        const GUID sendMessageGuid = WSAID_WSASENDMSG;
        sendMessage = fdLoadWinsockExtension<LPFN_WSASENDMSG>(fd, sendMessageGuid);
        if (!sendMessage)
            return -1;
    }

    std::vector<WSABUF> buffers;
    WSAMSG wsaMsg;
    memset(&wsaMsg, 0, sizeof(wsaMsg));
    fdCopyMsgHdrToWsaMsg(*msg, wsaMsg, buffers);

    DWORD bytesSent = 0;
    if (sendMessage(fd, &wsaMsg, static_cast<DWORD>(flags), &bytesSent, nullptr, nullptr) == SOCKET_ERROR) {
        WIN32_maperror(WSAGetLastError());
        return -1;
    }

    return static_cast<int>(bytesSent);
}
#endif

'@ -replace "`r?`n", $newline

    $updatedFdSource = [regex]::Replace(
        $updatedFdSource,
        '(?m)^#ifndef MSG_NOSIGNAL\r?\n#define MSG_NOSIGNAL 0\r?\n#endif\r?\n',
        '$0' + $fdMsghdrCompat,
        1
    )

    if ($updatedFdSource -eq $fdSource) {
        throw "Failed to add the MinGW fd msghdr compatibility layer to $fdSourcePath."
    }

    [System.IO.File]::WriteAllText(
        $fdSourcePath,
        $updatedFdSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $fdPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-fd-msghdr'
    Path = $fdSourcePath
    Applied = $fdPatched
})

$mainSourcePath = Join-Path $resolvedSourceRoot 'src\main.cc'
if (-not (Test-Path -LiteralPath $mainSourcePath)) {
    throw "Expected Squid source file was not found at $mainSourcePath."
}

$mainSource = Get-Content -Raw -LiteralPath $mainSourcePath
$mainGuardMarker = '_SQUID_MINGW_) /* squid4win-mingw-main-guards */'
$mainPatched = $false

if (-not $mainSource.Contains($mainGuardMarker)) {
    $newline = if ($mainSource.Contains("`r`n")) { "`r`n" } else { "`n" }

    $updatedMainSource = $mainSource.Replace(
        '#if !_SQUID_WINDOWS_',
        '#if !(_SQUID_WINDOWS_ || _SQUID_MINGW_) /* squid4win-mingw-main-guards */'
    )
    $updatedMainSource = $updatedMainSource.Replace(
        '#if _SQUID_WINDOWS_',
        '#if (_SQUID_WINDOWS_ || _SQUID_MINGW_) /* squid4win-mingw-main-guards */'
    )
    $updatedMainSource = $updatedMainSource.Replace(
        '#if !defined(_SQUID_WINDOWS_) && !defined(HAVE_SIGACTION)',
        '#if !defined(_SQUID_WINDOWS_) && !defined(_SQUID_MINGW_) && !defined(HAVE_SIGACTION) /* squid4win-mingw-main-guards */'
    )

    $originalChrootBlock = @'
    if (Config.chroot_dir && !Chrooted) {
        Chrooted = true;

        if (chroot(Config.chroot_dir) != 0) {
            int xerrno = errno;
            fatalf("chroot to %s failed: %s", Config.chroot_dir, xstrerr(xerrno));
        }

        if (!mainChangeDir("/"))
            fatalf("chdir to / after chroot to %s failed", Config.chroot_dir);
    }
'@ -replace "`r?`n", $newline

    $replacementChrootBlock = @'
    if (Config.chroot_dir && !Chrooted) {
        Chrooted = true;
#if _SQUID_MINGW_
        fatalf("chroot_dir is not supported on native MinGW builds");
#else
        if (chroot(Config.chroot_dir) != 0) {
            int xerrno = errno;
            fatalf("chroot to %s failed: %s", Config.chroot_dir, xstrerr(xerrno));
        }

        if (!mainChangeDir("/"))
            fatalf("chdir to / after chroot to %s failed", Config.chroot_dir);
#endif
    }
'@ -replace "`r?`n", $newline

    $updatedMainSource = $updatedMainSource.Replace($originalChrootBlock, $replacementChrootBlock)

    if ($updatedMainSource -eq $mainSource) {
        throw "Failed to add the MinGW main.cc guard compatibility layer to $mainSourcePath."
    }

    [System.IO.File]::WriteAllText(
        $mainSourcePath,
        $updatedMainSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $mainPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-main-guards'
    Path = $mainSourcePath
    Applied = $mainPatched
})

$mainWin32IncludeMarker = '#include "win32.h" /* squid4win-mingw-main-win32 */'
$mainWin32IncludePatched = $false
$mainSource = Get-Content -Raw -LiteralPath $mainSourcePath
if (-not $mainSource.Contains($mainWin32IncludeMarker)) {
    $newline = if ($mainSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $updatedMainSource = [regex]::Replace(
        $mainSource,
        '(?m)^#include "globals\.h"\r?\n',
        '#include "globals.h"' + $newline +
        $mainWin32IncludeMarker + $newline,
        1
    )

    if ($updatedMainSource -eq $mainSource) {
        throw "Failed to include win32.h in $mainSourcePath for MinGW."
    }

    [System.IO.File]::WriteAllText(
        $mainSourcePath,
        $updatedMainSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $mainWin32IncludePatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-main-win32-include'
    Path = $mainSourcePath
    Applied = $mainWin32IncludePatched
})

$toolsSourcePath = Join-Path $resolvedSourceRoot 'src\tools.cc'
if (-not (Test-Path -LiteralPath $toolsSourcePath)) {
    throw "Expected Squid source file was not found at $toolsSourcePath."
}

$toolsSource = Get-Content -Raw -LiteralPath $toolsSourcePath
$toolsPatchMarker = 'reinterpret_cast<LPTSTR>(&rawMessage) /* squid4win-mingw-tools */'
$toolsPatched = $false

if (-not $toolsSource.Contains($toolsPatchMarker)) {
    $newline = if ($toolsSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $originalWaitForOnePidBlock = @'
pid_t
WaitForOnePid(pid_t pid, PidStatus &status, int flags)
{
#if _SQUID_WINDOWS_
    return 0; // function not used on Windows
#else
    return waitpid(pid, &status, flags);
#endif
}
'@ -replace "`r?`n", $newline
    $replacementWaitForOnePidBlock = @'
pid_t
WaitForOnePid(pid_t pid, PidStatus &status, int flags)
{
#if _SQUID_WINDOWS_ || _SQUID_MINGW_ /* squid4win-mingw-tools */
    return 0; // function not used on Windows
#else
    return waitpid(pid, &status, flags);
#endif
}
'@ -replace "`r?`n", $newline
    $updatedToolsSource = $toolsSource.Replace(
        $originalWaitForOnePidBlock,
        $replacementWaitForOnePidBlock
    )

    $updatedToolsSource = $updatedToolsSource.Replace(
        'static_cast<LPTSTR>(&rawMessage)',
        'reinterpret_cast<LPTSTR>(&rawMessage) /* squid4win-mingw-tools */'
    )

    if ($updatedToolsSource -eq $toolsSource) {
        throw "Failed to add the MinGW tools.cc compatibility fixes to $toolsSourcePath."
    }

    [System.IO.File]::WriteAllText(
        $toolsSourcePath,
        $updatedToolsSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $toolsPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-tools-compat'
    Path = $toolsSourcePath
    Applied = $toolsPatched
})

$commSourcePath = Join-Path $resolvedSourceRoot 'src\comm.cc'
if (-not (Test-Path -LiteralPath $commSourcePath)) {
    throw "Expected Squid source file was not found at $commSourcePath."
}

$commSource = Get-Content -Raw -LiteralPath $commSourcePath
$commPatchMarker = 'commSockRecvFrom(int fd, void *buf, size_t len, int flags, struct sockaddr *from, size_t *fromLen) /* squid4win-mingw-comm */'
$commPatched = $false
$newline = if ($commSource.Contains("`r`n")) { "`r`n" } else { "`n" }
$commHelperPatch = @'
static int
commSockRecvFrom(int fd, void *buf, size_t len, int flags, struct sockaddr *from, size_t *fromLen) /* squid4win-mingw-comm */
{
#if _SQUID_MINGW_
    int winsockFromLen = static_cast<int>(*fromLen);
    const int result = recvfrom(fd, static_cast<char *>(buf), static_cast<int>(len), flags, from, &winsockFromLen);
    *fromLen = static_cast<size_t>(winsockFromLen);
    return result;
#else
    return recvfrom(fd, buf, len, flags, from, fromLen);
#endif
}

static ssize_t
commSockSend(int fd, const void *buf, size_t len, int flags) /* squid4win-mingw-comm */
{
#if _SQUID_MINGW_
    return send(fd, static_cast<const char *>(buf), static_cast<int>(len), flags);
#else
    return send(fd, buf, len, flags);
#endif
}

static int
commSockGetSockName(int fd, struct sockaddr *name, size_t *nameLen) /* squid4win-mingw-comm */
{
#if _SQUID_MINGW_
    int winsockNameLen = static_cast<int>(*nameLen);
    const int result = getsockname(fd, name, &winsockNameLen);
    *nameLen = static_cast<size_t>(winsockNameLen);
    return result;
#else
    return getsockname(fd, name, nameLen);
#endif
}

static int
commSockGetSockOptInt(int fd, int level, int optname, int *value, int *valueLen) /* squid4win-mingw-comm */
{
#if _SQUID_MINGW_
    return getsockopt(fd, level, optname, reinterpret_cast<char *>(value), valueLen);
#else
    return getsockopt(fd, level, optname, value, valueLen);
#endif
}

static int
commSockSendTo(int fd, const void *buf, int len, int flags, const struct sockaddr *to, size_t toLen) /* squid4win-mingw-comm */
{
#if _SQUID_MINGW_
    return sendto(fd, static_cast<const char *>(buf), len, flags, to, static_cast<int>(toLen));
#else
    return sendto(fd, buf, len, flags, to, toLen);
#endif
}

'@ -replace "`r?`n", $newline

if (-not $commSource.Contains($commPatchMarker)) {
    $updatedCommSource = $commSource.Replace(
        'static int comm_apply_flags(int new_socket, Ip::Address &addr, int flags, struct addrinfo *AI);' + $newline + $newline + '#if USE_DELAY_POOLS',
        'static int comm_apply_flags(int new_socket, Ip::Address &addr, int flags, struct addrinfo *AI);' + $newline + $newline + $commHelperPatch + '#if USE_DELAY_POOLS'
    )

    $updatedCommSource = $updatedCommSource.Replace(
        'int x = recvfrom(fd, buf, len, flags, AI->ai_addr, &AI->ai_addrlen);',
        'int x = commSockRecvFrom(fd, buf, len, flags, AI->ai_addr, &AI->ai_addrlen);'
    )
    $updatedCommSource = $updatedCommSource.Replace(
        '    return send(s, buf, len, flags);',
        '    return commSockSend(s, buf, len, flags);'
    )
    $updatedCommSource = $updatedCommSource.Replace(
        '    if (getsockname(fd, addr->ai_addr, &(addr->ai_addrlen)) ) {',
        '    if (commSockGetSockName(fd, addr->ai_addr, &(addr->ai_addrlen)) ) {'
    )
    $updatedCommSource = $updatedCommSource.Replace(
        '            x = getsockopt(sock, SOL_SOCKET, SO_ERROR, &err, &errlen);',
        '            x = commSockGetSockOptInt(sock, SOL_SOCKET, SO_ERROR, &err, &errlen);'
    )
    $updatedCommSource = $updatedCommSource.Replace(
        '        x = getsockopt(sock, SOL_SOCKET, SO_ERROR, &err, &errlen);',
        '        x = commSockGetSockOptInt(sock, SOL_SOCKET, SO_ERROR, &err, &errlen);'
    )
    $updatedCommSource = $updatedCommSource.Replace(
        '    int x = sendto(fd, buf, len, 0, AI->ai_addr, AI->ai_addrlen);',
        '    int x = commSockSendTo(fd, buf, len, 0, AI->ai_addr, AI->ai_addrlen);'
    )

    if ($updatedCommSource -eq $commSource) {
        throw "Failed to add the MinGW comm.cc compatibility helpers to $commSourcePath."
    }

    [System.IO.File]::WriteAllText(
        $commSourcePath,
        $updatedCommSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $commPatched = $true
}

$commSource = Get-Content -Raw -LiteralPath $commSourcePath
$firstCommHelperIndex = $commSource.IndexOf($commHelperPatch)
if ($firstCommHelperIndex -ge 0) {
    $nextCommHelperIndex = $commSource.IndexOf($commHelperPatch, $firstCommHelperIndex + $commHelperPatch.Length)
    while ($nextCommHelperIndex -ge 0) {
        $commSource = $commSource.Remove($nextCommHelperIndex, $commHelperPatch.Length)
        $nextCommHelperIndex = $commSource.IndexOf($commHelperPatch, $firstCommHelperIndex + $commHelperPatch.Length)
        $commPatched = $true
    }

    [System.IO.File]::WriteAllText(
        $commSourcePath,
        $commSource,
        [System.Text.UTF8Encoding]::new($false)
    )
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-comm-compat'
    Path = $commSourcePath
    Applied = $commPatched
})

$cbdataSourcePath = Join-Path $resolvedSourceRoot 'src\cbdata.cc'
if (-not (Test-Path -LiteralPath $cbdataSourcePath)) {
    throw "Expected Squid source file was not found at $cbdataSourcePath."
}

$cbdataSource = Get-Content -Raw -LiteralPath $cbdataSourcePath
$cbdataPatchMarker = 'std::intptr_t cookie; /* squid4win-mingw-cbdata-cookie */'
$cbdataPatched = $false

if (-not $cbdataSource.Contains($cbdataPatchMarker)) {
    $newline = if ($cbdataSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $updatedCbdataSource = $cbdataSource.Replace(
        '#include <cstddef>',
        '#include <cstddef>' + $newline + '#include <cstdint>'
    )

    $updatedCbdataSource = $updatedCbdataSource.Replace(
        '    long cookie;',
        '    std::intptr_t cookie; /* squid4win-mingw-cbdata-cookie */'
    )
    $updatedCbdataSource = $updatedCbdataSource.Replace(
        '    void check(int) const {assert(cookie == ((long)this ^ Cookie));}',
        '    void check(int) const {assert(cookie == (reinterpret_cast<std::intptr_t>(this) ^ Cookie));}'
    )
    $updatedCbdataSource = $updatedCbdataSource.Replace(
        '    static const long Cookie;',
        '    static const std::intptr_t Cookie;'
    )
    $updatedCbdataSource = $updatedCbdataSource.Replace(
        'const long cbdata::Cookie((long)0xDEADBEEF);',
        'const std::intptr_t cbdata::Cookie(static_cast<std::intptr_t>(0xDEADBEEF));'
    )
    $updatedCbdataSource = $updatedCbdataSource.Replace(
        '    c->cookie = (long) c ^ cbdata::Cookie;',
        '    c->cookie = reinterpret_cast<std::intptr_t>(c) ^ cbdata::Cookie;'
    )

    if ($updatedCbdataSource -eq $cbdataSource) {
        throw "Failed to apply the cbdata pointer-width cookie fix to $cbdataSourcePath."
    }

    [System.IO.File]::WriteAllText(
        $cbdataSourcePath,
        $updatedCbdataSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $cbdataPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-cbdata-cookie'
    Path = $cbdataSourcePath
    Applied = $cbdataPatched
})

$typedMsgHdrSourcePath = Join-Path $resolvedSourceRoot 'src\ipc\TypedMsgHdr.cc'
if (-not (Test-Path -LiteralPath $typedMsgHdrSourcePath)) {
    throw "Expected Squid source file was not found at $typedMsgHdrSourcePath."
}

$typedMsgHdrSource = Get-Content -Raw -LiteralPath $typedMsgHdrSourcePath
$typedMsgHdrPatched = $false
$newline = if ($typedMsgHdrSource.Contains("`r`n")) { "`r`n" } else { "`n" }
$typedMsgHdrHelperMarker = 'firstControlMessage(const msghdr *msg) /* squid4win-mingw-first-cmsg */'
$typedMsgHdrHelper = @'
namespace {
static inline struct cmsghdr *
firstControlMessage(msghdr *msg) /* squid4win-mingw-first-cmsg */
{
    return msg && msg->msg_control && msg->msg_controllen >= sizeof(struct cmsghdr) ?
           reinterpret_cast<struct cmsghdr *>(msg->msg_control) :
           nullptr;
}

static inline const struct cmsghdr *
firstControlMessage(const msghdr *msg) /* squid4win-mingw-first-cmsg */
{
    return msg && msg->msg_control && msg->msg_controllen >= sizeof(struct cmsghdr) ?
           reinterpret_cast<const struct cmsghdr *>(msg->msg_control) :
           nullptr;
}
} // namespace

'@ -replace "`r?`n", $newline

if (-not $typedMsgHdrSource.Contains($typedMsgHdrHelperMarker)) {
    $updatedTypedMsgHdrSource = [regex]::Replace(
        $typedMsgHdrSource,
        '(?m)^#include <cstring>\r?\n',
        '#include <cstring>' + $newline + $newline + $typedMsgHdrHelper,
        1
    )

    if ($updatedTypedMsgHdrSource -eq $typedMsgHdrSource) {
        throw "Failed to add the MinGW first-control-message helper to $typedMsgHdrSourcePath."
    }

    $typedMsgHdrSource = $updatedTypedMsgHdrSource
    $typedMsgHdrPatched = $true
}

$updatedTypedMsgHdrSource = $typedMsgHdrSource.Replace(
    'struct cmsghdr *cmsg = CMSG_FIRSTHDR(this);',
    'auto cmsg = firstControlMessage(this);'
).Replace(
    'const int *fdStore = reinterpret_cast<const int*>(SQUID_CMSG_DATA(cmsg));',
    'const int *fdStore = reinterpret_cast<const int*>(SQUID_CMSG_DATA(const_cast<struct cmsghdr *>(cmsg))); /* squid4win-mingw-first-cmsg */'
)

if ($updatedTypedMsgHdrSource -ne $typedMsgHdrSource) {
    [System.IO.File]::WriteAllText(
        $typedMsgHdrSourcePath,
        $updatedTypedMsgHdrSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $typedMsgHdrPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-typedmsghdr-first-cmsg'
    Path = $typedMsgHdrSourcePath
    Applied = $typedMsgHdrPatched
})

$certificateDbSourcePath = Join-Path $resolvedSourceRoot 'src\security\cert_generators\file\certificate_db.cc'
if (-not (Test-Path -LiteralPath $certificateDbSourcePath)) {
    throw "Expected Squid source file was not found at $certificateDbSourcePath."
}

$certificateDbSource = Get-Content -Raw -LiteralPath $certificateDbSourcePath
$certificateDbPatchMarker = '#if _SQUID_WINDOWS_ || _SQUID_MINGW_ /* squid4win-mingw-certificate-db-locking */'
$certificateDbPatched = $false

if (-not $certificateDbSource.Contains($certificateDbPatchMarker)) {
    $newline = if ($certificateDbSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $updatedCertificateDbSource = [regex]::Replace(
        $certificateDbSource,
        '(?m)^#if _SQUID_WINDOWS_\r?\n',
        $certificateDbPatchMarker + $newline,
        5
    )

    if ($updatedCertificateDbSource -eq $certificateDbSource) {
        throw "Failed to switch the certificate DB locking path to the Windows/MinGW branch in $certificateDbSourcePath."
    }

    [System.IO.File]::WriteAllText(
        $certificateDbSourcePath,
        $updatedCertificateDbSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $certificateDbPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-certificate-db-locking'
    Path = $certificateDbSourcePath
    Applied = $certificateDbPatched
})

$certificateDbHeaderPath = Join-Path $resolvedSourceRoot 'src\security\cert_generators\file\certificate_db.h'
if (-not (Test-Path -LiteralPath $certificateDbHeaderPath)) {
    throw "Expected Squid source file was not found at $certificateDbHeaderPath."
}

$certificateDbHeaderSource = Get-Content -Raw -LiteralPath $certificateDbHeaderPath
$certificateDbHeaderPatchMarker = '#if _SQUID_WINDOWS_ || _SQUID_MINGW_ /* squid4win-mingw-certificate-db-handle */'
$certificateDbHeaderPatched = $false

if (-not $certificateDbHeaderSource.Contains($certificateDbHeaderPatchMarker)) {
    $newline = if ($certificateDbHeaderSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $updatedCertificateDbHeaderSource = [regex]::Replace(
        $certificateDbHeaderSource,
        '(?m)^#if _SQUID_WINDOWS_\r?\n',
        $certificateDbHeaderPatchMarker + $newline,
        1
    )

    if ($updatedCertificateDbHeaderSource -eq $certificateDbHeaderSource) {
        throw "Failed to switch the certificate DB lock handle declaration to the Windows/MinGW branch in $certificateDbHeaderPath."
    }

    [System.IO.File]::WriteAllText(
        $certificateDbHeaderPath,
        $updatedCertificateDbHeaderSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $certificateDbHeaderPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-certificate-db-handle'
    Path = $certificateDbHeaderPath
    Applied = $certificateDbHeaderPatched
})

$securityFileCertgenSourcePath = Join-Path $resolvedSourceRoot 'src\security\cert_generators\file\security_file_certgen.cc'
if (-not (Test-Path -LiteralPath $securityFileCertgenSourcePath)) {
    throw "Expected Squid source file was not found at $securityFileCertgenSourcePath."
}

$securityFileCertgenSource = Get-Content -Raw -LiteralPath $securityFileCertgenSourcePath
$securityFileCertgenFatalMarker = 'fatalf(const char *fmt, ...) /* squid4win-mingw-security-file-certgen-fatal */'
$securityFileCertgenPatched = $false

if (-not $securityFileCertgenSource.Contains($securityFileCertgenFatalMarker)) {
    $newline = if ($securityFileCertgenSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $securityFileCertgenFatalStub = @'
#include <cstdarg>
#include <cstdio>
#include <cstdlib>

void
fatalf(const char *fmt, ...) /* squid4win-mingw-security-file-certgen-fatal */
{
    va_list args;
    va_start(args, fmt);
    vfprintf(stderr, fmt, args);
    fputc('\n', stderr);
    va_end(args);
    exit(EXIT_FAILURE);
}

'@ -replace "`r?`n", $newline

    $updatedSecurityFileCertgenSource = [regex]::Replace(
        $securityFileCertgenSource,
        '(?m)^#include <string>\r?\n',
        '#include <string>' + $newline + $securityFileCertgenFatalStub,
        1
    )

    if ($updatedSecurityFileCertgenSource -eq $securityFileCertgenSource) {
        throw "Failed to add the MinGW fatalf stub to $securityFileCertgenSourcePath."
    }

    [System.IO.File]::WriteAllText(
        $securityFileCertgenSourcePath,
        $updatedSecurityFileCertgenSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $securityFileCertgenPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-security-file-certgen-fatal'
    Path = $securityFileCertgenSourcePath
    Applied = $securityFileCertgenPatched
})

$securityFileCertgenMakefileAmPath = Join-Path $resolvedSourceRoot 'src\security\cert_generators\file\Makefile.am'
if (-not (Test-Path -LiteralPath $securityFileCertgenMakefileAmPath)) {
    throw "Expected Squid source file was not found at $securityFileCertgenMakefileAmPath."
}

$securityFileCertgenMakefileAmSource = Get-Content -Raw -LiteralPath $securityFileCertgenMakefileAmPath
$securityFileCertgenLinkMarker = '$(MINGW_LIBS) \'
$securityFileCertgenLinkRegex = [regex]::new('(?m)^([ \t]*)\$\((SSLLIB)\) \\\r?\n\1\$\((COMPAT_LIB)\)')
$securityFileCertgenMakefileAmPatched = $false

if (-not $securityFileCertgenMakefileAmSource.Contains($securityFileCertgenLinkMarker)) {
    $newline = if ($securityFileCertgenMakefileAmSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $updatedSecurityFileCertgenMakefileAmSource = $securityFileCertgenLinkRegex.Replace(
        $securityFileCertgenMakefileAmSource,
        {
            param($match)
            $indent = $match.Groups[1].Value
            return $indent + '$(SSLLIB) \' + $newline +
                $indent + '$(MINGW_LIBS) \' + $newline +
                $indent + '$(COMPAT_LIB)'
        },
        1
    )

    if ($updatedSecurityFileCertgenMakefileAmSource -eq $securityFileCertgenMakefileAmSource) {
        throw "Failed to add MinGW helper link libraries to $securityFileCertgenMakefileAmPath."
    }

    [System.IO.File]::WriteAllText(
        $securityFileCertgenMakefileAmPath,
        $updatedSecurityFileCertgenMakefileAmSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $securityFileCertgenMakefileAmPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-security-file-certgen-link'
    Path = $securityFileCertgenMakefileAmPath
    Applied = $securityFileCertgenMakefileAmPatched
})

$securityFileCertgenMakefileInPath = Join-Path $resolvedSourceRoot 'src\security\cert_generators\file\Makefile.in'
if (-not (Test-Path -LiteralPath $securityFileCertgenMakefileInPath)) {
    throw "Expected Squid source file was not found at $securityFileCertgenMakefileInPath."
}

$securityFileCertgenMakefileInSource = Get-Content -Raw -LiteralPath $securityFileCertgenMakefileInPath
$securityFileCertgenMakefileInPatched = $false

if (-not $securityFileCertgenMakefileInSource.Contains($securityFileCertgenLinkMarker)) {
    $newline = if ($securityFileCertgenMakefileInSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $updatedSecurityFileCertgenMakefileInSource = $securityFileCertgenLinkRegex.Replace(
        $securityFileCertgenMakefileInSource,
        {
            param($match)
            $indent = $match.Groups[1].Value
            return $indent + '$(SSLLIB) \' + $newline +
                $indent + '$(MINGW_LIBS) \' + $newline +
                $indent + '$(COMPAT_LIB)'
        },
        1
    )

    if ($updatedSecurityFileCertgenMakefileInSource -eq $securityFileCertgenMakefileInSource) {
        throw "Failed to add MinGW helper link libraries to $securityFileCertgenMakefileInPath."
    }

    [System.IO.File]::WriteAllText(
        $securityFileCertgenMakefileInPath,
        $updatedSecurityFileCertgenMakefileInSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $securityFileCertgenMakefileInPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-security-file-certgen-link'
    Path = $securityFileCertgenMakefileInPath
    Applied = $securityFileCertgenMakefileInPatched
})

$qosConfigSourcePath = Join-Path $resolvedSourceRoot 'src\ip\QosConfig.cc'
if (-not (Test-Path -LiteralPath $qosConfigSourcePath)) {
    throw "Expected Squid source file was not found at $qosConfigSourcePath."
}

$qosConfigSource = Get-Content -Raw -LiteralPath $qosConfigSourcePath
$qosConfigPatched = $false

$updatedQosConfigSource = $qosConfigSource.Replace(
    'const int x = setsockopt(fd, IPPROTO_IP, IP_TOS, &bTos, sizeof(bTos));',
    'const int x = setsockopt(fd, IPPROTO_IP, IP_TOS, reinterpret_cast<const char *>(&bTos), sizeof(bTos));'
)
if ($updatedQosConfigSource -ne $qosConfigSource) {
    $qosConfigSource = $updatedQosConfigSource
    $qosConfigPatched = $true
}

$updatedQosConfigSource = $qosConfigSource.Replace(
    'const int x = setsockopt(fd, IPPROTO_IPV6, IPV6_TCLASS, &bTos, sizeof(bTos));',
    'const int x = setsockopt(fd, IPPROTO_IPV6, IPV6_TCLASS, reinterpret_cast<const char *>(&bTos), sizeof(bTos));'
)
if ($updatedQosConfigSource -ne $qosConfigSource) {
    $qosConfigSource = $updatedQosConfigSource
    $qosConfigPatched = $true
}

if ($qosConfigPatched) {
    [System.IO.File]::WriteAllText(
        $qosConfigSourcePath,
        $qosConfigSource,
        [System.Text.UTF8Encoding]::new($false)
    )
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-qos-setsockopt-cast'
    Path = $qosConfigSourcePath
    Applied = $qosConfigPatched
})

$logFileDaemonSourcePath = Join-Path $resolvedSourceRoot 'src\log\file\log_file_daemon.cc'
if (-not (Test-Path -LiteralPath $logFileDaemonSourcePath)) {
    throw "Expected Squid source file was not found at $logFileDaemonSourcePath."
}

$logFileDaemonSource = Get-Content -Raw -LiteralPath $logFileDaemonSourcePath
$logFileDaemonPatchMarker = '#define _PATH_DEVNULL "NUL" /* squid4win-mingw-devnull */'
$logFileDaemonPatched = $false

if (-not $logFileDaemonSource.Contains($logFileDaemonPatchMarker)) {
    $newline = if ($logFileDaemonSource.Contains("`r`n")) { "`r`n" } else { "`n" }
    $updatedLogFileDaemonSource = [regex]::Replace(
        $logFileDaemonSource,
        '(?m)^#if HAVE_PATHS_H\r?\n#include <paths\.h>\r?\n#endif\r?\n',
        '#if HAVE_PATHS_H' + $newline +
        '#include <paths.h>' + $newline +
        '#endif' + $newline +
        '#if _SQUID_MINGW_ && !defined(_PATH_DEVNULL)' + $newline +
        '#define _PATH_DEVNULL "NUL" /* squid4win-mingw-devnull */' + $newline +
        '#endif' + $newline,
        1
    )

    if ($updatedLogFileDaemonSource -eq $logFileDaemonSource) {
        throw "Failed to add the MinGW devnull fallback to $logFileDaemonSourcePath."
    }

    [System.IO.File]::WriteAllText(
        $logFileDaemonSourcePath,
        $updatedLogFileDaemonSource,
        [System.Text.UTF8Encoding]::new($false)
    )
    $logFileDaemonPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-log-file-daemon-devnull'
    Path = $logFileDaemonSourcePath
    Applied = $logFileDaemonPatched
})

$radiusLinkPatched = $false

foreach ($radiusMakefilePath in @(
    (Join-Path $resolvedSourceRoot 'src\auth\basic\RADIUS\Makefile.am'),
    (Join-Path $resolvedSourceRoot 'src\auth\basic\RADIUS\Makefile.in')
)) {
    if (-not (Test-Path -LiteralPath $radiusMakefilePath)) {
        throw "Expected Squid source file was not found at $radiusMakefilePath."
    }

    $radiusMakefileSource = Get-Content -Raw -LiteralPath $radiusMakefilePath
    if ($radiusMakefileSource -notmatch '\$\(MINGW_LIBS\)') {
        $newline = if ($radiusMakefileSource.Contains("`r`n")) { "`r`n" } else { "`n" }
        $updatedRadiusMakefileSource = $radiusMakefileSource.Replace(
            '$(XTRA_LIBS)',
            '$(XTRA_LIBS) \' + $newline + '	$(MINGW_LIBS)'
        )

        if ($updatedRadiusMakefileSource -eq $radiusMakefileSource) {
            throw "Failed to add MINGW_LIBS to the RADIUS helper link line in $radiusMakefilePath."
        }

        [System.IO.File]::WriteAllText(
            $radiusMakefilePath,
            $updatedRadiusMakefileSource,
            [System.Text.UTF8Encoding]::new($false)
        )
        $radiusLinkPatched = $true
    }

    $patchResults.Add([PSCustomObject]@{
        Name = 'mingw-radius-helper-link-libs'
        Path = $radiusMakefilePath
        Applied = $radiusLinkPatched
    })
}

$mingwWinsockPatched = $false

foreach ($mingwLibsPath in @(
    (Join-Path $resolvedSourceRoot 'configure.ac'),
    (Join-Path $resolvedSourceRoot 'configure')
)) {
    if (-not (Test-Path -LiteralPath $mingwLibsPath)) {
        throw "Expected Squid source file was not found at $mingwLibsPath."
    }

    $mingwLibsSource = Get-Content -Raw -LiteralPath $mingwLibsPath
    if ($mingwLibsSource.Contains('MINGW_LIBS="-lmingwex"')) {
        $updatedMingwLibsSource = $mingwLibsSource.Replace(
            'MINGW_LIBS="-lmingwex"',
            'MINGW_LIBS="-lmingwex -lws2_32"'
        )

        [System.IO.File]::WriteAllText(
            $mingwLibsPath,
            $updatedMingwLibsSource,
            [System.Text.UTF8Encoding]::new($false)
        )
        $mingwWinsockPatched = $true
    }

    $patchResults.Add([PSCustomObject]@{
        Name = 'mingw-winsock-link-libs'
        Path = $mingwLibsPath
        Applied = $mingwWinsockPatched
    })
}

$strictErrorConfigurePath = Join-Path $resolvedSourceRoot 'configure'
if (-not (Test-Path -LiteralPath $strictErrorConfigurePath)) {
    throw "Expected Squid configure script was not found at $strictErrorConfigurePath."
}

$strictErrorPatchMarker = '# squid4win-mingw-disable-strict-errors'
$strictErrorPattern = [regex]'(?m)^(if test "x\$enable_strict_error_checking" != "xno"\r?\nthen :\r?\n)'
$strictErrorPrefix = @'
# squid4win-mingw-disable-strict-errors
case $host_os in
  mingw*) enable_strict_error_checking=no ;;
esac
'@

$strictErrorConfigureScript = Get-Content -Raw -LiteralPath $strictErrorConfigurePath
$strictErrorPatched = $false

if (-not $strictErrorConfigureScript.Contains($strictErrorPatchMarker)) {
    $newline = if ($strictErrorConfigureScript.Contains("`r`n")) { "`r`n" } else { "`n" }
    $strictErrorBlock = ($strictErrorPrefix -replace "`r?`n", $newline) + $newline
    $updatedStrictErrorConfigureScript = $strictErrorPattern.Replace(
        $strictErrorConfigureScript,
        {
            param($match)

            $strictErrorBlock + $match.Groups[1].Value
        },
        1
    )

    if ($updatedStrictErrorConfigureScript -eq $strictErrorConfigureScript) {
        throw "Failed to apply the MinGW strict-error-checking workaround to $strictErrorConfigurePath."
    }

    [System.IO.File]::WriteAllText(
        $strictErrorConfigurePath,
        $updatedStrictErrorConfigureScript,
        [System.Text.UTF8Encoding]::new($false)
    )
    $strictErrorPatched = $true
}

$patchResults.Add([PSCustomObject]@{
    Name = 'mingw-disable-strict-error-checking'
    Path = $strictErrorConfigurePath
    Applied = $strictErrorPatched
})

$configurePatchMarker = '# squid4win-mingw-disable-deptrack'
$configureDependencyPattern = [regex]'(?m)^(if test "x\$enable_dependency_tracking" != xno; then\r?\n)'
$configureDependencyPrefix = @'
# squid4win-mingw-disable-deptrack
case $host_os in
  mingw*) enable_dependency_tracking=no ;;
esac
'@

foreach ($configureScriptPath in @(
    (Join-Path $resolvedSourceRoot 'configure'),
    (Join-Path $resolvedSourceRoot 'libltdl\configure')
)) {
    if (-not (Test-Path -LiteralPath $configureScriptPath)) {
        throw "Expected Squid configure script was not found at $configureScriptPath."
    }

    $configureScript = Get-Content -Raw -LiteralPath $configureScriptPath
    $configureScriptPatched = $false

    if (-not $configureScript.Contains($configurePatchMarker)) {
        $newline = if ($configureScript.Contains("`r`n")) { "`r`n" } else { "`n" }
        $configureDependencyBlock = ($configureDependencyPrefix -replace "`r?`n", $newline) + $newline
        $updatedConfigureScript = $configureDependencyPattern.Replace(
            $configureScript,
            {
                param($match)

                $configureDependencyBlock + $match.Groups[1].Value
            },
            1
        )

        if ($updatedConfigureScript -eq $configureScript) {
            throw "Failed to apply the MinGW dependency tracking workaround to $configureScriptPath."
        }

        [System.IO.File]::WriteAllText(
            $configureScriptPath,
            $updatedConfigureScript,
            [System.Text.UTF8Encoding]::new($false)
        )
        $configureScriptPatched = $true
    }

    $patchResults.Add([PSCustomObject]@{
        Name = 'mingw-disable-dependency-tracking'
        Path = $configureScriptPath
        Applied = $configureScriptPatched
    })
}

$patchResults
