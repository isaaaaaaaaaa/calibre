#!/usr/bin/env python


__license__   = 'GPL v3'
__copyright__ = '2010, Kovid Goyal <kovid@kovidgoyal.net>'
__docformat__ = 'restructuredtext en'

import textwrap

from qt.core import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QEvent,
    QIcon,
    QLineEdit,
    QListView,
    QListWidget,
    Qt,
    QTableWidget,
    QVBoxLayout,
    QWidget,
    pyqtSignal,
)

from calibre.customize.ui import preferences_plugins
from calibre.gui2.complete2 import EditWithComplete
from calibre.gui2.widgets import HistoryLineEdit
from calibre.utils.config import ConfigProxy
from polyglot.builtins import string_or_bytes


class AbortCommit(Exception):
    pass


class AbortInitialize(Exception):
    pass


class ConfigWidgetInterface:
    '''
    This class defines the interface that all widgets displayed in the
    Preferences dialog must implement. See :class:`ConfigWidgetBase` for
    a base class that implements this interface and defines various convenience
    methods as well.
    '''

    #: This signal must be emitted whenever the user changes a value in this
    #: widget
    changed_signal = None

    #: Set to True iff the :meth:`restore_to_defaults` method is implemented.
    supports_restoring_to_defaults = True

    #: The tooltip for the "Restore defaults" button
    restore_defaults_desc = _('Restore settings to default values. '
            'You have to click Apply to actually save the default settings.')

    #: If True the Preferences dialog will not allow the user to set any more
    #: preferences. Only has effect if :meth:`commit` returns True.
    restart_critical = False

    def genesis(self, gui):
        '''
        Called once before the widget is displayed, should perform any
        necessary setup.

        :param gui: The main calibre graphical user interface
        '''
        raise NotImplementedError()

    def initialize(self):
        '''
        Should set all config values to their initial values (the values
        stored in the config files). A "return" statement is optional. Return
        False if the dialog is not to be shown.
        '''
        raise NotImplementedError()

    def restore_defaults(self):
        '''
        Should set all config values to their defaults.
        '''
        pass

    def commit(self):
        '''
        Save any changed settings. Return True if the changes require a
        restart, False otherwise. Raise an :class:`AbortCommit` exception
        to indicate that an error occurred. You are responsible for giving the
        user feedback about what the error is and how to correct it.
        '''
        return False

    def refresh_gui(self, gui):
        '''
        Called once after this widget is committed. Responsible for causing the
        gui to reread any changed settings. Note that by default the GUI
        re-initializes various elements anyway, so most widgets won't need to
        use this method.
        '''
        pass

    def initial_tab_changed(self):
        '''
        Called if the initially displayed tab is changed before the widget is shown, but after it is initialized.
        '''
        pass

    def do_on_child_tabs(self, method, *args):
        r = False
        for t in self.child_tabs:
            lazy_init_called = getattr(t, 'lazy_init_called', True)
            if method in ('commit', 'refresh_gui') and not lazy_init_called:
                continue
            if method == 'restore_defaults' and not lazy_init_called:
                if hasattr(t, 'lazy_initialize'):
                    t.lazy_initialize()
                    t.lazy_init_called = True
            r = r | bool(getattr(t, method)(*args))
        return r


def set_help_tips(gui_obj, tt):
    if tt:
        if not str(gui_obj.whatsThis()):
            gui_obj.setWhatsThis(tt)
        if not str(gui_obj.statusTip()):
            gui_obj.setStatusTip(tt)
        tt = '\n'.join(textwrap.wrap(tt, 70))
        gui_obj.setToolTip(tt)


