// Native WebView2 surfaces for inert mail and isolated local PDF.js documents.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <objbase.h>
#include <WebView2.h>
#include <algorithm>
#include <atomic>
#include <functional>
#include <cstring>
#include <cmath>
#include <memory>
#include <string>
#include <vector>

// ==========================================
// Function: Retain COM callbacks until asynchronous browser operations complete.
// Method: Implement the documented IUnknown contract with one typed Invoke delegate.
// ==========================================
template<class Interface,class... Args> struct Handler final:Interface {
    std::atomic<ULONG> refs{1};std::function<HRESULT(Args...)> callback;
    // ==========================================
    // Function: Store one typed asynchronous COM event delegate.
    // Method: Move the host-owned callable into reference-counted storage.
    // ==========================================
    explicit Handler(std::function<HRESULT(Args...)> value):callback(std::move(value)){}
    // ==========================================
    // Function: Expose only IUnknown and the exact implemented event interface.
    // Method: Match interface UUIDs and increment COM ownership on success.
    // ==========================================
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID id,void** out) override {
        if(!out)return E_POINTER;*out=nullptr;
        if(IsEqualIID(id,IID_IUnknown)||IsEqualIID(id,__uuidof(Interface))){*out=static_cast<Interface*>(this);AddRef();return S_OK;}return E_NOINTERFACE;
    }
    // ==========================================
    // Function: Retain one asynchronous callback reference.
    // Method: Atomically increment the COM ownership counter.
    // ==========================================
    ULONG STDMETHODCALLTYPE AddRef() override{return ++refs;}
    // ==========================================
    // Function: Release one asynchronous callback reference.
    // Method: Destroy the delegate only after its final COM owner releases.
    // ==========================================
    ULONG STDMETHODCALLTYPE Release() override{ULONG count=--refs;if(!count)delete this;return count;}
    // ==========================================
    // Function: Dispatch one typed WebView2 callback on the GTK COM apartment.
    // Method: Invoke only application-owned handlers with SDK-defined arguments.
    // ==========================================
    HRESULT STDMETHODCALLTYPE Invoke(Args... args) override{return callback(args...);}
};

// ==========================================
// Function: Share one sandboxed browser environment across lazy mail views.
// Method: Retain pending views by shared ownership and release all controllers explicitly.
// ==========================================
struct View {
    RECT last_bounds{},last_position{},last_clip{},last_cut{},last_root_screen{},logical_box{},logical_clip{},logical_cut{};
    std::vector<RECT> logical_exclusions,last_exclusions;
    int logical_width=0,logical_height=0,root_width=0,root_height=0;
    HWND root=nullptr;bool geometry_known=false,last_visible=false,last_shown=false;
    HWND parent=nullptr;ICoreWebView2Controller* controller=nullptr;ICoreWebView2* web=nullptr;ICoreWebView2_2* dom_web=nullptr;
    std::string pending;std::wstring link,error,origin,pdf_prefix;bool closed=false,visible=true,ready=false,remote=false;
    double zoom=1,wheel=0;HRESULT result=E_PENDING;unsigned generation=0;UINT64 navigation_id=0;
    unsigned query_id=0;bool query_ready=false;std::wstring query_result;std::vector<unsigned> keys;
    EventRegistrationToken nav_token{},complete_token{},dom_token{},popup_token{},resource_token{},permission_token{},download_token{},key_token{},wheel_token{};
    // ==========================================
    // Function: Release any remaining native browser ownership.
    // Method: Close the controller before releasing its final COM references.
    // ==========================================
    ~View(){if(dom_web)dom_web->Release();if(web)web->Release();if(controller){controller->Close();controller->Release();}if(parent&&IsWindow(parent))DestroyWindow(parent);}
};
struct Handle {std::shared_ptr<View> value;};
static ICoreWebView2Environment* environment=nullptr;
static ICoreWebView2Environment5* environment_events=nullptr;
static EventRegistrationToken browser_exit_token{};
static std::vector<UINT32> exited_browsers;
static unsigned document_serial=0;
static bool environment_pending=false;
static bool com_initialized=false;
static bool shutting_down=false;
static HMODULE loader_module=nullptr;
static std::vector<HANDLE> browser_processes;
static unsigned pending_controllers=0;
static HRESULT last_close_result=S_OK;
static unsigned close_count=0,close_failures=0,surface_moves=0,surface_regions=0;
static ULONG last_controller_refs=0,last_web_refs=0,last_environment_refs=0;
static std::vector<std::weak_ptr<View>> waiting;
static std::vector<std::weak_ptr<View>> views;
typedef HRESULT(STDAPICALLTYPE* CreateEnvironment)(PCWSTR,PCWSTR,ICoreWebView2EnvironmentOptions*,ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler*);

