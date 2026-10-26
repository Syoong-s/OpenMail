/* Exercise the production launcher's Windows quoting against the OS parser. */
#define wWinMain launcher_main_for_arguments_test
#include "../native/windows/launcher.c"
#undef wWinMain
#include <stdio.h>

/* ==========================================
 * Function: Verify native argv survives empty strings, Unicode, quotes and trailing slashes.
 * Method: Round-trip the production argument builder through CommandLineToArgvW.
 * ========================================== */
int wmain(void){
    const wchar_t *expected[]={L"TeleMail.exe",L"",L"中文 path",L"C:\\folder\\",L"two\\\"quote",L"back\\\\\\\"escape",L"plain"};
    wchar_t command[4096]={0};size_t used=0;int total=(int)(sizeof(expected)/sizeof(expected[0]));
    for(int index=0;index<total;++index)if(!argument(command,4096,&used,expected[index]))return 2;
    int count=0;LPWSTR *actual=CommandLineToArgvW(command,&count);
    if(!actual||count!=total)return 3;
    for(int index=0;index<total;++index)if(wcscmp(actual[index],expected[index])){LocalFree(actual);return 4;}
    LocalFree(actual);
    wchar_t small[8]={0};used=0;if(argument(small,8,&used,L"too-long-command"))return 5;
    puts("Native launcher argv: 7 round trips and overflow rejection passed");return 0;
}