class Setting:

    CHOICES_SEARCH_FLAGS = Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchCaseSensitive

    def __init__(self, name, config_obj, widget, gui_name=None,
            empty_string_is_None=True, choices=None, restart_required=False):
        self.name, self.gui_name = name, gui_name
        self.empty_string_is_None = empty_string_is_None
        self.restart_required = restart_required
        self.choices = choices
        if gui_name is None:
            self.gui_name = 'opt_'+name
        self.config_obj = config_obj
        self.gui_obj = getattr(widget, self.gui_name)
        self.widget = widget

        if isinstance(self.gui_obj, QCheckBox):
            self.datatype = 'bool'
            self.gui_obj.stateChanged.connect(self.changed)
        elif isinstance(self.gui_obj, QAbstractSpinBox):
            self.datatype = 'number'
            self.gui_obj.valueChanged.connect(self.changed)
        elif isinstance(self.gui_obj, (QLineEdit, HistoryLineEdit)):
            self.datatype = 'string'
            self.gui_obj.textChanged.connect(self.changed)
            if isinstance(self.gui_obj, HistoryLineEdit):
                self.gui_obj.initialize('preferences_setting_' + self.name)
        elif isinstance(self.gui_obj, QComboBox):
            self.datatype = 'choice'
            self.gui_obj.editTextChanged.connect(self.changed)
            self.gui_obj.currentIndexChanged.connect(self.changed)
        else:
            raise ValueError(f'Unknown data type {self.gui_obj.__class__}')

        if isinstance(self.config_obj, ConfigProxy) and \
                not str(self.gui_obj.toolTip()):
            h = self.config_obj.help(self.name)
            if h:
                self.gui_obj.setToolTip(h)
        tt = str(self.gui_obj.toolTip())
        set_help_tips(self.gui_obj, tt)

    def changed(self, *args):
        self.widget.changed_signal.emit()

    def initialize(self):
        self.gui_obj.blockSignals(True)
        if self.datatype == 'choice':
            choices = self.choices or []
            if isinstance(self.gui_obj, EditWithComplete):
                self.gui_obj.all_items = choices
            else:
                self.gui_obj.clear()
                for x in choices:
                    if isinstance(x, string_or_bytes):
                        x = (x, x)
                    self.gui_obj.addItem(x[0], (x[1]))
        self.set_gui_val(self.get_config_val(default=False))
        self.gui_obj.blockSignals(False)
        self.initial_value = self.get_gui_val()

    def commit(self):
        val = self.get_gui_val()
        oldval = self.get_config_val()
        changed = val != oldval
        if changed:
            self.set_config_val(self.get_gui_val())
        return changed and self.restart_required

    def restore_defaults(self):
        self.set_gui_val(self.get_config_val(default=True))

    def get_config_val(self, default=False):
        if default:
            val = self.config_obj.defaults[self.name]
        else:
            val = self.config_obj[self.name]
        return val

    def set_config_val(self, val):
        self.config_obj[self.name] = val

    def set_gui_val(self, val):
        if self.datatype == 'bool':
            self.gui_obj.setChecked(bool(val))
        elif self.datatype == 'number':
            self.gui_obj.setValue(val)
        elif self.datatype == 'string':
            self.gui_obj.setText(val if val else '')
        elif self.datatype == 'choice':
            if isinstance(self.gui_obj, EditWithComplete):
                self.gui_obj.setText(val)
            else:
                idx = self.gui_obj.findData((val), role=Qt.ItemDataRole.UserRole,
                        flags=self.CHOICES_SEARCH_FLAGS)
                if idx == -1:
                    idx = 0
                self.gui_obj.setCurrentIndex(idx)

    def get_gui_val(self):
        if self.datatype == 'bool':
            val = bool(self.gui_obj.isChecked())
        elif self.datatype == 'number':
            val = self.gui_obj.value()
        elif self.datatype == 'string':
            val = str(self.gui_obj.text()).strip()
            if self.empty_string_is_None and not val:
                val = None
        elif self.datatype == 'choice':
            if isinstance(self.gui_obj, EditWithComplete):
                val = str(self.gui_obj.text())
            else:
                idx = self.gui_obj.currentIndex()
                if idx < 0:
                    idx = 0
                val = str(self.gui_obj.itemData(idx) or '')
        return val


class CommaSeparatedList(Setting):

    def set_gui_val(self, val):
        x = ''
        if val:
            x = ', '.join(val)
        self.gui_obj.setText(x)

    def get_gui_val(self):
        val = str(self.gui_obj.text()).strip()
        ans = []
        if val:
            ans = [x.strip() for x in val.split(',')]
            ans = [x for x in ans if x]
        return ans


