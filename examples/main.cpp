#include <JavaScriptCore/JavaScript.h>
#include <cstdio>

static constexpr char smokeTest[] = R"JS(
    (() => {
        function check(condition, name) {
            if (!condition) throw new Error(name);
        }

        function sum(limit) {
            let result = 0;
            for (let i = 0; i < limit; ++i) result += i;
            return result;
        }
        for (let i = 0; i < 100000; ++i) {
            const limit = 64 + (i & 7);
            check(sum(limit) === limit * (limit - 1) / 2, "Hot JS loop");
        }

        const wasm = new Uint8Array([
            0x00, 0x61, 0x73, 0x6d, 1, 0, 0, 0, // Header
            1, 7, 1, 0x60, 2, 0x7f, 0x7f, 1, 0x7f, // (i32, i32) -> i32
            3, 2, 1, 0, // Function
            7, 7, 1, 3, 0x61, 0x64, 0x64, 0, 0, // Export "add"
            10, 9, 1, 7, 0, 0x20, 0, 0x20, 1, 0x6a, 0x0b // local.get, local.get, i32.add, end
        ]);
        const instance = new WebAssembly.Instance(new WebAssembly.Module(wasm));
        check(instance.exports.add(20, 22) === 42, "Wasm add");

        check(new Intl.NumberFormat("en-US").format(12345.67) === "12,345.67", "en-US format");
        check(new Intl.NumberFormat("es-ES").format(12345.67) === "12.345,67", "es-ES format");
        check(new Intl.DateTimeFormat("en-US", { timeZone: "UTC" }).format(new Date(0))
              === "1/1/1970", "UTC date format");
        check("\u00e1\u00e9\u00ed\u00f3\u00fa".normalize("NFD") === "a\u0301e\u0301i\u0301o\u0301u\u0301",
              "Unicode NFD");
        check(/\p{Letter}+/u.test("Hola"), "Unicode property escape");
        check(new Intl.NumberFormat("zu-ZA").format(42).length > 0, "zu-ZA format");
        return new Float32Array([1.5, -2.25, 42]);
    })()
)JS";

int main()
{
    JSGlobalContextRef context = JSGlobalContextCreate(nullptr);
    JSStringRef script = JSStringCreateWithUTF8CString(smokeTest);
    JSValueRef exception = nullptr;
    JSValueRef value = JSEvaluateScript(context, script, nullptr, nullptr, 1, &exception);
    JSStringRelease(script);

    bool passed = false;
    JSObjectRef array = value && !exception ? JSValueToObject(context, value, &exception) : nullptr;
    if (array && !exception && JSObjectGetTypedArrayLength(context, array, &exception) == 3 && !exception) {
        const auto* bytes = static_cast<const float*>(JSObjectGetTypedArrayBytesPtr(context, array, &exception));
        passed = bytes && !exception && bytes[0] == 1.5f && bytes[1] == -2.25f && bytes[2] == 42.0f;
    }

    if (exception) {
        JSStringRef message = JSValueToStringCopy(context, exception, nullptr);
        if (message) {
            char text[256];
            JSStringGetUTF8CString(message, text, sizeof(text));
            std::fprintf(stderr, "%s\n", text);
            JSStringRelease(message);
        }
    } else if (!passed) {
        std::fprintf(stderr, "Float32Array C API check failed\n");
    }
    JSGlobalContextRelease(context);
    if (passed)
        std::puts("JavaScript, Wasm, Intl, Unicode, and Float32Array checks passed");
    return passed ? 0 : 1;
}
