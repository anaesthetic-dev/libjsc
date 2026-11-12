"""Build the JSCOnly shared C API and assemble a development SDK."""
import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile


PUBLIC_API_HEADERS = (
    'JavaScript.h',
    'JSBase.h',
    'JSContextRef.h',
    'JSObjectRef.h',
    'JSStringRef.h',
    'JSTypedArray.h',
    'JSValueRef.h',
    'WebKitAvailability.h',
)

SHIM_C_SOURCE = """\
#include <stdbool.h>
#include <stdlib.h>

#if defined(_MSC_VER)
#define JSC_ALIGN(n) __declspec(align(n))
#else
#define JSC_ALIGN(n) __attribute__((aligned(n)))
#endif

JSC_ALIGN(16) unsigned char Bun__removableFeatureState[536] = {0};

void Bun__throwForRemovedFeature(void) { abort(); }
void Bun__throwForRemovedFunction(void) { abort(); }
void Bun__abortForRemovedFeature(void) { abort(); }
void Bun__didFinishFirstCollectionOfCompiledProgram(void) {}

#if defined(_WIN32)
typedef struct mi_theap_s mi_theap_t;
extern mi_theap_t* mi_theap_get_default(void);
extern void mi_theap_collect(mi_theap_t* theap, bool force);

void mi_on_thread_idle(void) {
    mi_theap_collect(mi_theap_get_default(), false);
}
#endif
"""



def run(*args):
    print('+', ' '.join(str(a) for a in args), flush=True)
    subprocess.run([str(arg) for arg in args], check=True)


@dataclass(frozen=True, order=True)
class ApiExport:
    name: str
    is_data: bool = False


def extract_c_api_exports(api_dir: Path) -> list[ApiExport]:
    """Collect public functions and extern data, preserving their export kind."""
    comment_re = re.compile(r'/\*.*?\*/|//[^\n]*', re.DOTALL)
    function_re = re.compile(
        r'JS_EXPORT\s+(?:(?!;).)*?\b(JS[A-Z][A-Za-z0-9_]*)\s*\(',
        re.DOTALL,
    )
    # Public data declarations do not have a function parameter list and need
    # not start with JS (notably kJSClassDefinitionEmpty in JSObjectRef.h).
    data_re = re.compile(
        r'JS_EXPORT\s+extern\s+[^;()]+?\b([A-Za-z_][A-Za-z0-9_]*)\s*;',
    )
    exports = set()
    for name in PUBLIC_API_HEADERS:
        header = api_dir / name
        if not header.is_file():
            continue
        text = comment_re.sub('', header.read_text(encoding='utf-8', errors='replace'))
        for match in function_re.finditer(text):
            exports.add(ApiExport(match.group(1)))
        for match in data_re.finditer(text):
            exports.add(ApiExport(match.group(1), is_data=True))
    if not exports:
        raise RuntimeError('No JS_EXPORT symbols found in API headers')
    return sorted(exports)


def patch_js_global_context_release(source: Path) -> None:
    """Ensure JSGlobalContextRelease holds JSLockHolder before releasing the VM."""
    ctx_cpp = source / 'Source/JavaScriptCore/API/JSContextRef.cpp'
    text = ctx_cpp.read_text(encoding='utf-8')
    target = 'void JSGlobalContextRelease(JSGlobalContextRef ctx)\n{'
    if target in text and 'JSLockHolder locker(' not in text.split(target, 1)[1][:350]:
        replacement = (
            'void JSGlobalContextRelease(JSGlobalContextRef ctx)\n{\n'
            '    if (!ctx)\n        return;\n'
            '    JSLockHolder locker(toJS(ctx));'
        )
        text = text.replace(target, replacement, 1)
        ctx_cpp.write_text(text, encoding='utf-8')
        print('Patched JSGlobalContextRelease with JSLockHolder in JSContextRef.cpp')


