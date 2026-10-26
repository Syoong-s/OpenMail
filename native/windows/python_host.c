/* Project-owned CPython DLL host with an explicit Windows UTF-8 process manifest. */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <wchar.h>

/* ==========================================
 * Function: Run the pinned private CPython DLL with native Unicode arguments and UTF-8 Win32 APIs.
 * Method: Load only the adjacent runtime DLL and call its public Py_Main entry; keep it until process exit.
 * ========================================== */
int wmain(int argc,wchar_t **argv){
    wchar_t library[32768];DWORD count=GetModuleFileNameW(NULL,library,32768);
    if(!count||count>=32768){fputs("TeleMail: cannot locate private Python host\n",stderr);return 1;}
    wchar_t *name=wcsrchr(library,L'\\');
    if(!name||wcslen(L"python314.dll")>=32768-(size_t)(name+1-library))return 1;
    wcscpy(name+1,L"python314.dll");
    if(!SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_DEFAULT_DIRS))return 1;
    HMODULE runtime=LoadLibraryExW(library,NULL,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if(!runtime){fprintf(stderr,"TeleMail: cannot load private Python DLL (%lu)\n",GetLastError());return 1;}
    typedef int (__cdecl *PythonMain)(int,wchar_t **);
    PythonMain run=(PythonMain)(void *)GetProcAddress(runtime,"Py_Main");
    if(!run){fputs("TeleMail: private Python DLL has no Py_Main\n",stderr);return 1;}
    /* The interpreter and extension DLLs retain module state through process teardown. */
    return run(argc,argv);
}
