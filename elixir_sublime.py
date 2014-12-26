import tempfile
import os
import sublime
import sublime_plugin
import subprocess
import json
import socket
import re
import webbrowser

_socket = None
_logfile = open(os.path.join(tempfile.gettempdir(), 'ElixirSublime.log'), 'w')
_sessions = {}


def plugin_loaded(): 
    run_mix_task('deps.get')

    global _socket
    _socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    _socket.bind(('', 0))   
    _socket.listen(1)
    _socket.settimeout(5)


def plugin_unloaded():
    if _logfile:
        _logfile.close() 
    if _socket:
        _socket.close()   
    for session in _sessions.values():
        session.close()


def run_mix_task(cmd):
    settings = sublime.load_settings('Preferences.sublime-settings')
    cwd = os.path.join(os.path.dirname(__file__), 'sublime_completion')
    env = os.environ.copy()
    try:
        env['PATH'] += os.pathsep + settings.get('env')['PATH']
    except (TypeError, ValueError, KeyError):
        pass
    if _socket:
        env['ELIXIR_SUBLIME_PORT'] = str(_socket.getsockname()[1])

    if sublime.platform() == "windows":
        # on Windows, mix is a .bat file, which `subprocess` can't just launch like that. Use cmd.exe to launch the .bat file
        launcher = ['cmd', '/c', 'mix']

        # don't show the console window
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
    else:
        launcher = ['mix']
        startupinfo = None

    return subprocess.Popen( 
        launcher + cmd.split(), 
        cwd=cwd, 
        stderr=_logfile.fileno(),
        stdout=_logfile.fileno(),
        env=env,
        startupinfo=startupinfo)


def find_mix_project(cwd=None):
    cwd = cwd or os.getcwd()   
    if cwd == os.path.realpath('/'):
        return None
    elif os.path.exists(os.path.join(cwd, 'mix.exs')):
        return cwd
    else: 
        return find_mix_project(os.path.dirname(cwd))


def find_ebin_folders(mix_project):
    paths = []
    if mix_project is not None:
        lib_path = os.path.join(mix_project, '_build/dev/lib')
        for lib in os.listdir(lib_path):
            paths.append(os.path.join(lib_path, lib, 'ebin'))
    return paths


def is_elixir_file(filename):
    return filename and filename.endswith(('.ex', '.exs'))


def is_erlang_file(filename):
    return filename and filename.endswith('erl')


def expand_selection(view, point_or_region, aliases={}):
    region = view.expand_by_class(point_or_region, 
        sublime.CLASS_WORD_START | 
        sublime.CLASS_WORD_END, ' (){},[]%&')
    selection = view.substr(region).strip()
    if aliases:
        parts = selection.split('.')
        for alias, canonical in aliases.items():
            if alias == parts[0]:
                parts[0] = canonical
                return '.'.join(parts)
    return selection


def do_focus(fn, pattern):
    window = sublime.active_window()
    view = window.open_file(fn)
    if view.is_loading():
        focus(fn, pattern)
    else:
        window.focus_view(view)
        if pattern:
            r = view.find(pattern, 0)
            if r:
                row, col = view.rowcol(r.begin())
                pt = view.text_point(row, col)
                r = sublime.Region(pt, pt)
                view.sel().clear()
                view.sel().add(r)
                view.show(pt)


def focus(fn, pattern, timeout=25):
    sublime.set_timeout(lambda: do_focus(fn, pattern), timeout)


def focus_function(fn, function):
    focus(fn, 'def(p|macrop?)?\s%s\(?' % function)


def find_aliases(view):
    aliases = {}
    for region in view.find_all('^[\s\t]*?alias\s.+?$'):
        alias_line = view.substr(region).strip()
        for (pattern, replacer) in [
            (r'^alias (.+?)\.(.+?)$', lambda prefix, alias: '%s.%s' % (prefix, alias)),
            (r'^alias (.+?), as: (.+)$', lambda prefix, _: prefix),
        ]:
            matches = re.findall(pattern, alias_line)
            if matches:
                [(prefix, alias)] = matches
                aliases[alias] = replacer(prefix, alias)
                break
    return aliases


