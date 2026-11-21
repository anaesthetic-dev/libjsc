"""Generate a vcpkg ICU overlay using filtered data from the same ICU release."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
from urllib.request import urlretrieve
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]


def prepare(vcpkg: Path, overlay: Path) -> Path:
    source = vcpkg / 'ports/icu'
    port = overlay / 'icu'
    if port.resolve() == source.resolve():
        raise ValueError('The overlay directory must be separate from the original vcpkg ports')
    portfile = (source / 'portfile.cmake').read_text(encoding='utf-8')
    manifest = json.loads((source / 'vcpkg.json').read_text(encoding='utf-8'))
    version = next(manifest[key] for key in ('version', 'version-string', 'version-semver')
                   if key in manifest)
    archive_url = re.search(
        r'https://github\.com/unicode-org/icu/releases/download/[^\s"/]+/'
        r'icu4c-[^\s"/]+-(?:sources|src)\.tgz', portfile,
    )
    if not archive_url:
        raise ValueError('Cannot find the ICU source release URL in the vcpkg port')
    versions = {'VERSION': version}
    # Older ports rewrite the version with hyphens for the tag and underscores
    # for the asset. Follow those substitutions before changing the suffix.
    for old, new, variable in re.findall(
        r'string\(REPLACE\s+"([^"]*)"\s+"([^"]*)"\s+(\w+)\s+"\$\{VERSION\}"\)',
        portfile,
    ):
        versions[variable] = version.replace(old, new)
    source_url = re.sub(r'\$\{(\w+)\}', lambda match: versions.get(match[1], match[0]), archive_url[0])
    if '${' in source_url:
        raise ValueError(f'Cannot resolve the ICU release URL: {source_url}')
    tag_url, source_asset = source_url.rsplit('/', 1)
    asset = re.sub(r'-(?:sources|src)\.tgz$', '-data.zip', source_asset)
    extract = re.search(r'^vcpkg_extract_source_archive\((?:[^\n]*\)[ \t]*$|.*?^\))',
                        portfile, re.MULTILINE | re.DOTALL)
    configure = re.search(
        r'^vcpkg_(?:make_configure|configure_make)\([^\n]*\n.*?^\)',
        portfile, re.MULTILINE | re.DOTALL,
    )
    options = re.search(r'^([ \t]+)OPTIONS[ \t]*$', configure[0], re.MULTILINE) if configure else None
    if not extract or not options or extract.end() > configure.start():
        raise ValueError('Cannot find ICU source extraction and configure options in the vcpkg port')

    overlay.mkdir(parents=True, exist_ok=True)
    downloads = overlay.parent / 'icu-downloads'
    downloads.mkdir(exist_ok=True)
    archive = downloads / asset
    if not archive.is_file():
        with TemporaryDirectory(dir=downloads) as temporary:
            download = Path(temporary) / asset
            print(f'Downloading {tag_url}/{asset}', flush=True)
            urlretrieve(f'{tag_url}/{asset}', download)
            with ZipFile(download) as data:
                data.getinfo('data/locales/root.txt')
            download.replace(archive)
    with archive.open('rb') as data:
        digest = hashlib.file_digest(data, 'sha512').hexdigest()

    # Paths based on CMAKE_CURRENT_LIST_DIR are absolute, slash-separated and
    # keep the generated port's ABI hash independent of the workspace path.
    extract_data = f'''

set(icu_data_archive "${{CMAKE_CURRENT_LIST_DIR}}/../../icu-downloads/{asset}")
file(SHA512 "${{icu_data_archive}}" icu_data_sha512)
if(NOT icu_data_sha512 STREQUAL "{digest}")
    message(FATAL_ERROR "ICU data sources archive changed: ${{icu_data_archive}}")
endif()
file(REMOVE_RECURSE "${{SOURCE_PATH}}/source/data/in")
file(ARCHIVE_EXTRACT INPUT "${{icu_data_archive}}" DESTINATION "${{SOURCE_PATH}}/source")
file(GLOB icu_prebuilt_data "${{SOURCE_PATH}}/source/data/in/*.dat")
if(icu_prebuilt_data OR NOT EXISTS "${{SOURCE_PATH}}/source/data/locales/root.txt")
    message(FATAL_ERROR "Expected ICU data sources without a prebuilt .dat")
endif()
'''
    disabled = ('icuio', 'layoutex', 'extras', 'samples', 'tests')
    missing = ''.join(f'\n{options[1]}    --disable-{name}' for name in disabled
                      if not re.search(rf'^\s*--disable-{name}(?:\s|$)', configure[0], re.MULTILINE))
    position = configure.start() + options.end()
    portfile = portfile[:position] + missing + portfile[position:]
    portfile = portfile[:configure.start()] + '''# Native data builds need genrb and the other ICU generators.
if(NOT VCPKG_CROSSCOMPILING)
    list(REMOVE_ITEM CONFIGURE_OPTIONS --disable-tools --enable-tools)
    list(APPEND CONFIGURE_OPTIONS --enable-tools)
endif()
set(ENV{ICU_DATA_FILTER_FILE} "${CMAKE_CURRENT_LIST_DIR}/filters.json")

''' + portfile[configure.start():]
    portfile = portfile[:extract.end()] + extract_data + portfile[extract.end():]

    if port.exists():
        shutil.rmtree(port)
    shutil.copytree(source, port)
    shutil.copyfile(ROOT / 'icu/filters.json', port / 'filters.json')
    (port / 'portfile.cmake').write_text(portfile, encoding='utf-8', newline='\n')
    return overlay


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vcpkg-root', type=Path, default=os.environ.get('VCPKG_INSTALLATION_ROOT'))
    parser.add_argument('--output', type=Path, default=ROOT / 'build/overlay-ports')
    args = parser.parse_args()
    if args.vcpkg_root is None:
        parser.error('set VCPKG_INSTALLATION_ROOT or pass --vcpkg-root')
    print(f'ICU overlay: {prepare(args.vcpkg_root.resolve(), args.output.resolve())}')


if __name__ == '__main__':
    main()
