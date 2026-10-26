/* Native Windows GUI entry point: private CPython runtime, no shell or WSL. */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>

/* ==========================================
 * Function: Append one UTF-16 string to a bounded command buffer.
 * Method: Advance the cursor only when its complete terminating zero fits.
 * ========================================== */
static int append(wchar_t *buffer,size_t capacity,size_t *used,const wchar_t *value){
    size_t length=wcslen(value);if(*used+length>=capacity)return 0;
    memcpy(buffer+*used,value,(length+1)*sizeof(wchar_t));*used+=length;return 1;
}

/* ==========================================
 * Function: Quote one Windows argv element without a command interpreter.
 * Method: Apply CommandLineToArgvW backslash-before-quote rules, including trailing slashes.
 * ========================================== */
static int argument(wchar_t *buffer,size_t capacity,size_t *used,const wchar_t *value){
    if(!append(buffer,capacity,used,*used?L" \"":L"\""))return 0;
    while(*value){
        size_t slashes=0;while(*value==L'\\'){++slashes;++value;}
        if(*value==L'"'||!*value)slashes*=2;
        while(slashes--)if(!append(buffer,capacity,used,L"\\"))return 0;
        if(!*value)break;
        if(*value==L'"'&&!append(buffer,capacity,used,L"\\"))return 0;
        wchar_t character[2]={*value++,0};if(!append(buffer,capacity,used,character))return 0;
    }
    return append(buffer,capacity,used,L"\"");
}

/* ==========================================
 * Function: Report a startup failure through a native dialog and diagnostic log.
 * Method: Show only operational errors, never launch arguments or mailbox credentials.
 * ========================================== */
static int failure(const wchar_t *message){MessageBoxW(NULL,message,L"TeleMail",MB_OK|MB_ICONERROR);return 1;}

/* ==========================================
 * Function: Start the native Windows client from a relocatable portable directory.
 * Method: Launch private Python with Unicode argv and hidden console, wait, and preserve exit status.
 * ========================================== */
int WINAPI wWinMain(HINSTANCE instance,HINSTANCE previous,PWSTR raw,int show){
    (void)instance;(void)previous;(void)raw;(void)show;
    wchar_t root[32768],python[32768],bootstrap[32768],runtime[32768];
    DWORD length=GetModuleFileNameW(NULL,root,32768);if(!length||length>=32768)return failure(L"无法定位 TeleMail.exe。");
    SetEnvironmentVariableW(L"TELEMAIL_LAUNCHER",root);
    wchar_t *separator=wcsrchr(root,L'\\');if(!separator)return failure(L"应用目录无效。");*separator=0;
    if(swprintf(python,32768,L"%ls\\runtime\\python\\python.exe",root)<0||
       swprintf(bootstrap,32768,L"%ls\\app\\bootstrap.py",root)<0||
       swprintf(runtime,32768,L"%ls\\runtime",root)<0)return failure(L"应用路径过长。");
    if(GetFileAttributesW(python)==INVALID_FILE_ATTRIBUTES||GetFileAttributesW(bootstrap)==INVALID_FILE_ATTRIBUTES)
        return failure(L"TeleMail 发行目录不完整。请保留 TeleMail.exe、app 和 runtime 文件夹。");
    SetEnvironmentVariableW(L"TELEMAIL_WINDOWS_RUNTIME",runtime);
    SetEnvironmentVariableW(L"TELEMAIL_APP_ROOT",root);
    int count=0;LPWSTR *args=CommandLineToArgvW(GetCommandLineW(),&count);
    if(!args)return failure(L"无法读取启动参数。");
    wchar_t command[32768];command[0]=0;size_t used=0;
    int valid=argument(command,32768,&used,python)&&append(command,32768,&used,L" -I -B -X utf8")&&argument(command,32768,&used,bootstrap);
    for(int index=1;valid&&index<count;++index)valid=argument(command,32768,&used,args[index]);
    LocalFree(args);if(!valid)return failure(L"启动参数过长。");
    HANDLE output=GetStdHandle(STD_OUTPUT_HANDLE),error=GetStdHandle(STD_ERROR_HANDLE),logfile=INVALID_HANDLE_VALUE;
    DWORD outtype=output&&output!=INVALID_HANDLE_VALUE?GetFileType(output):FILE_TYPE_UNKNOWN;
    if(outtype!=FILE_TYPE_PIPE&&outtype!=FILE_TYPE_DISK){
        wchar_t folder[32768],logs[32768],logpath[32768];DWORD found=GetEnvironmentVariableW(L"LOCALAPPDATA",folder,32768);
        if(!found||found>=32768)GetTempPathW(32768,folder);
        swprintf(logs,32768,L"%ls\\TeleMail",folder);CreateDirectoryW(logs,NULL);
        swprintf(logs,32768,L"%ls\\TeleMail\\logs",folder);CreateDirectoryW(logs,NULL);
        swprintf(logpath,32768,L"%ls\\desktop.log",logs);
        logfile=CreateFileW(logpath,FILE_APPEND_DATA,FILE_SHARE_READ|FILE_SHARE_WRITE,NULL,OPEN_ALWAYS,FILE_ATTRIBUTE_NORMAL,NULL);
        if(logfile!=INVALID_HANDLE_VALUE){SetHandleInformation(logfile,HANDLE_FLAG_INHERIT,HANDLE_FLAG_INHERIT);output=error=logfile;}
    }
    STARTUPINFOW startup={0};startup.cb=sizeof(startup);startup.dwFlags=STARTF_USESHOWWINDOW|STARTF_USESTDHANDLES;
    startup.wShowWindow=SW_HIDE;startup.hStdOutput=output;startup.hStdError=error;startup.hStdInput=GetStdHandle(STD_INPUT_HANDLE);
    if(!startup.hStdInput||startup.hStdInput==INVALID_HANDLE_VALUE){
        SECURITY_ATTRIBUTES security={sizeof(security),NULL,TRUE};
        startup.hStdInput=CreateFileW(L"NUL",GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE,&security,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL);
    }
    PROCESS_INFORMATION process={0};
    BOOL created=CreateProcessW(python,command,NULL,NULL,TRUE,CREATE_NO_WINDOW,NULL,root,&startup,&process);
    if(logfile!=INVALID_HANDLE_VALUE)CloseHandle(logfile);
    if(!created)return failure(L"无法启动应用运行库。请检查发行目录和安全软件设置。");
    CloseHandle(process.hThread);WaitForSingleObject(process.hProcess,INFINITE);
    DWORD result=1;GetExitCodeProcess(process.hProcess,&result);CloseHandle(process.hProcess);return (int)result;
}