// ==========================================
// Function: Position one independently owned browser surface without modifying GTK-owned regions.
// Method: Cache placement and full floating-layer exclusions; leave stationary surfaces untouched.
// ==========================================
static void resize(const std::shared_ptr<View>& view){
    if(!view->controller||view->closed||!view->parent||!IsWindow(view->root))return;
    if(view->root_width<1||view->root_height<1||view->logical_width<1||view->logical_height<1)return;
    RECT root{},root_screen{};GetClientRect(view->root,&root);GetWindowRect(view->root,&root_screen);
    RECT position{MulDiv(view->logical_box.left,root.right,view->root_width),MulDiv(view->logical_box.top,root.bottom,view->root_height),
        std::max(1,MulDiv(view->logical_width,root.right,view->root_width)),std::max(1,MulDiv(view->logical_height,root.bottom,view->root_height))};
    RECT bounds{0,0,position.right,position.bottom};
    bool moved=!view->geometry_known||!EqualRect(&position,&view->last_position);
    if(moved){SetWindowPos(view->parent,HWND_TOP,position.left,position.top,position.right,position.bottom,SWP_NOACTIVATE);++surface_moves;}
    if(!view->geometry_known||!EqualRect(&bounds,&view->last_bounds))view->controller->put_Bounds(bounds);
    RECT clip{MulDiv(view->logical_clip.left,bounds.right,view->logical_width),MulDiv(view->logical_clip.top,bounds.bottom,view->logical_height),
        MulDiv(view->logical_clip.right,bounds.right,view->logical_width),MulDiv(view->logical_clip.bottom,bounds.bottom,view->logical_height)};
    RECT cut{MulDiv(view->logical_cut.left,bounds.right,view->logical_width),MulDiv(view->logical_cut.top,bounds.bottom,view->logical_height),
        MulDiv(view->logical_cut.right,bounds.right,view->logical_width),MulDiv(view->logical_cut.bottom,bounds.bottom,view->logical_height)};
    if(IsRectEmpty(&clip))SetRectEmpty(&clip);if(IsRectEmpty(&cut))SetRectEmpty(&cut);
    std::vector<RECT> exclusions;
    for(const RECT& logical:view->logical_exclusions){
        RECT area{MulDiv(logical.left,bounds.right,view->logical_width),MulDiv(logical.top,bounds.bottom,view->logical_height),
            MulDiv(logical.right,bounds.right,view->logical_width),MulDiv(logical.bottom,bounds.bottom,view->logical_height)},inside{};
        if(IntersectRect(&inside,&bounds,&area))exclusions.push_back(inside);
    }
    bool same_exclusions=exclusions.size()==view->last_exclusions.size();
    if(same_exclusions)for(size_t i=0;i<exclusions.size();++i)if(!EqualRect(&exclusions[i],&view->last_exclusions[i])){same_exclusions=false;break;}
    bool region_changed=!view->geometry_known||!EqualRect(&clip,&view->last_clip)||!EqualRect(&cut,&view->last_cut)||!same_exclusions;
    if(region_changed){
        HRGN region=CreateRectRgn(clip.left,clip.top,clip.right,clip.bottom);
        if(region){
            if(!IsRectEmpty(&cut)){HRGN hole=CreateEllipticRgn(cut.left,cut.top,cut.right,cut.bottom);if(hole){CombineRgn(region,region,hole,RGN_DIFF);DeleteObject(hole);}}
            for(const RECT& area:exclusions){HRGN hole=CreateRectRgn(area.left,area.top,area.right,area.bottom);if(hole){CombineRgn(region,region,hole,RGN_DIFF);DeleteObject(hole);}}
            if(!SetWindowRgn(view->parent,region,FALSE))DeleteObject(region);else ++surface_regions;
        }
    }
    if(moved||region_changed||!EqualRect(&root_screen,&view->last_root_screen))view->controller->NotifyParentWindowPositionChanged();
    if(!view->geometry_known||view->visible!=view->last_visible)view->controller->put_IsVisible(view->visible);
    bool shown=view->visible&&view->ready&&!IsRectEmpty(&clip);
    if(!view->geometry_known||shown!=view->last_shown)ShowWindow(view->parent,shown?SW_SHOWNOACTIVATE:SW_HIDE);
    if(moved||region_changed||shown!=view->last_shown)InvalidateRect(view->root,nullptr,FALSE);
    view->last_bounds=bounds;view->last_position=position;view->last_clip=clip;view->last_cut=cut;view->last_exclusions=std::move(exclusions);
    view->last_visible=view->visible;view->last_shown=shown;view->last_root_screen=root_screen;view->geometry_known=true;
}

// ==========================================
// Function: Retain a waitable handle for the exact browser process owned by one controller.
// Method: Use the documented process ID and deduplicate handles without enumerating unrelated Edge processes.
// ==========================================
static void track_browser(ICoreWebView2* web){
    if(!web)return;UINT32 pid=0;if(FAILED(web->get_BrowserProcessId(&pid))||!pid)return;
    HANDLE process=OpenProcess(SYNCHRONIZE|PROCESS_QUERY_LIMITED_INFORMATION,FALSE,pid);
    if(process){bool known=false;for(HANDLE old:browser_processes)if(GetProcessId(old)==pid)known=true;if(known)CloseHandle(process);else browser_processes.push_back(process);}
}

// ==========================================
// Function: Show inert formatted content as soon as the DOM is ready, independently of remote image latency.
// Method: Install trusted host interaction hooks once per document; mail JavaScript remains blocked by sanitization and CSP.
// ==========================================
static void reveal_document(const std::shared_ptr<View>& view){
    if(view->closed||!view->web||view->ready)return;
    view->ready=true;
    std::wstring script=LR"JS((()=>{const token='maildesk-wheel:)JS"+std::to_wstring(view->generation)+LR"JS(:';
        document.addEventListener('pointerdown',event=>{if(event.isTrusted)window.chrome.webview.postMessage(token.replace('wheel:','click:'));},{capture:true});
        document.addEventListener('wheel',event=>{
            if(!event.isTrusted||event.ctrlKey||!event.deltaY||Math.abs(event.deltaX)>Math.abs(event.deltaY))return;
            const delta=event.deltaY*(event.deltaMode===1?40:event.deltaMode===2?innerHeight:1);
            if(!Number.isFinite(delta))return;
            for(let node=event.target instanceof Element?event.target:document.body;node;node=node.parentElement){
                const style=getComputedStyle(node);
                // Fitted mail hides root overflow; scrollHeight alone does not make that root user-scrollable.
                const root=node===document.scrollingElement;
                const overflow=root&&style.overflowY==='visible'&&document.body?getComputedStyle(document.body).overflowY:style.overflowY;
                const scrollable=/^(auto|scroll|overlay)$/.test(overflow)||(root&&!/^(hidden|clip)$/.test(overflow));
                if(scrollable&&node.scrollHeight>node.clientHeight+1&&
                   (delta<0?node.scrollTop>1:node.scrollTop+node.clientHeight<node.scrollHeight-1))return;
            }
            event.preventDefault();window.chrome.webview.postMessage(token+Math.max(-2500,Math.min(2500,delta)));
        },{capture:true,passive:false});})())JS";
    view->web->ExecuteScript(script.c_str(),nullptr);
}

