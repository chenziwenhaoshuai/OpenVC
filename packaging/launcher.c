/*
 * Tiny launcher for the portable OpenVC build.
 *
 * Compiled with mingw as a windowed exe (~50 KB).  It only starts the bundled
 * interpreter:
 *
 *     <app>\runtime\pythonw.exe -m app.main_qt
 *
 * with the working directory set to <app>, so `import app` resolves through the
 * `..` entry in python311._pth.  No PyInstaller, no unpacking at startup.
 */
#include <windows.h>

static void app_dir(wchar_t *out, DWORD n)
{
    GetModuleFileNameW(NULL, out, n);
    wchar_t *p = wcsrchr(out, L'\\');
    if (p) *p = L'\0';
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR args, int show)
{
    (void)inst; (void)prev; (void)args; (void)show;

    wchar_t base[MAX_PATH];
    app_dir(base, MAX_PATH);

    wchar_t python[MAX_PATH];
    lstrcpyW(python, base);
    lstrcatW(python, L"\\runtime\\pythonw.exe");

    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES) {
        wchar_t msg[MAX_PATH + 200];
        lstrcpyW(msg, L"缺少运行时:\n");
        lstrcatW(msg, python);
        lstrcatW(msg, L"\n\n请重新解压完整压缩包。");
        MessageBoxW(NULL, msg, L"OpenVC 启动失败", MB_ICONERROR);
        return 1;
    }

    wchar_t cmd[MAX_PATH * 2];
    lstrcpyW(cmd, L"\"");
    lstrcatW(cmd, python);
    lstrcatW(cmd, L"\" -m app.main_qt");

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));

    if (!CreateProcessW(python, cmd, NULL, NULL, FALSE, 0, NULL, base, &si, &pi)) {
        wchar_t msg[256];
        wsprintfW(msg, L"启动失败 (错误码 %lu)", GetLastError());
        MessageBoxW(NULL, msg, L"OpenVC 启动失败", MB_ICONERROR);
        return 1;
    }

    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