class ElixirSession(object):
    @classmethod
    def ensure(cls, cwd=None):
      mix_project = find_mix_project(cwd)
      session = _sessions.get(mix_project)
      if not session:
            session = cls(mix_project)
            _sessions[mix_project] = session
      if not session.alive:
        session.connect()
      return session

    def __init__(self, mix_project):
        self.mix_project = mix_project
        self.reset()

    @property
    def alive(self):
        return self.process is not None and self.process.returncode is None

    def reset(self):
        self.socket = None
        self.file = None
        self.process = None

    def connect(self):
        self.process = run_mix_task('run --no-halt')

        self.socket, _ = _socket.accept()
        self.socket.settimeout(5)

        self.file = self.socket.makefile() 

        for lib_path in find_ebin_folders(self.mix_project):
            self.send('PATH', lib_path)

    def send(self, cmd, args):
        try:
            self.socket.send(str.encode(cmd))
            self.socket.send(b' ')
            self.socket.send(str.encode(args))
            self.socket.send(b'\n')
            return True 
        except (OSError, IOError):
            self.reset()
            return False

    def recv(self):
        try:
            return self.file.readline().strip()
        except (OSError, IOError):
            self.reset()
            return None  

    def close(self): 
        if self.socket:
            self.socket.close() 
        if self.process:
            self.process.kill()


class ElixirGotoDefinition(sublime_plugin.TextCommand):
  def run(self, edit):
    aliases = find_aliases(self.view)
    selection = expand_selection(self.view, self.view.sel()[0], aliases=aliases)
    if selection:
        session = ElixirSession.ensure(os.path.dirname(self.view.file_name()))
        if session.send('GOTO', selection):
            goto = json.loads(session.recv())
            if goto:
                source = goto['source']
                function = goto['function']
                if not os.path.exists(source):
                    url = None
                    if is_erlang_file(source):
                        matches = re.findall(r'/lib/(.+?)/src/(.+?)\.erl$', source)
                        if matches:
                            [(_, module)] = matches
                            url = 'http://www.erlang.org/doc/man/%s.html' % module
                            if function:
                                url += '#%s-%s' % (goto['function'], goto['arities'][0])
                    elif is_elixir_file(source):
                        matches = re.findall(r'/lib/(.+?)/lib/(.+?)\.exs?$', source)
                        if matches:
                            [(lib, _)] = matches
                            url = 'http://elixir-lang.org/docs/stable/%s/%s.html' % (lib, goto['module'])
                            if function:
                                url += '#%s/%s' % (goto['function'], goto['arities'][0])
                    if url:
                        webbrowser.open(url)
                    return
                if function:
                    if is_erlang_file(source):
                        focus(source, '^%s\(' % function)
                    else:
                        focus_function(source, function)
                elif is_elixir_file(source):
                    focus(source, 'defmodule?\s%(module)s\sdo' % goto)
            else:
                focus_function(self.view.file_name(), selection)


class ElixirAutocomplete(sublime_plugin.EventListener):
    def on_activated_async(self, view):
        self.on_load_async(view)

    def on_load_async(self, view):
        filename = view.file_name()
        if is_elixir_file(filename):
            ElixirSession.ensure(os.path.dirname(filename))

    def on_query_completions(self, view, prefix, locations):
        if not is_elixir_file(view.file_name()):
            return None

        aliases = find_aliases(view)

        session = ElixirSession.ensure(os.path.dirname(view.file_name()))
        
        if not session.send('COMPLETE', expand_selection(view, locations[0], aliases=aliases)):
            return None

        completions = session.recv()
        if not completions:
            return None 

        seen_completions = set()

        rv = []
        for completion in json.loads(completions):
            seen_completions.add(completion['name'])

            if completion['type'] == 'module':
                rv.append(('%(name)s\t%(name)s' % completion, completion['content']))
            else: 
                rv.append(('%(name)s\t%(name)s/%(arity)s' % completion, completion['content']))

        for completion in view.extract_completions(prefix):
            if completion not in seen_completions:
                rv.append((completion,)) 

        return rv 

try:
  from SublimeLinter.lint import Linter

  class ElixirLinter(Linter):
      syntax = 'elixir'

      executable = 'elixirc' 
      tempfile_suffix = 'ex'

      regex = (
          r"^[^ ].+:(?P<line>\d+):"
          r"(?:(?P<warning>\swarning:\s)|(?P<error>\s))"
          r"(?P<message>.+)"
      )

      def cmd(self):
          command = [
            self.executable_path,
            '--warnings-as-errors',
            '--ignore-module-conflict',
            '-o', os.path.join(tempfile.gettempdir(), 'SublimeLinter3')
          ]

          for path in find_ebin_folders(find_mix_project()):
              command.extend(['-pa', path])

          return command
except ImportError:
  pass