// ==========================================
// Function: Create a controller only after the shared Edge environment is ready.
// Method: Disable document scripts and external navigation before loading sanitized mail.
// ==========================================
static void create_controller(const std::shared_ptr<View>& view){
    if(view->closed||!environment)return;
    // ==========================================
    // Function: Handle the native done completion or event.
    // Method: Preserve current view ownership and validate asynchronous state before dispatch.
    // ==========================================
    auto done=new Handler<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler,HRESULT,ICoreWebView2Controller*>([view](HRESULT result,ICoreWebView2Controller* controller){
        if(pending_controllers)--pending_controllers;view->result=result;if(view->closed){if(controller){ICoreWebView2* late=nullptr;controller->get_CoreWebView2(&late);track_browser(late);if(late)late->Release();last_close_result=controller->Close();++close_count;if(FAILED(last_close_result))++close_failures;}return S_OK;}
        if(FAILED(result)||!controller){view->error=L"WebView2 controller initialization failed";return S_OK;}
        view->controller=controller;controller->AddRef();controller->get_CoreWebView2(&view->web);
        if(!view->web){view->result=E_FAIL;return S_OK;}
        track_browser(view->web);
        ICoreWebView2Settings* settings=nullptr;view->web->get_Settings(&settings);
        if(settings){settings->put_AreDefaultContextMenusEnabled(FALSE);settings->put_IsScriptEnabled(TRUE);settings->put_IsWebMessageEnabled(TRUE);settings->put_AreDevToolsEnabled(FALSE);settings->put_AreHostObjectsAllowed(FALSE);settings->put_IsStatusBarEnabled(FALSE);
            ICoreWebView2Settings3* accelerators=nullptr;
            if(SUCCEEDED(settings->QueryInterface(__uuidof(ICoreWebView2Settings3),reinterpret_cast<void**>(&accelerators)))){accelerators->put_AreBrowserAcceleratorKeysEnabled(FALSE);accelerators->Release();}
            settings->Release();}
        // ==========================================
        // Function: Handle the native navigate completion or event.
        // Method: Preserve current view ownership and validate asynchronous state before dispatch.
        // ==========================================
        auto navigate=new Handler<ICoreWebView2NavigationStartingEventHandler,ICoreWebView2*,ICoreWebView2NavigationStartingEventArgs*>([view](ICoreWebView2*,ICoreWebView2NavigationStartingEventArgs* args){
            LPWSTR uri=nullptr;BOOL user=FALSE;args->get_Uri(&uri);args->get_IsUserInitiated(&user);std::wstring target=uri?uri:L"";CoTaskMemFree(uri);
            bool local=target==L"about:blank"||target==view->origin||target.rfind(view->origin+L"#mail-image-",0)==0;
            bool internal=target.rfind(L"https://maildesk.invalid/",0)==0;
            if(!local){args->put_Cancel(TRUE);if(!internal&&user&&(target.rfind(L"https:",0)==0||target.rfind(L"http:",0)==0||target.rfind(L"mailto:",0)==0))view->link=target;}
            else if(target==view->origin){args->get_NavigationId(&view->navigation_id);view->ready=false;}
            return S_OK;
        });
        view->web->add_NavigationStarting(navigate,&view->nav_token);navigate->Release();
        // ==========================================
        // Function: Handle the native completed completion or event.
        // Method: Preserve current view ownership and validate asynchronous state before dispatch.
        // ==========================================
        auto completed=new Handler<ICoreWebView2NavigationCompletedEventHandler,ICoreWebView2*,ICoreWebView2NavigationCompletedEventArgs*>([view](ICoreWebView2*,ICoreWebView2NavigationCompletedEventArgs* args){
            BOOL success=FALSE;UINT64 id=0;args->get_IsSuccess(&success);args->get_NavigationId(&id);
            if(!view->closed&&view->navigation_id&&id==view->navigation_id){
                if(success)reveal_document(view);
                else if(!view->ready)view->result=E_FAIL;
            }return S_OK;
        });view->web->add_NavigationCompleted(completed,&view->complete_token);completed->Release();
        // ==========================================
        // Function: Reveal the current document before delayed images finish, rejecting stale navigation events.
        // Method: Use WebView2's DOMContentLoaded navigation ID and retain the registration for explicit close cleanup.
        // ==========================================
        if(SUCCEEDED(view->web->QueryInterface(__uuidof(ICoreWebView2_2),reinterpret_cast<void**>(&view->dom_web)))){
            auto dom=new Handler<ICoreWebView2DOMContentLoadedEventHandler,ICoreWebView2*,ICoreWebView2DOMContentLoadedEventArgs*>([view](ICoreWebView2*,ICoreWebView2DOMContentLoadedEventArgs* args){
                UINT64 id=0;args->get_NavigationId(&id);
                if(!view->closed&&view->navigation_id&&id==view->navigation_id)reveal_document(view);
                return S_OK;
            });view->dom_web->add_DOMContentLoaded(dom,&view->dom_token);dom->Release();
        }
        // ==========================================
        // Function: Handle the native popup completion or event.
        // Method: Preserve current view ownership and validate asynchronous state before dispatch.
        // ==========================================
        auto popup=new Handler<ICoreWebView2NewWindowRequestedEventHandler,ICoreWebView2*,ICoreWebView2NewWindowRequestedEventArgs*>([view](ICoreWebView2*,ICoreWebView2NewWindowRequestedEventArgs* args){
            args->put_Handled(TRUE);LPWSTR uri=nullptr;BOOL user=FALSE;args->get_IsUserInitiated(&user);args->get_Uri(&uri);std::wstring target=uri?uri:L"";CoTaskMemFree(uri);
            if(target.rfind(L"https://maildesk.invalid/",0)!=0&&user&&(target.rfind(L"https:",0)==0||target.rfind(L"http:",0)==0||target.rfind(L"mailto:",0)==0))view->link=target;return S_OK;
        });view->web->add_NewWindowRequested(popup,&view->popup_token);popup->Release();
        // ==========================================
        // Function: Handle the native shortcut completion or event.
        // Method: Preserve current view ownership and validate asynchronous state before dispatch.
        // ==========================================
        auto shortcut=new Handler<ICoreWebView2AcceleratorKeyPressedEventHandler,ICoreWebView2Controller*,ICoreWebView2AcceleratorKeyPressedEventArgs*>([view](ICoreWebView2Controller*,ICoreWebView2AcceleratorKeyPressedEventArgs* args){
            COREWEBVIEW2_KEY_EVENT_KIND kind;args->get_KeyEventKind(&kind);
            if(kind!=COREWEBVIEW2_KEY_EVENT_KIND_KEY_DOWN&&kind!=COREWEBVIEW2_KEY_EVENT_KIND_SYSTEM_KEY_DOWN)return S_OK;
            UINT key=0;args->get_VirtualKey(&key);bool control=(GetKeyState(VK_CONTROL)&0x8000)!=0;bool shift=(GetKeyState(VK_SHIFT)&0x8000)!=0;
            if(key==VK_ESCAPE||(control&&(key=='N'||key=='F'||key=='R'||key=='A'||key==VK_OEM_COMMA))){
                args->put_Handled(TRUE);if(view->keys.size()<32)view->keys.push_back(key|(control?0x10000:0)|(shift?0x20000:0));
            }return S_OK;
        });controller->add_AcceleratorKeyPressed(shortcut,&view->key_token);shortcut->Release();
        // ==========================================
        // Function: Relay only trusted boundary wheel input from the current inert mail document.
        // Method: Validate origin, generation, exact string shape and finite bounded numeric delta.
        // ==========================================
        auto wheel=new Handler<ICoreWebView2WebMessageReceivedEventHandler,ICoreWebView2*,ICoreWebView2WebMessageReceivedEventArgs*>([view](ICoreWebView2*,ICoreWebView2WebMessageReceivedEventArgs* args){
            if(view->closed||!view->ready)return S_OK;
            LPWSTR source=nullptr,message=nullptr;args->get_Source(&source);std::wstring origin=source?source:L"";CoTaskMemFree(source);
            if(origin!=view->origin&&origin.rfind(view->origin+L"#mail-image-",0)!=0)return S_OK;
            if(FAILED(args->TryGetWebMessageAsString(&message))||!message){CoTaskMemFree(message);return S_OK;}
            std::wstring payload=message;CoTaskMemFree(message);
            if(payload==L"maildesk-click:"+std::to_wstring(view->generation)+L":"){if(view->keys.size()<32)view->keys.push_back(0x40000);return S_OK;}
            std::wstring prefix=L"maildesk-wheel:"+std::to_wstring(view->generation)+L":";
            if(payload.size()>100||payload.rfind(prefix,0)!=0)return S_OK;
            const wchar_t* start=payload.c_str()+prefix.size();wchar_t* end=nullptr;double delta=wcstod(start,&end);
            if(end==start||*end||!std::isfinite(delta)||std::abs(delta)>2500)return S_OK;
            view->wheel=std::clamp(view->wheel+delta,-10000.0,10000.0);return S_OK;
        });view->web->add_WebMessageReceived(wheel,&view->wheel_token);wheel->Release();
        view->web->AddWebResourceRequestedFilter(L"*",COREWEBVIEW2_WEB_RESOURCE_CONTEXT_ALL);
        // ==========================================
        // Function: Handle the native resource completion or event.
        // Method: Preserve current view ownership and validate asynchronous state before dispatch.
        // ==========================================
        auto resource=new Handler<ICoreWebView2WebResourceRequestedEventHandler,ICoreWebView2*,ICoreWebView2WebResourceRequestedEventArgs*>([view](ICoreWebView2*,ICoreWebView2WebResourceRequestedEventArgs* args){
            ICoreWebView2WebResourceRequest* request=nullptr;args->get_Request(&request);LPWSTR uri=nullptr;if(request){request->get_Uri(&uri);request->Release();}
            std::wstring target=uri?uri:L"";CoTaskMemFree(uri);
            if(!view->pdf_prefix.empty()){
                // ==========================================
                // Function: Admit only the trusted PDF viewer's capability-scoped local resources.
                // Method: Block every other network/file origin without relaxing inert mail policy.
                // ==========================================
                std::wstring blob_prefix=L"blob:"+view->pdf_prefix.substr(0,view->pdf_prefix.find(L'/',7))+L"/";
                if(target.rfind(view->pdf_prefix,0)==0||target.rfind(blob_prefix,0)==0||target.rfind(L"data:",0)==0)return S_OK;
                if(environment){ICoreWebView2WebResourceResponse* response=nullptr;environment->CreateWebResourceResponse(nullptr,403,L"Blocked",L"Content-Type: text/plain",&response);if(response){args->put_Response(response);response->Release();}}
                return S_OK;
            }
            if(target==view->origin&&environment){
                size_t size=view->pending.size();
                HGLOBAL bytes=GlobalAlloc(GMEM_MOVEABLE,std::max<size_t>(1,size));if(!bytes)return E_OUTOFMEMORY;void* buffer=GlobalLock(bytes);
                if(!buffer){GlobalFree(bytes);return E_OUTOFMEMORY;}if(size)std::memcpy(buffer,view->pending.data(),size);GlobalUnlock(bytes);
                IStream* stream=nullptr;HRESULT hr=CreateStreamOnHGlobal(bytes,TRUE,&stream);if(FAILED(hr)){GlobalFree(bytes);return hr;}
                ULARGE_INTEGER exact{};exact.QuadPart=size;hr=stream->SetSize(exact);if(FAILED(hr)){stream->Release();return hr;}
                // ==========================================
                // Function: Deny executable mail content independently of document-controlled markup.
                // Method: Enforce HTTP CSP while enabling only privileged host API input callbacks.
                // ==========================================
                std::wstring policy=L"default-src 'none'; script-src 'none'; connect-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'; style-src 'unsafe-inline'; font-src 'none'; media-src data:; img-src data:";
                if(view->remote)policy+=L" https: http:";
                std::wstring headers=L"Content-Type: text/html; charset=utf-8\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nReferrer-Policy: no-referrer\r\nContent-Security-Policy: "+policy;
                ICoreWebView2WebResourceResponse* response=nullptr;environment->CreateWebResourceResponse(stream,200,L"OK",headers.c_str(),&response);
                stream->Release();if(response){args->put_Response(response);response->Release();}return S_OK;
            }
            COREWEBVIEW2_WEB_RESOURCE_CONTEXT context=COREWEBVIEW2_WEB_RESOURCE_CONTEXT_ALL;args->get_ResourceContext(&context);
            bool allowed=target==L"about:blank"||target.rfind(L"data:",0)==0||(view->remote&&context==COREWEBVIEW2_WEB_RESOURCE_CONTEXT_IMAGE&&(target.rfind(L"https:",0)==0||target.rfind(L"http:",0)==0));
            if(!allowed&&environment){ICoreWebView2WebResourceResponse* response=nullptr;environment->CreateWebResourceResponse(nullptr,403,L"Blocked",L"Content-Type: text/plain",&response);if(response){args->put_Response(response);response->Release();}}return S_OK;
        });view->web->add_WebResourceRequested(resource,&view->resource_token);resource->Release();
        ICoreWebView2Controller2* background=nullptr;
        if(SUCCEEDED(controller->QueryInterface(__uuidof(ICoreWebView2Controller2),reinterpret_cast<void**>(&background)))){
            COREWEBVIEW2_COLOR color{255,39,41,44};background->put_DefaultBackgroundColor(color);background->Release();
        }
        // ==========================================
        // Function: Handle the native permission completion or event.
        // Method: Preserve current view ownership and validate asynchronous state before dispatch.
        // ==========================================
        auto permission=new Handler<ICoreWebView2PermissionRequestedEventHandler,ICoreWebView2*,ICoreWebView2PermissionRequestedEventArgs*>([](ICoreWebView2*,ICoreWebView2PermissionRequestedEventArgs* args){args->put_State(COREWEBVIEW2_PERMISSION_STATE_DENY);return S_OK;});
        view->web->add_PermissionRequested(permission,&view->permission_token);permission->Release();
        ICoreWebView2_4* downloads=nullptr;
        if(SUCCEEDED(view->web->QueryInterface(__uuidof(ICoreWebView2_4),reinterpret_cast<void**>(&downloads)))){
            // ==========================================
            // Function: Handle the native refuse completion or event.
            // Method: Preserve current view ownership and validate asynchronous state before dispatch.
            // ==========================================
            auto refuse=new Handler<ICoreWebView2DownloadStartingEventHandler,ICoreWebView2*,ICoreWebView2DownloadStartingEventArgs*>([](ICoreWebView2*,ICoreWebView2DownloadStartingEventArgs* args){args->put_Cancel(TRUE);args->put_Handled(TRUE);return S_OK;});
            downloads->add_DownloadStarting(refuse,&view->download_token);refuse->Release();downloads->Release();
        }
        controller->put_ZoomFactor(view->zoom);resize(view);
        if(!view->pending.empty()||!view->pdf_prefix.empty())view->web->Navigate(view->origin.c_str());
        return S_OK;
    });
    ICoreWebView2Environment10* private_environment=nullptr;
    HRESULT result=environment->QueryInterface(__uuidof(ICoreWebView2Environment10),reinterpret_cast<void**>(&private_environment));
    if(SUCCEEDED(result)){
        ICoreWebView2ControllerOptions* options=nullptr;result=private_environment->CreateCoreWebView2ControllerOptions(&options);
        if(SUCCEEDED(result)&&options){
            result=options->put_IsInPrivateModeEnabled(TRUE);
            if(SUCCEEDED(result)){++pending_controllers;result=private_environment->CreateCoreWebView2ControllerWithOptions(view->parent,options,done);if(FAILED(result)&&pending_controllers)--pending_controllers;}
            options->Release();
        }
        private_environment->Release();
    }
    done->Release();if(FAILED(result))view->result=result;
}