def neutralize_windows_declspec_in_internal_macros(source: Path) -> None:
    """Prevent internal WTF_EXPORT_PRIVATE / JS_EXPORT_PRIVATE from expanding to
    __declspec(dllimport/dllexport) on Windows static & generator targets.
    Public C-API symbols are exported via JavaScriptCore.def at link time.
    """
    export_macros = source / 'Source/WTF/wtf/ExportMacros.h'
    text = export_macros.read_text(encoding='utf-8')
    text = text.replace('#define WTF_EXPORT_DECLARATION __declspec(dllexport)',
                        '#define WTF_EXPORT_DECLARATION')
    text = text.replace('#define WTF_IMPORT_DECLARATION __declspec(dllimport)',
                        '#define WTF_IMPORT_DECLARATION')
    export_macros.write_text(text, encoding='utf-8')


def ensure_windows_mimalloc(source: Path, build: Path, jobs: int) -> Path:
    existing = list(build.rglob('mimalloc*.lib'))
    if existing:
        return existing[0]
    mi_src = source / 'Source/bmalloc/mimalloc/mimalloc'
    mi_build = build / 'mimalloc-md'
    run(
        'cmake', '-S', mi_src, '-B', mi_build, '-G', 'Ninja',
        '-DCMAKE_BUILD_TYPE=Release',
        '-DCMAKE_C_COMPILER=clang-cl',
        '-DCMAKE_CXX_COMPILER=clang-cl',
        '-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreadedDLL',
        '-DMI_OVERRIDE=OFF',
        '-DMI_BUILD_SHARED=OFF',
        '-DMI_BUILD_STATIC=ON',
        '-DMI_BUILD_OBJECT=OFF',
        '-DMI_BUILD_TESTS=OFF',
    )
    run('cmake', '--build', mi_build, '--config', 'Release', '--parallel', jobs)
    built = list(mi_build.rglob('mimalloc*.lib'))
    if not built:
        raise RuntimeError('Failed to build mimalloc static library on Windows')
    return built[0]


