# Installation

The recommended way to install the application is via [uv](https://docs.astral.sh/uv/):

```bash
uv tool install git+https://github.com/vkhitrin/gojeera
```

Alternatively, you can install it using `pip`:

```bash
pip install git+https://github.com/vkhitrin/gojeera
```

or `pipx`:

```bash
pipx install git+https://github.com/vkhitrin/gojeera
```

After installing the package, you can run the CLI tool with the following command:

```shell
gojeera --help
```

This will show you the available commands for the CLI tool

```bash
Usage: gojeera [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  comments     Use it to add, list or delete comments associated to work...
  completions  Generate shell completion script.
  config       Shows the location of the configuration file.
  issues       Use it to search, update or delete work items.
  themes       List the available built-in themes.
  ui           Launches the gojeera application.
  users        Use it to search users and user groups.
  version      Shows the version of the tool.
```

Before you can launch the UI or use the CLI commands you need to configure the
application.  
Visit [configuration guide](/../docs/configuration.md) for more details.
