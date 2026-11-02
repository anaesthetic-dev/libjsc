#include <JavaScriptCore/JavaScript.h>
#include <cstdio>

int main()
{
    JSGlobalContextRef context = JSGlobalContextCreate(nullptr);
    JSStringRef script = JSStringCreateWithUTF8CString("21 * 2");
    JSValueRef exception = nullptr;
    JSValueRef value = JSEvaluateScript(context, script, nullptr, nullptr, 1, &exception);
    int status = 1;
    if (value && !exception) {
        double result = JSValueToNumber(context, value, &exception);
        if (!exception) {
            std::printf("%.0f\n", result);
            status = result == 42 ? 0 : 1;
        }
    }
    JSStringRelease(script);
    JSGlobalContextRelease(context);
    return status;
}