// ==========================================
// Function: Initialize one native HTML reader without starting a second browser environment.
// Method: Use the official loader DLL and the installed evergreen Windows runtime.
// ==========================================
extern "C" __declspec(dllexport) void* md_webview_create(HWND parent,const wchar_t* profile,const wchar_t* loader){
    views.erase(std::remove_if(views.begin(),views.end(),[](const std::weak_ptr<View>& old){return old.expired();}),views.end());
    auto view=std::make_shared<View>();views.push_back(view);view->root=parent;view->parent=CreateWindowExW(WS_EX_NOPARENTNOTIFY,L"STATIC",L"",WS_CHILD|WS_CLIPSIBLINGS|WS_CLIPCHILDREN,0,0,1,1,parent,nullptr,GetModuleHandleW(nullptr),nullptr);view->origin=L"https://maildesk.invalid/reader/"+std::to_wstring(++document_serial);auto handle=new Handle{view};
    if(!view->parent){view->result=HRESULT_FROM_WIN32(GetLastError());return handle;}
    if(shutting_down){view->result=E_ABORT;return handle;}
    if(!com_initialized){HRESULT initialized=CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED);if(FAILED(initialized)){view->result=initialized;return handle;}com_initialized=true;}
    if(environment){create_controller(view);return handle;}
    waiting.push_back(view);if(environment_pending)return handle;environment_pending=true;
    if(!loader_module)loader_module=LoadLibraryW(loader);auto create=loader_module?reinterpret_cast<CreateEnvironment>(GetProcAddress(loader_module,"CreateCoreWebView2EnvironmentWithOptions")):nullptr;
    if(!create){view->result=HRESULT_FROM_WIN32(GetLastError());view->error=L"WebView2Loader.dll is unavailable";environment_pending=false;return handle;}
    // ==========================================
    // Function: Handle the native ready completion or event.
    // Method: Preserve current view ownership and validate asynchronous state before dispatch.
    // ==========================================
    auto ready=new Handler<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler,HRESULT,ICoreWebView2Environment*>([](HRESULT result,ICoreWebView2Environment* value){
        environment_pending=false;if(shutting_down)return S_OK;if(SUCCEEDED(result)&&value){
            environment=value;environment->AddRef();
            if(SUCCEEDED(environment->QueryInterface(__uuidof(ICoreWebView2Environment5),reinterpret_cast<void**>(&environment_events)))){
                // ==========================================
                // Function: Observe completed browser cleanup while its environment remains owned.
                // Method: Record the SDK-reported process ID after runtime resources/UDF handles release.
                // ==========================================
                auto exited=new Handler<ICoreWebView2BrowserProcessExitedEventHandler,ICoreWebView2Environment*,ICoreWebView2BrowserProcessExitedEventArgs*>([](ICoreWebView2Environment*,ICoreWebView2BrowserProcessExitedEventArgs* args){
                    UINT32 pid=0;if(SUCCEEDED(args->get_BrowserProcessId(&pid)))exited_browsers.push_back(pid);return S_OK;
                });environment_events->add_BrowserProcessExited(exited,&browser_exit_token);exited->Release();
            }
        }
        auto queued=std::move(waiting);waiting.clear();for(auto& weak:queued)if(auto current=weak.lock()){
            if(environment)create_controller(current);else {current->result=result;current->error=L"Microsoft Edge WebView2 Runtime is required";}
        }return S_OK;
    });HRESULT result=create(nullptr,profile,nullptr,ready);ready->Release();if(FAILED(result)){view->result=result;environment_pending=false;}
    return handle;
}

