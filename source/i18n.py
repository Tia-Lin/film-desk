"""English/Simplified Chinese presentation; processing values stay language-neutral."""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path
from PySide6.QtCore import QLocale, QTranslator, QObject
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QComboBox, QCheckBox
from PySide6.QtGui import QAction

LANGUAGES=('en','zh_CN')
_language='en'
_root=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
_catalog=json.loads((_root/'assets/translations-zh_CN.json').read_text(encoding='utf-8'))
_patterns=[]
for source,target in _catalog.items():
    if re.search(r'\{p\d+(?::[^}]+)?\}',source):
        parts=re.split(r'(\{p\d+(?::[^}]+)?\})',source)
        keys=[];pattern=''
        for part in parts:
            if part.startswith('{p'):
                key=part[1:].split(':',1)[0].rstrip('}');keys.append(key)
                pattern+='(.+?)'
            else:pattern+=re.escape(part)
        _patterns.append((re.compile('^'+pattern+'$',re.DOTALL),keys,target))


def language(): return _language


def tr(source,**values):
    if not isinstance(source,str): source=str(source)
    text=source
    if _language=='zh_CN':
        text=_catalog.get(source,source)
        if text==source and not values:
            for pattern,keys,target in _patterns:
                match=pattern.fullmatch(source)
                if match:
                    try:
                        captured=dict(zip(keys,match.groups()))
                        text=re.sub(r'\{(p\d+)(?::[^}]+)?\}',lambda m:captured[m[1]],target)
                    except (KeyError,ValueError,TypeError):pass
                    break
            if text==source and '\n' in source:
                text='\n'.join(tr(line) for line in source.split('\n'))
    if values:
        values=dict(values)
        if source=='{p0} output selected for the roll. Individual adjustments and crops are preserved.':
            values['p0']=tr(values['p0'])
        elif source=='{p0} / {p1} · {p2} · {p3}':
            values['p3']=tr(values['p3'])
        return text.format(**values)
    return text


class StandardTranslator(QTranslator):
    def translate(self,context,source,disambiguation=None,n=-1):
        if _language!='zh_CN':return ''
        # Qt's standard dialog buttons. Native macOS file pickers use OS language.
        return {'OK':'确定','&OK':'确定','Cancel':'取消','&Cancel':'取消',
                'Close':'关闭','&Close':'关闭','Save':'保存','&Save':'保存',
                'Open':'打开','&Open':'打开','Yes':'是','&Yes':'是',
                'No':'否','&No':'否','Apply':'应用','Reset':'重置'}.get(source,'')


def set_language(code):
    global _language
    _language=code if code in LANGUAGES else 'en'
    app=QApplication.instance()
    if app is not None:
        translator=getattr(app,'_film_desk_translator',None)
        if translator is None:
            translator=StandardTranslator(app);app._film_desk_translator=translator
        else:app.removeTranslator(translator)
        app.installTranslator(translator)


def default_language():
    return 'zh_CN' if QLocale.system().name().lower().startswith('zh') else 'en'


def bind(widget,property,source,**values):
    bindings=getattr(widget,'_film_desk_i18n',{})
    bindings[property]=(source,values)
    widget._film_desk_i18n=bindings
    getattr(widget,'set'+property[0].upper()+property[1:])(tr(source,**values))
    return widget


def text(widget,source,**values): return bind(widget,'text',source,**values)
def tooltip(widget,source,**values): return bind(widget,'toolTip',source,**values)
def title(widget,source,**values): return bind(widget,'windowTitle',source,**values)


def plain_text(widget,value):
    getattr(widget,'_film_desk_i18n',{}).pop('text',None)
    widget.setText(value)


def plain_tooltip(widget,value):
    getattr(widget,'_film_desk_i18n',{}).pop('toolTip',None)
    widget.setToolTip(value)


def label(source='',**values): return text(QLabel(),source,**values)
def button(source,**values): return text(QPushButton(),source,**values)
def checkbox(source,**values): return text(QCheckBox(),source,**values)
def action(source,parent): return text(QAction(parent),source)
def menu(bar,source): return bind(bar.addMenu(''),'title',source)


def combo_item(combo,source,data):
    combo.addItem(tr(source),data)
    items=getattr(combo,'_film_desk_combo_i18n',{})
    items[combo.count()-1]=source;combo._film_desk_combo_i18n=items


def retranslate(window):
    for widget in [window]+window.findChildren(QObject):
        blocked=widget.blockSignals(True)
        try:
            for property,(source,values) in getattr(widget,'_film_desk_i18n',{}).items():
                getattr(widget,'set'+property[0].upper()+property[1:])(tr(source,**values))
            if isinstance(widget,QComboBox):
                for index,source in getattr(widget,'_film_desk_combo_i18n',{}).items():
                    widget.setItemText(index,tr(source))
        finally:widget.blockSignals(blocked)
