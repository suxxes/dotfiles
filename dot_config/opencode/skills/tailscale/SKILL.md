---
name: tailscale
description: Inspect and reason about Tailscale connectivity in this dotfiles setup.
---

# Tailscale

Use this skill when a task involves Tailscale connectivity, tailnet reachability, or machine-to-machine access.

- Start with read-only checks such as `tailscale status`, `tailscale ip`, and `tailscale netcheck`.
- Do not print auth keys, API keys, node keys, or 1Password item values.
- Do not run `tailscale up`, change advertised routes, change exit node settings, or alter ACL/DNS policy unless the user explicitly asks.
- On Linux/LXC machines, this dotfiles repo may authenticate Tailscale from 1Password during package setup.
- On macOS, expect interactive user authentication unless the machine already has an active Tailscale session.