// ==========================================
// Function: Load an inert prepared document while retaining pending asynchronous state.
// Method: The Python caller sanitizes markup; native settings and resource events enforce policy.
// ==========================================
extern "C" __declspec(dllexport) void md_webview_load(void* pointer,const wchar_t* html,int remote){
    auto view=static_cast<Handle*>(pointer)->value;if(view->closed)return;
    int length=html?static_cast<int>(wcslen(html)):0;
    int bytes=length?WideCharToMultiByte(CP_UTF8,0,html,length,nullptr,0,nullptr,nullptr):0;
    if(length&&!bytes){view->result=HRESULT_FROM_WIN32(GetLastError());return;}
    view->pending.resize(bytes);if(bytes)WideCharToMultiByte(CP_UTF8,0,html,length,view->pending.data(),bytes,nullptr,nullptr);
    view->pdf_prefix.clear();view->origin=L"https://maildesk.invalid/reader/"+std::to_wstring(++document_serial);view->remote=remote!=0;view->ready=false;view->navigation_id=0;view->link.clear();view->keys.clear();view->wheel=0;view->query_ready=false;view->query_result.clear();++view->generation;
    if(view->web){view->result=S_OK;view->error.clear();HRESULT result=view->web->Navigate(view->origin.c_str());if(FAILED(result))view->result=result;}
}
// ==========================================
// Function: Navigate a dedicated PDF surface to its private loopback resource capability.
// Method: Accept only a numeric loopback port, 48 hex token and exact viewer filename.
// ==========================================
extern "C" __declspec(dllexport) int md_webview_open_pdf(void* pointer,const wchar_t* address){
    if(!pointer||!address)return 0;auto view=static_cast<Handle*>(pointer)->value;if(view->closed)return 0;
    std::wstring url=address,prefix=L"http://127.0.0.1:";if(url.size()>160||url.rfind(prefix,0)!=0)return 0;
    size_t slash=url.find(L'/',prefix.size());if(slash==std::wstring::npos)return 0;
    std::wstring port=url.substr(prefix.size(),slash-prefix.size());if(port.empty()||port.size()>5||port.find_first_not_of(L"0123456789")!=std::wstring::npos)return 0;
    unsigned number=static_cast<unsigned>(wcstoul(port.c_str(),nullptr,10));if(!number||number>65535)return 0;
    std::wstring path=url.substr(slash);if(path.size()!=61||path.substr(49)!=L"/viewer.html"||path.substr(1,48).find_first_not_of(L"0123456789abcdef")!=std::wstring::npos)return 0;
    view->pdf_prefix=url.substr(0,slash+50);view->origin=url;view->pending.clear();view->remote=false;
    view->ready=false;view->navigation_id=0;view->query_ready=false;view->query_result.clear();view->keys.clear();view->link.clear();view->wheel=0;++view->generation;
    if(view->web){view->result=S_OK;view->error.clear();view->result=view->web->Navigate(url.c_str());}
    return 1;
}
// ==========================================
// Function: Read bounded PDF metadata without using the host's asynchronous diagnostic query slot.
// Method: Copy the native document title and release the COM allocation immediately.
// ==========================================
extern "C" __declspec(dllexport) int md_webview_title(void* pointer,wchar_t* output,int capacity){
    if(!pointer||!output||capacity<2)return 0;auto view=static_cast<Handle*>(pointer)->value;
    if(view->closed||!view->web)return 0;LPWSTR title=nullptr;if(FAILED(view->web->get_DocumentTitle(&title))||!title)return 0;
    size_t size=wcslen(title);if(size>=static_cast<size_t>(capacity)){CoTaskMemFree(title);return 0;}
    std::wmemcpy(output,title,size+1);CoTaskMemFree(title);return 1;
}
// ==========================================
// Function: Apply GTK allocation and visibility to the browser controller.
// Method: Read the current native child window on every allocation or map transition.
// ==========================================
extern "C" __declspec(dllexport) void md_webview_resize(void* pointer,int visible){auto view=static_cast<Handle*>(pointer)->value;view->visible=visible!=0;resize(view);}
// ==========================================
// Function: Stage GTK logical placement without introducing an intermediate native repaint.
// Method: The following viewport call commits placement, clipping and overlay exclusion together.
// ==========================================
extern "C" __declspec(dllexport) void md_webview_position(void* pointer,int x,int y,int width,int height,int root_width,int root_height){
    auto view=static_cast<Handle*>(pointer)->value;if(view->closed)return;
    view->logical_box={x,y,width,height};view->root_width=root_width;view->root_height=root_height;
}
// ==========================================
// Function: Keep a floating GTK control visible and reachable above the browser surface.
// Method: Subtract its circular footprint from the independently owned browser window region.
// ==========================================
extern "C" __declspec(dllexport) void md_webview_overlay(void* pointer,int left,int top,int right,int bottom){
    auto view=static_cast<Handle*>(pointer)->value;if(!view->closed)view->logical_cut={left,top,right,bottom};
}
// ==========================================
// Function: Stage the complete higher GTK surface coverage before committing reader geometry.
// Method: Copy a bounded list of logical exclusion rectangles; zero count restores unobstructed content.
// ==========================================
extern "C" __declspec(dllexport) void md_webview_exclusions(void* pointer,const int* rectangles,int count){
    auto view=static_cast<Handle*>(pointer)->value;if(view->closed||count<0||count>128||(!rectangles&&count))return;
    view->logical_exclusions.clear();view->logical_exclusions.reserve(count);
    for(int i=0;i<count;++i){const int* area=rectangles+i*4;view->logical_exclusions.push_back({area[0],area[1],area[2],area[3]});}
}
// ==========================================
// Function: Expose only this reader's owned HWND for native geometry and input diagnostics.
// Method: Return a borrowed handle, never transfer or enumerate unrelated windows.
// ==========================================
extern "C" __declspec(dllexport) HWND md_webview_window(void* pointer){return static_cast<Handle*>(pointer)->value->parent;}
// ==========================================
// Function: Preserve each browser's actual visible portion when GTK repositions native siblings.
// Method: Accept logical host/viewport intersection only; convert against the exact HWND client dimensions.
// ==========================================
extern "C" __declspec(dllexport) void md_webview_viewport(void* pointer,int left,int top,int right,int bottom,int width,int height,int visible){
    auto view=static_cast<Handle*>(pointer)->value;if(view->closed)return;
    view->logical_width=std::max(0,width);view->logical_height=std::max(0,height);
    left=std::clamp(left,0,view->logical_width);top=std::clamp(top,0,view->logical_height);
    view->logical_clip={left,top,std::clamp(right,left,view->logical_width),std::clamp(bottom,top,view->logical_height)};
    view->visible=visible!=0;resize(view);
}
// ==========================================
// Function: Query browser readiness or a native initialization failure.
// Method: Return zero while asynchronous, one when loaded, or a failing HRESULT.
// ==========================================
extern "C" __declspec(dllexport) int md_webview_status(void* pointer){auto view=static_cast<Handle*>(pointer)->value;return FAILED(view->result)&&view->result!=E_PENDING?static_cast<int>(view->result):(view->ready?1:0);}
// ==========================================
// Function: Transfer one user-requested safe link to the application's URI handler.
// Method: Copy into a caller-owned buffer and clear exactly once.
// ==========================================
extern "C" __declspec(dllexport) int md_webview_link(void* pointer,wchar_t* output,int count){auto view=static_cast<Handle*>(pointer)->value;if(view->link.empty()||count<2)return 0;wcsncpy_s(output,count,view->link.c_str(),_TRUNCATE);view->link.clear();return 1;}
// ==========================================
// Function: Consume bounded unhandled wheel input from one reader on the GTK main loop.
// Method: Transfer the accumulated numeric delta once without exposing native commands to HTML.
// ==========================================
extern "C" __declspec(dllexport) double md_webview_wheel(void* pointer){auto view=static_cast<Handle*>(pointer)->value;double delta=view->wheel;view->wheel=0;return delta;}
// ==========================================
// Function: Scale a browser document without rerendering original MIME input.
// Method: Keep the documented controller zoom within the UI's bounded range.
// ==========================================
extern "C" __declspec(dllexport) void md_webview_zoom(void* pointer,double factor){auto view=static_cast<Handle*>(pointer)->value;view->zoom=factor;if(view->controller)view->controller->put_ZoomFactor(factor);}
// ==========================================
// Function: Run a trusted reader-only operation while document scripts remain disabled.
// Method: Host ExecuteScript is fixed by the application; untrusted mail scripts never execute.
// ==========================================
extern "C" __declspec(dllexport) void md_webview_script(void* pointer,const wchar_t* script){auto view=static_cast<Handle*>(pointer)->value;if(!view->closed&&view->web)view->web->ExecuteScript(script,nullptr);}
// ==========================================
// Function: Close a controller and break all event-handler ownership cycles.
// Method: Close releases WebView event registrations before dropping the handle owner.
// ==========================================
extern "C" __declspec(dllexport) void md_webview_close(void* pointer){
    if(!pointer)return;auto handle=static_cast<Handle*>(pointer);auto view=handle->value;view->closed=true;if(view->parent)ShowWindow(view->parent,SW_HIDE);
    if(view->dom_web){view->dom_web->remove_DOMContentLoaded(view->dom_token);view->dom_web->Release();view->dom_web=nullptr;}
    if(view->web){
        view->web->remove_NavigationStarting(view->nav_token);view->web->remove_NavigationCompleted(view->complete_token);
        view->web->remove_WebMessageReceived(view->wheel_token);
        view->web->remove_NewWindowRequested(view->popup_token);view->web->remove_WebResourceRequested(view->resource_token);view->web->remove_PermissionRequested(view->permission_token);
        ICoreWebView2_4* downloads=nullptr;
        if(SUCCEEDED(view->web->QueryInterface(__uuidof(ICoreWebView2_4),reinterpret_cast<void**>(&downloads)))){downloads->remove_DownloadStarting(view->download_token);downloads->Release();}
    }
    if(view->controller){view->controller->remove_AcceleratorKeyPressed(view->key_token);last_close_result=view->controller->Close();++close_count;if(FAILED(last_close_result))++close_failures;last_controller_refs=view->controller->Release();view->controller=nullptr;}
    if(view->web){last_web_refs=view->web->Release();view->web=nullptr;}delete handle;
}
// ==========================================
// Function: Begin browser shutdown after its final controller closes.
// Method: Release environment references after controllers settle, retaining owned process handles until drained.
// ==========================================
extern "C" __declspec(dllexport) void md_webview_shutdown(){
    shutting_down=true;waiting.clear();
    if(environment_pending||pending_controllers)return;
    for(auto& weak:views)if(auto view=weak.lock())if(view->controller)return;
    if(environment_events){environment_events->remove_BrowserProcessExited(browser_exit_token);environment_events->Release();environment_events=nullptr;}
    if(environment){last_environment_refs=environment->Release();environment=nullptr;}
}
// ==========================================
// Function: Observe only verified owned WebView2 browser process handles during shutdown.
// Method: Poll signaled handles without blocking GTK or terminating unrelated Edge processes.
// ==========================================
extern "C" __declspec(dllexport) int md_webview_drained(){
    if(environment_pending||pending_controllers)return 0;
    for(HANDLE process:browser_processes){
        if(WaitForSingleObject(process,0)==WAIT_TIMEOUT)return 0;
        if(environment_events&&std::find(exited_browsers.begin(),exited_browsers.end(),GetProcessId(process))==exited_browsers.end())return 0;
    }
    return 1;
}
// ==========================================
// Function: Complete apartment cleanup after the GTK shutdown grace period.
// Method: Release process handles, the loader, and the single owned COM initialization.
// ==========================================
extern "C" __declspec(dllexport) void md_webview_finish(){
    if(environment_events){environment_events->remove_BrowserProcessExited(browser_exit_token);environment_events->Release();environment_events=nullptr;}
    if(environment){last_environment_refs=environment->Release();environment=nullptr;}
    for(HANDLE process:browser_processes)CloseHandle(process);browser_processes.clear();
    if(loader_module&&!environment_pending){FreeLibrary(loader_module);loader_module=nullptr;}
    if(com_initialized){CoUninitialize();com_initialized=false;}
}

