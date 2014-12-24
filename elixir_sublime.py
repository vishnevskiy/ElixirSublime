import tempfile
import os
import sublime
import sublime_plugin
import subprocess
import json
import socket

_socket = None
_logfile = open(os.path.join(tempfile.gettempdir(), 'ElixirSublime.log'), 'w')
_sessions = {}


def plugin_loaded(): 
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


def run_elixir():
    run_process('mix deps.get').wait()
    return run_process('mix run --no-halt')


def run_process(cmd):
    settings = sublime.load_settings('Preferences.sublime-settings')
    cwd = os.path.join(os.path.dirname(__file__), 'sublime_completion')
    env = os.environ.copy()
    try:
        env['PATH'] += ':' + settings.get('env')['PATH']
    except (TypeError, ValueError, KeyError):
        pass 
    env['ELIXIR_SUBLIME_PORT'] = str(_socket.getsockname()[1])
    return subprocess.Popen( 
        cmd.split(), 
        cwd=cwd, 
        stderr=_logfile.fileno(),
        stdout=_logfile.fileno(),
        env=env)


def find_mix_project(cwd=None):
    cwd = cwd or os.getcwd()   
    if cwd == '/':
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
        self.process = run_elixir() 

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
        except OSError:
            self.reset()
            return False

    def recv(self):
        try:
            return self.file.readline().strip()
        except OSError:
            self.reset()
            return None  

    def close(self): 
        if self.socket:
            self.socket.close() 
        if self.process:
            self.process.kill()


class ElixirAutocomplete(sublime_plugin.EventListener):
    def on_activated_async(self, view):
        self.on_load_async(view)

    def on_load_async(self, view):
        filename = view.file_name()
        if is_elixir_file(filename):
            ElixirSession.ensure(os.path.basename(filename))

    def on_query_completions(self, view, prefix, locations):
        if not is_elixir_file(view.file_name()):
            return None

        region = view.expand_by_class(locations[0], 
            sublime.CLASS_WORD_START | 
            sublime.CLASS_WORD_END | 
            sublime.CLASS_LINE_END | 
            sublime.CLASS_LINE_START, ' ')

        session = ElixirSession.ensure()
        
        if not session.send('COMPLETE', view.substr(region).strip()):
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

  class Elixirc(Linter):
      syntax = 'elixir'

      executable = 'elixirc'
      tempfile_suffix = 'ex'

      regex = (
          r"^[^ ].+:(?P<line>\d+):"
          r"(?:(?P<warning>\swarning:\s)|(?P<error>\s))"
          r"(?P<message>.+)"
      )
    
      defaults = { 
          'include_dirs': [],
          'pa': [] 
      }

      def cmd(self):
          tmpdir = os.path.join(tempfile.gettempdir(), 'SublimeLinter3')
          command = [
            self.executable_path,
            '--warnings-as-errors',
            '--ignore-module-conflict',
            '-o', tmpdir
          ]

          settings = self.get_view_settings()
          dirs = settings.get('include_dirs', [])
          paths = settings.get('pa', [])
          paths.extend(find_ebin_folders(find_mix_project()))

          for p in paths:
              command.extend(['-pa', p])

          for d in dirs:
              command.extend(['-I', d])

          return command
except ImportError:
  pass