def link_shared_library(
    windows: bool,
    source: Path,
    build: Path,
    sdk: Path,
    icu: Path | None,
    exports: list[ApiExport],
    jobs: int,
) -> None:
    shim_c = build / 'shim.c'
    shim_c.write_text(SHIM_C_SOURCE, encoding='utf-8')

    if windows:
        shim_obj = build / 'shim.obj'
        run('clang-cl', '/MD', '/O2', '/c', shim_c, f'/Fo{shim_obj}')

        def_file = build / 'JavaScriptCore.def'
        # DATA is required for the import library to describe variables rather
        # than generate function thunks for them.
        def_lines = ['LIBRARY JavaScriptCore', 'EXPORTS'] + [
            f'    {symbol.name}' + (' DATA' if symbol.is_data else '')
            for symbol in exports
        ]
        def_file.write_text('\n'.join(def_lines) + '\n', encoding='ascii')

        mimalloc_lib = ensure_windows_mimalloc(source, build, jobs)
        lib_dir = build / 'lib'
        static_libs = [
            lib_dir / 'JavaScriptCore.lib',
            lib_dir / 'WTF.lib',
            lib_dir / 'bmalloc.lib',
            mimalloc_lib,
        ]
        for i, lib in enumerate(static_libs):
            if not lib.is_file():
                found = list(build.rglob(lib.name))
                if not found:
                    raise RuntimeError(f'Missing static library: {lib.name}')
                static_libs[i] = found[0]

        icu_libs = sorted((icu / 'lib').glob('icu*.lib'))
        if not icu_libs:
            raise RuntimeError(f'No ICU .lib files found in {icu / "lib"}')

        dll_out = sdk / 'bin/JavaScriptCore.dll'
        imp_out = sdk / 'lib/JavaScriptCore.lib'
        sys_libs = [
            'winmm.lib', 'ws2_32.lib', 'dbghelp.lib', 'advapi32.lib',
            'user32.lib', 'shell32.lib', 'ole32.lib', 'oleaut32.lib',
            'uuid.lib', 'bcrypt.lib', 'ntdll.lib', 'synchronization.lib',
        ]
        run(
            'lld-link', '/DLL',
            f'/DEF:{def_file}',
            f'/OUT:{dll_out}',
            f'/IMPLIB:{imp_out}',
            '/MACHINE:X64', '/NOLOGO', '/INCREMENTAL:NO', '/OPT:REF', '/OPT:ICF',
            shim_obj, *static_libs, *icu_libs, *sys_libs,
        )
    else:
        shim_o = build / 'shim.o'
        run('clang-21', '-fPIC', '-O2', '-c', shim_c, '-o', shim_o)

        ver_file = build / 'JavaScriptCore.map'
        ver_lines = ['{', '  global:'] + [f'    {symbol.name};' for symbol in exports] + ['  local:', '    *;', '};']
        ver_file.write_text('\n'.join(ver_lines) + '\n', encoding='ascii')

        lib_dir = build / 'lib'
        static_libs = [
            lib_dir / 'libJavaScriptCore.a',
            lib_dir / 'libWTF.a',
            lib_dir / 'libbmalloc.a',
        ]
        for i, lib in enumerate(static_libs):
            if not lib.is_file():
                found = list(build.rglob(lib.name))
                if not found:
                    raise RuntimeError(f'Missing static archive: {lib.name}')
                static_libs[i] = found[0]

        so_out = sdk / 'lib/libJavaScriptCore.so'
        u_flags = [f'-Wl,-u,{symbol.name}' for symbol in exports]
        run(
            'clang++-21', '-shared', '-fuse-ld=lld',
            '-o', so_out,
            f'-Wl,--version-script={ver_file}',
            '-Wl,-soname,libJavaScriptCore.so',
            '-Wl,--gc-sections',
            *u_flags,
            '-Wl,--start-group',
            shim_o, *static_libs,
            '-Wl,--end-group',
            '-licui18n', '-licuuc', '-licudata',
            '-lpthread', '-ldl', '-lm', '-latomic', '-lstdc++', '-lgcc_s',
        )


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--source', type=Path, default=Path('webkit'))
    parser.add_argument('--platform', required=True)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = args.source.resolve()
    windows = platform.system() == 'Windows'
    if platform.machine().lower() not in ('amd64', 'x86_64'):
        raise RuntimeError('This SDK currently targets x64 only')
    if not re.fullmatch(r'[a-z0-9.-]+', args.platform):
        raise ValueError('Invalid platform name')
    build = root / 'build' / args.platform
    sdk = root / 'dist' / f'javascriptcore-{args.platform}'
    if sdk.exists():
        raise RuntimeError(f'Use a fresh package directory: {sdk}')
    revision = subprocess.check_output(
        ['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()

    schema_lists = source / 'Source/JavaScriptCore/aot/ir/AOTSchemaFiles.cmake'
    if b'\r\n' in schema_lists.read_bytes():
        raise RuntimeError('WebKit requires LF line endings. Clone it with '
                           'git -c core.autocrlf=false clone https://github.com/oven-sh/WebKit.git webkit')

    patch_js_global_context_release(source)

    if windows:
        neutralize_windows_declspec_in_internal_macros(source)
        options = source / 'Source/cmake/OptionsMSVC.cmake'
        original = options.read_text(encoding='utf-8')
        patched = re.sub(r'MultiThreadedDebug(?!DLL)', 'MultiThreadedDebugDLL', original)
        patched = re.sub(r'MultiThreaded(?!Debug|DLL)', 'MultiThreadedDLL', patched)
        if patched != original:
            options.write_text(patched, encoding='utf-8')

    flags = [
        '-DPORT=JSCOnly',
        '-DCMAKE_BUILD_TYPE=Release',
        '-DENABLE_STATIC_JSC=ON',
        '-DENABLE_FTL_JIT=ON',
        '-DUSE_BUN_JSC_ADDITIONS=ON',
        '-DUSE_BUN_EVENT_LOOP=ON',
        '-DENABLE_REMOTE_INSPECTOR=OFF',
        '-DENABLE_JSC_GLIB_API=OFF',
        '-DENABLE_API_TESTS=OFF',
        '-DCMAKE_POSITION_INDEPENDENT_CODE=ON',
        '-DENABLE_LTO=OFF',
        '-DUSE_THIN_ARCHIVES=OFF',
    ]
    icu = None
    if windows:
        icu = Path(os.environ['ICU_ROOT']).resolve()
        flags += [
            '-DCMAKE_C_COMPILER=clang-cl',
            '-DCMAKE_CXX_COMPILER=clang-cl',
            '-DUSE_SYSTEM_MALLOC=OFF',
            '-DUSE_MIMALLOC=ON',
            '-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreadedDLL',
            '-DCMAKE_C_FLAGS=-DJS_NO_EXPORT -DENABLE_AOT=0 -DU_STATIC_IMPLEMENTATION=1',
            '-DCMAKE_CXX_FLAGS=-DJS_NO_EXPORT -DENABLE_AOT=0 -DU_STATIC_IMPLEMENTATION=1',
            f'-DICU_ROOT={icu}',
        ]
    else:
        flags += [
            '-DCMAKE_C_COMPILER=clang-21',
            '-DCMAKE_CXX_COMPILER=clang++-21',
            '-DUSE_SYSTEM_MALLOC=ON',
            '-DUSE_MIMALLOC=OFF',
            '-DCMAKE_C_FLAGS=-DENABLE_AOT=0 -fPIC -ftls-model=global-dynamic',
            '-DCMAKE_CXX_FLAGS=-DENABLE_AOT=0 -fPIC -ftls-model=global-dynamic',
        ]

    run('cmake', '-S', source, '-B', build, '-G', 'Ninja', *flags)
    run('cmake', '--build', build, '--target', 'LLIntSettingsExtractor',
        'LLIntOffsetsExtractor', '--parallel', args.jobs)
    run('cmake', '--build', build, '--target', 'JavaScriptCore', '--parallel', args.jobs)

    for directory in ('include/JavaScriptCore', 'lib', 'bin', 'licenses'):
        (sdk / directory).mkdir(parents=True, exist_ok=True)

    api_dir = source / 'Source/JavaScriptCore/API'
    for header_name in PUBLIC_API_HEADERS:
        header_path = api_dir / header_name
        if header_path.is_file():
            shutil.copy2(header_path, sdk / 'include/JavaScriptCore' / header_name)
        else:
            found = list(build.rglob(header_name))
            if found:
                shutil.copy2(found[0], sdk / 'include/JavaScriptCore' / header_name)

    if not (sdk / 'include/JavaScriptCore/JavaScript.h').is_file():
        raise RuntimeError('JavaScriptCore API headers missing')

    exports = extract_c_api_exports(sdk / 'include/JavaScriptCore')
    link_shared_library(windows, source, build, sdk, icu, exports, args.jobs)

    # No se copian las DLL de ICU.
    if windows and (icu / 'share/icu').is_dir():
        shutil.copytree(icu / 'share/icu', sdk / 'licenses/icu')

    for directory in (source, source / 'Source/JavaScriptCore', source / 'Source/WTF',
                      source / 'Source/bmalloc'):
        for pattern in ('LICENSE*', 'COPYING*'):
            for license_file in directory.glob(pattern):
                if license_file.is_file():
                    shutil.copy2(license_file, sdk / 'licenses' /
                                 f'{directory.name}-{license_file.name}')

    config = sdk / 'lib/cmake/JavaScriptCore'
    config.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / 'cmake/JavaScriptCoreConfig.cmake', config)
    shutil.copytree(root / 'examples', sdk / 'examples')
    shutil.copy2(root / 'README.md', sdk)
    (sdk / 'build-info.json').write_text(json.dumps({
        'repository': 'https://github.com/oven-sh/WebKit',
        'commit': revision,
        'platform': args.platform,
        'linkage': 'shared',
        'configuration': 'Release',
        'bun_additions': True,
        'system_malloc': not windows,
        'allocator': 'mimalloc' if windows else 'system',
        'runtime': '/MD' if windows else 'glibc, system ICU (Ubuntu 24.04)',
        'cmake_options': flags,
        'exported_symbols': len(exports),
    }, indent=2) + '\n', encoding='utf-8')

    if windows:
        archive = Path(shutil.make_archive(str(sdk), 'zip', root_dir=sdk))
    else:
        archive = sdk.with_suffix(sdk.suffix + '.tar.gz')
        with tarfile.open(archive, 'w:gz') as tar:
            tar.add(sdk, arcname='.')

    with archive.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    Path(str(archive) + '.sha256').write_text(
        f'{checksum}  {archive.name}\n', encoding='ascii')
    print(f'SDK: {archive}')


if __name__ == '__main__':
    main()