class ConfigWidgetBase(QWidget, ConfigWidgetInterface):
    '''
    Base class that contains code to easily add standard config widgets like
    checkboxes, combo boxes, text fields and so on. See the :meth:`register`
    method.

    This class automatically handles change notification, resetting to default,
    translation between gui objects and config objects, etc. for registered
    settings.

    If your config widget inherits from this class but includes setting that
    are not registered, you should override the :class:`ConfigWidgetInterface` methods
    and call the base class methods inside the overrides.
    '''

    changed_signal = pyqtSignal()
    restart_now = pyqtSignal()
    supports_restoring_to_defaults = True
    restart_critical = False

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        if hasattr(self, 'setupUi'):
            self.setupUi(self)
        self.settings = {}
        self.child_tabs = []
        for v in self.__dict__.values():
            if isinstance(v, LazyConfigWidgetBase):
                self.child_tabs.append(v)

    def register(self, name, config_obj, gui_name=None, choices=None,
            restart_required=False, empty_string_is_None=True, setting=Setting):
        '''
        Register a setting.

        :param name: The setting name
        :param config_obj: The config object that reads/writes the setting
        :param gui_name: The name of the GUI object that presents an interface
                         to change the setting. By default it is assumed to be
                         ``'opt_' + name``.
        :param choices: If this setting is a multiple choice (combobox) based
                        setting, the list of choices. The list is a list of two
                        element tuples of the form: ``[(gui name, value), ...]``
        :param setting: The class responsible for managing this setting. The
                        default class handles almost all cases, so this param
                        is rarely used.
        '''
        setting = setting(name, config_obj, self, gui_name=gui_name,
                choices=choices, restart_required=restart_required,
                empty_string_is_None=empty_string_is_None)
        return self.register_setting(setting)

    def register_setting(self, setting):
        self.settings[setting.name] = setting
        return setting

    def initialize(self):
        for setting in self.settings.values():
            setting.initialize()

    def commit(self, *args):
        restart_required = False
        for setting in self.settings.values():
            rr = setting.commit()
            if rr:
                restart_required = True
        return restart_required

    def restore_defaults(self, *args):
        for setting in self.settings.values():
            setting.restore_defaults()

    def register_child_tab(self, tab):
        self.child_tabs.append(tab)


def get_plugin(category, name):
    for plugin in preferences_plugins():
        if plugin.category == category and plugin.name == name:
            return plugin
    raise ValueError(
            f'No Preferences Plugin with category: {category} and name: {name} found')


class LazyConfigWidgetBase(ConfigWidgetBase):
    '''
    Use this for dialogs that are tabs, accessed either from the left or on the
    top. It directly replaces ConfigWidgetBase, supporting the lazy operations.
    '''

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lazy_init_called = False

    def ensure_lazy_initialized(self):
        if not self.lazy_init_called:
            if hasattr(self, 'lazy_initialize'):
                self.lazy_initialize()
            self.lazy_init_called = True

    def set_changed_signal(self, changed_signal):
        self.changed_signal.connect(changed_signal)

    def restore_defaults(self):
        self.ensure_lazy_initialized()
        super().restore_defaults()

    def showEvent(self, event):
        # called when the widget is actually displays. We can't do something like
        # lazy_genesis because Qt does "things" before showEvent() is called. In
        # particular, the register function doesn't work with combo boxes if
        # genesis isn't called before everything else. Why is a mystery.
        self.ensure_lazy_initialized()
        super().showEvent(event)


class ConfigDialog(QDialog):

    def set_widget(self, w):
        self.w = w

    def accept(self):
        try:
            self.restart_required = self.w.commit()
        except AbortCommit:
            return
        QDialog.accept(self)


def init_gui():
    from calibre.gui2.main import option_parser
    from calibre.gui2.ui import Main
    from calibre.library import db
    parser = option_parser()
    opts, args = parser.parse_args([])
    actions = tuple(Main.create_application_menubar())
    db = db()
    gui = Main(opts)
    gui.initialize(db.library_path, db, actions, show_gui=False)
    return gui


