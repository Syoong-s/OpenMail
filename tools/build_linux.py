"""Build Linux amd64 ELF, relocatable tarball and Debian desktop package."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parent.parent
VERSION = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", (ROOT/'maildesk/__init__.py').read_text())[1]

# ==========================================
# Function: Build native Linux release artifacts without installing dependencies.
# Method: Compile the ELF entry point, stage Linux modules and generate tar/deb packages.
# ==========================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cc', default=os.environ.get('CC','cc'))
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        parser.error('Build requires Linux amd64')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    bundle, staging = output / 'TeleMail-Linux-amd64', ROOT / '.runtime/build-linux'
    for folder in (staging,bundle):
        if folder.exists():
            shutil.rmtree(folder)
    staging.mkdir(parents=True)
    package = bundle / 'app/maildesk'
    package.mkdir(parents=True)
    # Keep compiler-prefix RPATH injection out of the relocatable ELF.
    specs = subprocess.run([args.cc,'-dumpspecs'],check=True,capture_output=True,text=True).stdout
    match = re.search(r'(?ms)^\*link_command:\n(.*?)(?=\n\n|\Z)',specs)
    if not match:
        raise RuntimeError('Build requires a GCC-compatible specs interface')
    command = re.sub(r'%\{!static:-rpath [^}]+\}', '', match.group(1))
    local_specs = staging/'portable-link.specs'
    local_specs.write_text('*link_command:\n'+command.strip()+'\n')
    subprocess.run([args.cc,'-specs='+str(local_specs),'-O2','-Wall','-Wextra','-Werror','-fstack-protector-strong','-D_FORTIFY_SOURCE=2','-Wl,-z,relro,-z,now',str(ROOT / 'native/launcher.c'),'-o',str(bundle / 'TeleMail')], check=True)
    (bundle / 'TeleMail').chmod(0o755)
    dynamic = subprocess.run(['readelf','-d',str(bundle/'TeleMail')],check=True,capture_output=True,text=True).stdout
    if '(RPATH)' in dynamic or '(RUNPATH)' in dynamic:
        raise RuntimeError('Refusing release ELF with compiler-specific RPATH')
    # Include every application module and static resource, excluding interpreter caches.
    shutil.copytree(ROOT / 'maildesk', package, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    from release_assets import copy_release_documents
    copy_release_documents(bundle)
    shutil.copy2(ROOT / 'README.md', bundle / 'README.md')
    manifest = {'name':'TeleMail','version':VERSION,'application_license':'MIT','os':'linux','architecture':'amd64',
        'entrypoint':'TeleMail','ui':'native GTK 3','python':'>=3.12','gtk':'>=3.24','glibc':'>=2.34',
        'browser_required':False,'http_server_required':False,
        'account_signin':'native-provider-wizard-with-imap-smtp-verification-and-explicit-confirmation',
        'oauth_browser_optional':True,'oauth_requires_own_client_registration':True,'oauth_pkce':True,'oauth_refresh':True,
        'provider_templates':['gmail','outlook','microsoft365','other'],
        'application_cloud_required':False,'account_free_local_folders':True,'inbox_modes':['focused','smart','classic'],
        'reply_surface':'source-anchored-conversation-bubble','history_navigation':'continuous-all-local-headers-per-card-disclosure','quoted_history':'conservative-nested-rich-local-disclosure','collapsed_body_loading':'lazy','account_scope':'native-pill-popover','source_header_details':True,'collapsed_mail_snippets':True,'local_draft_status':True,
        'composer_ui':'modern-native','single_buffer_editor_expansion':True,
        'document_runtime_dependencies':['libwebkit2gtk-4.1.so.0'],
        'pdf_engine':'PDF.js 6.4.299 (offline legacy browser build)',
        'internal_pdf_resource_transport':'app-owned loopback capability; no external server',
        'reader_runtime_bundled':False,'file_preview':'embedded-right-panel','inline_mail_images':True,
        'sender_background_colors':True,'account_outline_colors':True,'navigation_rail_px':40,'compact_attachment_footer':True,'settings_navigation':True,'settings_icons':True,'send_later_calendar':True,'gatekeeper_modes':['explicit','inThread','off'],'embedded_composer':True,'local_mdn_receipts':True,'template_variables':True,'general_appearance_settings':True,'focused_sender_summaries':True,'row_quick_actions':['done','seen','trash'],'continuous_conversation_cards':True,'inline_reply':True,'full_compose':True,'credential_storage':'local AES-256-GCM with private device key',
        'sha256':{str(p.relative_to(bundle)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(bundle.rglob('*')) if p.is_file()}}
    (bundle / 'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    for directory, dirs, files in os.walk(bundle):
        Path(directory).chmod(0o755)
        for name in files:
            (Path(directory) / name).chmod(0o755 if name == 'TeleMail' else 0o644)
    tarball = output / f'telemail-{VERSION}-linux-amd64.tar.gz'
    with tarfile.open(tarball, 'w:gz') as archive:
        archive.add(bundle, arcname=bundle.name)
    debroot = staging / 'deb'
    opt = debroot / 'opt/telemail'
    shutil.copytree(bundle, opt)
    desktop = debroot / 'usr/share/applications'
    desktop.mkdir(parents=True)
    shutil.copy2(ROOT / 'packaging/org.telemail.Desktop.desktop', desktop)
    icons = debroot / 'usr/share/icons/hicolor/scalable/apps'
    icons.mkdir(parents=True)
    shutil.copy2(ROOT / 'maildesk/desktop_assets/icon.svg', icons / 'org.telemail.Desktop.svg')
    bindir = debroot / 'usr/bin'
    bindir.mkdir(parents=True)
    (bindir / 'telemail').symlink_to('/opt/telemail/TeleMail')
    control = debroot / 'DEBIAN'
    control.mkdir()
    (control / 'control').write_text(f'''Package: telemail-desktop
Version: {VERSION}
Section: mail
Priority: optional
Architecture: amd64
Maintainer: TeleMail Project <maintainer@example.invalid>
Depends: libc6 (>= 2.34), python3 (>= 3.12), libgtk-3-0 (>= 3.24) | libgtk-3-0t64 (>= 3.24), librsvg2-common, libfontconfig1, libssl3 | libssl3t64, libwebkit2gtk-4.1-0
Description: Native Linux desktop mail client
 IMAP/SMTP email with native GTK windows, classification and local drafts.
Installed-Size: {sum(p.stat().st_size for p in opt.rglob('*') if p.is_file()) // 1024}
''')
    deb = output / f'telemail-desktop_{VERSION}_amd64.deb'
    subprocess.run(['dpkg-deb','--root-owner-group','--build',str(debroot),str(deb)], check=True)
    sums = output / 'SHA256SUMS-linux-amd64'
    sums.write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n' for p in (tarball,deb)))
    print(json.dumps({'bundle':str(bundle),'tarball':str(tarball),'deb':str(deb),'checksums':str(sums)},indent=2))

if __name__ == '__main__':
    main()
