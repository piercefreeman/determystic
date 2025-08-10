# Determystic

![Determystic Logo](https://raw.githubusercontent.com/piercefreeman/determystic/main/media/header.png)

Determystic is a library that forces your agents to give you a coding style that you're happy with - _deterministically_ every time.

It works by creating validators for your coding conventions, using the AST of your programming language. If you see a bad piece of code and can describe why it's bad and why you never want to see code like that in the future, there's a good chance we can write a deterministic validator to make sure it never happens again.

## Getting Started

We'll look into adding a MCP server in the future. But for the time being just asking Claude Code / Cursor to run our validation script is usually good enough to get the job done.

Append to your `.cursorrules` (Cursor) or `CLAUDE.md` (Claude Code).

```
Before yielding results, you should ALWAYS call `uvx determystic validate`. Iterate until all of our validators are passing.
```

Also setup your anthropic key for our global configuration. This will be accessible across projects so you should only have to do this once:

```shell
$ uvx determystic configure
```

When you have an issue, you can add a special validation case using:

```shell
$ uvx determystic new-validator
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

In this case, the fact that there's an Optional typehint instead of modern Python syntax (A | None = None). We can add this as a rule:

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

My main annoyance in using these systems is when they output code that mostly works but is really messy, or against my own coding conventions. Typehinting in Python is especially egregious here. No matter how much I try to coerce my AGENT.md files, all of the SOTA models have a very strong preference to use List[] and Optional[]. I want to use the modern `list[]` and `A | None`.

It's a small thing but it's representative of a larger problem. The main control we have over these systems today is in their system prompts: specifying a AGENT.md or .cursorrules file to try to guide their behavior over text alone. This certainly works for higher level instructions like describing a feature scope. But we lose precision over what we're looking for by having to describe programming goals and constructs in natural language instead of code. Adding in AST validation changes that - and it turns out that LLMs are actually very good at writing AST validators even though they're pretty annoying for people.

## Default validators

We provide some default validators that are good choices for most projects, but these can be disabled on a per project basis.

| Name | Validator | Description | Powered By |
|------|-----------|-------------|------------|
| `static_analysis` | **Static Analysis** | Code formatting, style conventions, and type checking | `ruff` + `ty` |
| `hanging_functions` | **Hanging Functions** | Detects functions that are defined but never called | AST analysis |
| `dynamic_ast` | **Dynamic AST** | Loads and runs custom validators from `.determystic` files | Custom AST traversers |

## Configuration

You can customize which validators run in your project by creating a `.determystic/config.toml` file in your project root. The configuration file supports excluding specific validators from running.

### Excluding Validators

To disable specific validators, add them to the `exclude` list in your config:

```toml
# .determystic/config.toml
exclude = [
    "Static Analysis",
    "Hanging Functions"
]
```

## Random notes

- Targeting just Python for now. Other languages can follow the same convention pretty closely, but we need to support AST validating for their syntax & test whether LLMs will output better AST validators when written in the same language or if we can use Python as a bridge for control logic
- Using Anthropic's Claude to do the authoring of the AST validators and the testing files (although in theory it would be very easy to swap this out for any other coding model)
- We use .deterministic file extensions for our validation and validation test files. These are just python files but we prefer a different extension so they're not inadvertantly picked up by static analysis tools that just sniff for any .py extension. We might reconsider this in the future.
- Since determystic files are on disk, they should be portable across projects and usable by CI validation across a team
- Right now we don't support the editing case for existing validators - but this seems like an obvious extension in the future to try and make these more flexible given additional code that either incorrectly validates or does not validate