def show_config_widget(category, name, gui=None, show_restart_msg=False,
        parent=None, never_shutdown=False, callback=None):
    '''
    Show the preferences plugin identified by category and name

    :param gui: gui instance, if None a hidden gui is created
    :param show_restart_msg: If True and the preferences plugin indicates a
    restart is required, show a message box telling the user to restart
    :param parent: The parent of the displayed dialog

    :return: True iff a restart is required for the changes made by the user to
    take effect
    '''
    from calibre.gui2 import gprefs
    pl = get_plugin(category, name)
    d = ConfigDialog(parent)
    d.resize(750, 550)
    conf_name = f'config_widget_dialog_geometry_{category}_{name}'
    d.setWindowTitle(_('Configure ') + pl.gui_name)
    d.setWindowIcon(QIcon.ic('config.png'))
    bb = QDialogButtonBox(d)
    bb.setStandardButtons(QDialogButtonBox.StandardButton.Apply|QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.RestoreDefaults)
    bb.accepted.connect(d.accept)
    bb.rejected.connect(d.reject)
    w = pl.create_widget(d)
    d.set_widget(w)
    bb.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(w.restore_defaults)
    bb.button(QDialogButtonBox.StandardButton.RestoreDefaults).setEnabled(w.supports_restoring_to_defaults)
    bb.button(QDialogButtonBox.StandardButton.Apply).setEnabled(False)
    bb.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(d.accept)

    def onchange():
        b = bb.button(QDialogButtonBox.StandardButton.Apply)
        b.setEnabled(True)
        b.setDefault(True)
        b.setAutoDefault(True)
    w.changed_signal.connect(onchange)
    bb.button(QDialogButtonBox.StandardButton.Cancel).setFocus(Qt.FocusReason.OtherFocusReason)
    l = QVBoxLayout()
    d.setLayout(l)
    l.addWidget(w)
    l.addWidget(bb)
    mygui = gui is None
    if gui is None:
        gui = init_gui()
        mygui = True
    w.genesis(gui)
    w.do_on_child_tabs('genesis', gui)
    w.initialize()
    w.do_on_child_tabs('initialize')
    d.restore_geometry(gprefs, conf_name)
    if callback is not None:
        callback(w)
    d.exec()
    d.save_geometry(gprefs, conf_name)
    rr = getattr(d, 'restart_required', False)
    if show_restart_msg and rr:
        from calibre.gui2 import warning_dialog
        warning_dialog(gui, 'Restart required', 'Restart required', show=True)
    if mygui and not never_shutdown:
        gui.shutdown()
    return rr


class ListViewWithMoveByKeyPress(QListView):

    def set_movement_functions(self, up_function, down_function):
        self.up_function = up_function
        self.down_function = down_function

    def event(self, event):
        if (event.type() == QEvent.KeyPress and
            QApplication.keyboardModifiers() == Qt.KeyboardModifier.ControlModifier):
            if event.key() == Qt.Key.Key_Up:
                self.up_function()
            elif event.key() == Qt.Key.Key_Down:
                self.down_function()
            return True
        return QListView.event(self, event)


class ListWidgetWithMoveByKeyPress(QListWidget):

    def set_movement_functions(self, up_function, down_function):
        self.up_function = up_function
        self.down_function = down_function

    def event(self, event):
        if (event.type() == QEvent.KeyPress and
            QApplication.keyboardModifiers() == Qt.KeyboardModifier.ControlModifier):
            if event.key() == Qt.Key.Key_Up:
                self.up_function()
            elif event.key() == Qt.Key.Key_Down:
                self.down_function()
            return True
        return QListWidget.event(self, event)


class TableWidgetWithMoveByKeyPress(QTableWidget):

    def set_movement_functions(self, up_function, down_function):
        self.up_function = up_function
        self.down_function = down_function

    def event(self, event):
        if (event.type() == QEvent.KeyPress and
            QApplication.keyboardModifiers() == Qt.KeyboardModifier.ControlModifier):
            if event.key() == Qt.Key.Key_Up:
                self.up_function()
            elif event.key() == Qt.Key.Key_Down:
                self.down_function()
            return True
        return QTableWidget.event(self, event)


# Testing {{{

def test_widget(category, name, gui=None, callback=None):
    show_config_widget(category, name, gui=gui, show_restart_msg=True, callback=callback)


def test_all():
    from qt.core import QApplication
    app = QApplication([])
    app
    gui = init_gui()
    for plugin in preferences_plugins():
        test_widget(plugin.category, plugin.name, gui=gui)
    gui.shutdown()


if __name__ == '__main__':
    test_all()
# }}}
