# determystic

Determystic is a library that forces your agents to give you a coding style that you're happy with - _deterministically_ every time.

It works by creating validators for your coding conventions, using the AST of your programming language. If you see a bad piece of code and can describe why it's bad and why you never want to see code like that in the future, there's a good chance we can write a deterministic validator to make sure it never happens again.

## Getting Started

We'll look into adding a MCP server in the future. But for the time being just asking Claude Code / Cursor to run our validation script is usually good enough to get the job done.

Append to your `.cursorrules` (Cursor) or `CLAUDE.md` (Claude Code).

```
Before yielding results, you should ALWAYS call `uvx determystic validate`.
```

When you have an issue, you can add a special validation case using:

```bash
uvx deterministic new-validator
```

## Background

Programming agents are getting _really good_. You're hard pressed to find a professional engineer these days that doesn't use Cursor or Claude Code for at least some part of their workflow.

My main annoyance in using these systems is when they output code that mostly works but is really messy, or against my own coding conventions. Typehinting in Python is especially egregious here. No matter how much I try to coerce my AGENT.md files, all of the SOTA models have a very strong preference to use List[] and Optional[]. I want to use the modern `list[]` and `A | None`.

It's a small thing but it's representative of a larger problem. The main control we have today over these systems today is in their system prompts: specifying a AGENT.md or .cursorrules file to try to guide their behavior over text alone. This certainly works for higher level instructions like describing a feature scope. But we lose precision over what we're looking for by having to describe programming goals and constructs in natural language instead of code.

## How it works

When you see your LLMs outputting something that you know you never want in practice, you'll want to add a deterministic "validator". Copy some portion of your code file that exhibits the problem and run:

```bash
uv run ...
```

## Limitations

- Targeting just Python for now. Other languages can follow the same convention pretty closely, but we need to support AST validating for their syntax & test whether LLMs will output better AST validators when written in the same language or if we can use Python as a bridge for control logic
- Using Anthropic's Claude to do the authoring of the AST validators and the testing files (although in theory it would be very easy to swap this out for any other coding model)
