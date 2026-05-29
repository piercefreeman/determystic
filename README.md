# Determystic

![Determystic Logo](https://raw.githubusercontent.com/piercefreeman/determystic/main/media/header.png)

Determystic is a library that forces your agents to give you a coding style that you're happy with - _deterministically_ every time.

It works by creating validators for your coding conventions, using the AST of your programming language. If you see a bad piece of code and can describe why it's bad and why you never want to see code like that in the future, there's a good chance we can write a deterministic validator to make sure it never happens again.

## Getting Started

We'll look into adding a MCP server in the future. But for the time being just asking Codex, Claude Code, or Cursor to run our validation script is usually good enough to get the job done.

Append to your `AGENTS.md` (Codex), `.cursorrules` (Cursor), or `CLAUDE.md` (Claude Code).

```
Before yielding results, you should ALWAYS call `uvx determystic validate`. Iterate until all of our validators are passing.
```

When you have an issue, you can add a special validation case using:

```shell
$ uvx determystic new-validator
```

`new-validator` uses a local coding agent CLI. By default it uses Codex when `codex` is installed, and falls back to Claude Code when only `claude` is installed. You can pin the choice per project in `pyproject.toml`:

```toml
[tool.determystic.settings]
validator_agent = "codex"  # "auto", "codex", or "claude"
```

## Example

Let's say your LLM generated some code that we don't like:

```python
from typing import Optional
from pydantic import BaseModel


class MyModel(BaseModel):
    name: Optional[str] = None
    age: int


def main():
    model = MyModel(name="John", age=30)
    print(model)

if __name__ == "__main__":
    main()
```

In this case, the fact that there's an Optional typehint instead of modern Python syntax (A | None = None). Both work but we prefer the latter. We can add this as a rule:

```bash
Code: name: Optional[str] = None
Feedback: Don't use Optional - use A | None
```

This will add a new .determystic hidden folder in your current project that you can introspect. But usually the logic looks pretty good zero-shot (we add internal tests to try to ensure that reasonableness of the validator we just wrote) so we can then run the validation:

```shell
$ uvx determystic validate example_project

Detailed Results:

✗ Custom Validator
  main.py:6: Use 'T | None' instead of 'Optional[T]' for type hints
        4 | 
        5 | class MyModel(BaseModel):
  >>>   6 |     name: Optional = None
        7 |     age: int
        8 |
```

## Background

Programming agents are getting _really good_. You're hard pressed to find a professional engineer these days that doesn't use Cursor or Claude Code for at least some part of their workflow.

My main annoyance in using these systems is when they output code that mostly works but is really messy, or against my own coding conventions. Here are some things that I've seen:

- When in a long running loop to try and fix some tests, models will sometimes wrap test logic in a try/except in order to get it to pass
- Models will use patch() by default over testing the underlying end to end logic
- They'll use bare assert statements over more detailed ValueError exception subclasses
- time.sleep() in tests to stopgap investigating race conditions, or just littered excessively 
- Most models have a very strong preference to use List[] and Optional[]. I want to use the modern `list[]` and `A | None`.

All these happen regardless of how strongly I try to coerce the system prompt. We've managed to successfully make models pretty [tenacious](https://pierce.dev/notes/the-tenacity-of-modern-llms/) in problem solving, but that doesn't help much if they're able to cheat on the given problems.

The main control we have over these systems today is in their system prompts: specifying an AGENTS.md, CLAUDE.md, or .cursorrules file to try to guide their behavior over text alone. This certainly works for higher level instructions like describing a feature scope. But we lose precision over what we're looking for by having to describe programming goals and constructs in natural language instead of code. Adding in AST validation changes that - and it turns out that LLMs are actually very good at writing AST validators even though they're pretty annoying for people.

## Bundled validators

Determystic includes bundled validators that can replace parts of a conventional lint stack. Bundled validators are opt-in: list the ones you want under `[tool.determystic].enabled`. Custom validators created in your project are enabled automatically unless excluded.

| Name | Validator | Description | Powered By |
|------|-----------|-------------|------------|
| `static_analysis` | **Static Analysis** | Code formatting, style conventions, and type checking | `ruff` + `ty` |
| `hanging_functions` | **Hanging Functions** | Detects unused functions, methods, classes, arguments, and unreachable code | AST analysis |
| `function_visibility` | **Function Visibility** | Requires externally used functions/methods before private helpers, and internal helpers to use `_` prefixes | Project import graph + AST analysis |
| `exception_coverage` | **Exception Coverage** | Requires every production `except` handler to be marked as covered by a test function | Test comment markers + AST analysis |
| `dynamic_ast` | **Dynamic AST** | Loads and runs custom validators from `.determystic` files | Custom AST traversers |

## Configuration

You can customize which validators run in your project by adding a `[tool.determystic]` section to your project `pyproject.toml`. The configuration supports enabling bundled validators, excluding specific validators from running, and ignoring generated or vendored paths.
Generated custom validator metadata is also tracked in this section; the generated validator source files still live under `.determystic/`.

### Enabling Bundled Validators

To enable bundled validators, add their names to the `enabled` list in your config:

```toml
# pyproject.toml
[tool.determystic]
enabled = [
    "static_analysis",
    "function_visibility"
]
```

Use `enabled = ["all"]` to opt into every bundled validator explicitly.

### Ignoring Files And Directories

To skip generated, vendored, or otherwise out-of-scope code across all validators, add project-relative entries to `ignore_paths`:

```toml
# pyproject.toml
[tool.determystic]
ignore_paths = [
    "generated/",
    "vendor/client.py",
    "build/**/*.py"
]
```

Directory entries ignore everything below that directory. Glob-style entries are also supported.

### Excluding Validators

Custom validators are active by default. To disable a custom validator or override an enabled bundled validator, add it to the `exclude` list:

```toml
# pyproject.toml
[tool.determystic]
exclude = [
    "my_custom_validator",
    "Function Visibility"
]
```

### Suppression Comments

Determystic validators share one suppression comment format. Use it when a line, function, class, or block is intentionally used by framework/plugin code that local static analysis cannot see.

```python
def public_plugin_hook(event, context):  # determystic: used
    return event

def generated_path(value):  # determystic: ignore[unused-argument]
    return 1

# determystic: ignore-start[function-visibility]
def framework_registered_helper():
    return "called dynamically"
# determystic: ignore-end[function-visibility]
```

Line comments apply to that line and the next line. Comments on or immediately above a function/class definition apply to that whole definition. `ignore-start[...]` and `ignore-end[...]` suppress a block.

Supported codes include `unused-function`, `unused-method`, `unused-class`, `unused-argument`, `unreachable-code`, `dead-code`, `private-prefix`, `function-order`, and `function-visibility`. Custom validators can also be suppressed by validator name.

### Exception Coverage Markers

The `exception_coverage` bundled validator does not require comments in production code. Instead, add a marker immediately above the test function, or above that test function's decorators, naming the production function and the handled exception types that test covers:

```python
# determystic: tested-exceptions[my_package.service.load_config: FileNotFoundError, ValueError]
def test_load_config_handles_missing_or_invalid_file():
    ...
```

Use the fully qualified production target, including class names for methods, such as `my_package.worker.Runner.execute`. Exception names may be written as `ValueError` or `module.ValueError`.

### Agent Selection

Generated validators are authored by a local coding agent CLI. The default `validator_agent = "auto"` checks for `codex` first, then `claude`. To force one agent for a project, add:

```toml
# pyproject.toml
[tool.determystic.settings]
validator_agent = "claude"
```

## Random notes

- Targeting just Python for now. Other languages can follow the same convention pretty closely, but we need to support AST validating for their syntax & test whether LLMs will output better AST validators when written in the same language or if we can use Python as a bridge for control logic
- Using an installed local coding agent, Codex by default with Claude Code as a fallback, to author the AST validators and test files
- We use .deterministic file extensions for our validation and validation test files. These are just python files but we prefer a different extension so they're not inadvertantly picked up by static analysis tools that just sniff for any .py extension. We might reconsider this in the future.
- Since determystic files are on disk, they should be portable across projects and usable by CI validation across a team
- Right now we don't support the editing case for existing validators - but this seems like an obvious extension in the future to try and make these more flexible given additional code that either incorrectly validates or does not validate
