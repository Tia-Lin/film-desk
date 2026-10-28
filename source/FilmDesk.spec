# Build from this directory with: python -m PyInstaller --noconfirm FilmDesk.spec
from pathlib import Path
root=Path(SPECPATH).resolve()
a=Analysis([str(root/'app.py')],pathex=[str(root)],
    datas=[(str(root/'assets'),'assets'),(str(root.parent/'licenses'),'licenses'),
           (str(root.parent/'README.md'),'.'),(str(root.parent/'INSTALL.md'),'.'),(str(root.parent/'INSTALL.zh-CN.md'),'.'),(str(root.parent/'README.zh-CN.md'),'.'),
           (str(root.parent/'SUPPORTED_CAMERAS.md'),'.'),(str(root.parent/'SUPPORTED_CAMERAS.zh-CN.md'),'.'),(str(root.parent/'THIRD-PARTY-NOTICES.txt'),'.')],
    hiddenimports=[],excludes=['tkinter','PySide6.QtNetwork','PySide6.QtQml',
    'PySide6.QtQuick','PySide6.QtOpenGL','PySide6.QtPdf','PySide6.QtSql','PySide6.QtTest'],
    noarchive=False,optimize=0)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='Film Desk',console=False,
    disable_windowed_traceback=False,argv_emulation=False,
    target_arch='arm64',codesign_identity=None,
    icon=str(root/'assets/FilmDesk.icns'))
coll=COLLECT(exe,a.binaries,a.datas,name='Film Desk')
app=BUNDLE(coll,name='Film Desk.app',icon=str(root/'assets/FilmDesk.icns'),
    bundle_identifier='local.filmdesk.app',version='1.5.0',
    info_plist={
        'CFBundleVersion':'1.5.0','LSMinimumSystemVersion':'26.0',
        'NSHumanReadableCopyright':'Film Desk 2026. MIT license; third-party notices included.',
        'CFBundleDocumentTypes':[{'CFBundleTypeName':'Film Desk session',
            'CFBundleTypeRole':'Editor','LSHandlerRank':'Alternate',
            'LSItemContentTypes':['local.filmdesk.session'],
            'CFBundleTypeExtensions':['filmdesk']}],
        'UTExportedTypeDeclarations':[{'UTTypeIdentifier':'local.filmdesk.session',
            'UTTypeDescription':'Film Desk session','UTTypeConformsTo':['public.json'],
            'UTTypeTagSpecification':{'public.filename-extension':['filmdesk']}}],
    })