// ==========================================
// Function: Inspect synthetic reader DOM state through a host-owned asynchronous operation.
// Method: Sequence results against document generation and ignore stale or closed callbacks.
// ==========================================
extern "C" __declspec(dllexport) unsigned md_webview_query(void* pointer,const wchar_t* script){
    auto view=static_cast<Handle*>(pointer)->value;unsigned id=++view->query_id;unsigned generation=view->generation;
    view->query_ready=false;view->query_result.clear();if(view->closed||!view->web)return 0;
    // ==========================================
    // Function: Handle the native callback completion or event.
    // Method: Preserve current view ownership and validate asynchronous state before dispatch.
    // ==========================================
    auto callback=new Handler<ICoreWebView2ExecuteScriptCompletedHandler,HRESULT,LPCWSTR>([view,id,generation](HRESULT result,LPCWSTR json){
        if(!view->closed&&id==view->query_id&&generation==view->generation){view->query_result=SUCCEEDED(result)&&json?json:L"null";view->query_ready=true;}return S_OK;
    });HRESULT result=view->web->ExecuteScript(script,callback);callback->Release();return SUCCEEDED(result)?id:0;
}
// ==========================================
// Function: Return only the requested current diagnostic result to a caller-owned buffer.
// Method: Keep asynchronous JSON bounded by the destination size and consume exactly once.
// ==========================================
extern "C" __declspec(dllexport) int md_webview_result(void* pointer,unsigned id,wchar_t* output,int count){
    auto view=static_cast<Handle*>(pointer)->value;if(view->closed||id!=view->query_id)return -1;if(!view->query_ready)return 0;
    if(count<=static_cast<int>(view->query_result.size()))return -2;
    wcscpy_s(output,count,view->query_result.c_str());view->query_ready=false;view->query_result.clear();return 1;
}
// ==========================================
// Function: Read the current native document URI or title without evaluating mail content.
// Method: Copy COM-owned strings into the caller buffer before CoTaskMemFree.
// ==========================================
extern "C" __declspec(dllexport) int md_webview_info(void* pointer,int title,wchar_t* output,int count){
    auto view=static_cast<Handle*>(pointer)->value;if(view->closed||!view->web||count<2)return 0;LPWSTR text=nullptr;
    HRESULT result=title?view->web->get_DocumentTitle(&text):view->web->get_Source(&text);
    if(FAILED(result)||!text)return 0;wcsncpy_s(output,count,text,_TRUNCATE);CoTaskMemFree(text);return 1;
}

