ElixirSublime
=============

Features
--------
- Code completion for modules and functions.
- Go to definition for modules and functions with `Shift+Click`
- Errors and warnings via [SublimeLinter3](https://github.com/SublimeLinter/SublimeLinter3).

Demo
----

![Demo](https://raw.githubusercontent.com/vishnevskiy/ElixirSublime/master/demo.gif)

Caveats
-------

This is built by piggybacking on `IEx.Autocomplete` so it can be a little naive.

- It does not understand macros, aliases and imports and therefore will not provide completion for them.
- Go to definition does not work on local functions.
- Since Elixir and Erlang standard library sources tend to not ship with the install it does best effort for go to definition by opening the documentation in the browser.

Installation
------------

1. Install [Sublime Package Control](https://sublime.wbond.net/installation#st3) if you haven't already.
2. Brand up the commands with `CTRL+Shift+P` or `CMD+Shift+P` and type `Package Control: Install Package` then `ElixirSublime`.
3. Repeat the previous step for `SublimeLinter` if you don't already have it.

*This package does not offer syntax highlighting. Use the offical [Elixir TextMate bundle](https://github.com/elixir-lang/elixir-tmbundle).*

Troubleshooting
---------------

If the plugin does not seem to work then it probably cannot find your Elixir installation. Provide the path in the default user settings.

```json
{
	"env": {
		"PATH": "path to elixir bins"
	}
}
```