// ==========================================
// Function: Forward application shortcuts from an embedded browser to the GTK controller.
// Method: Transfer bounded key/modifier values while preserving native copy and text selection.
// ==========================================
extern "C" __declspec(dllexport) unsigned md_webview_key(void* pointer){auto view=static_cast<Handle*>(pointer)->value;if(view->keys.empty())return 0;unsigned key=view->keys.front();view->keys.erase(view->keys.begin());return key;}

// ==========================================
// Function: Inspect actual native controller ownership during synthetic lifecycle acceptance.
// Method: Count live weak owners or pending creation without keeping retired mail views alive.
// ==========================================
extern "C" __declspec(dllexport) unsigned md_webview_metrics(int field){
    if(field==1)return pending_controllers;if(field==2)return environment_pending?1:0;
    if(field==5)return static_cast<unsigned>(exited_browsers.size());
    if(field==6)return static_cast<unsigned>(last_close_result);if(field==7)return close_count;
    if(field==8)return last_controller_refs;if(field==9)return last_web_refs;if(field==10)return last_environment_refs;
    if(field==11){unsigned alive=0;for(auto& weak:views)if(!weak.expired())++alive;return alive;}
    if(field==12)return close_failures;if(field==13)return surface_moves;if(field==14)return surface_regions;
    if(field==4){size_t bytes=0;for(auto& weak:views)if(auto view=weak.lock())bytes+=view->pending.capacity()*sizeof(char);return static_cast<unsigned>(std::min<size_t>(bytes,0xffffffffu));}
    if(field==3){unsigned alive=0;for(HANDLE process:browser_processes)if(WaitForSingleObject(process,0)==WAIT_TIMEOUT)++alive;return alive;}
    unsigned count=0;for(auto& weak:views)if(auto view=weak.lock())if(!view->closed&&view->controller)++count;return count;
}
