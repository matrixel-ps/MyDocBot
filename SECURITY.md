# Security Policy

## Supported versions

MyDocBot is a small personal project. Only the latest release (the `main`
branch, tagged `vX.Y.Z`) gets security fixes.

## Reporting a vulnerability

Please **don't open a public issue**. Report it privately through GitHub:
on the repository's **Security** tab, choose **Report a vulnerability**. That
opens a private advisory only the maintainer can see. Include what you found,
how to reproduce it, and what an attacker could do with it.

This is a one-person project, so replies may take a few days. You'll hear
back once the report has been looked at, and again when a fix is released.

## Scope

In scope:
- The MyDocBot code in this repository: the CLI, the TUIs, the Discord bot,
  and how they handle your Google sign-in (`token.json`, `credentials.json`)
  and data files (aliases, the offline queue, the tag index, the watcher's
  state), all kept in your data directory (`~/.config/mydocbot/` by default).
- The Discord bot's allowlist: a message from someone not in
  `allowed_user_ids` getting a note written or a reply.

Out of scope:
- Google's and Discord's own services and libraries (report those to them).
- Problems that need someone who already controls your user account or your
  data directory.

## What MyDocBot sends where

MyDocBot talks only to Google's Docs API (with your own OAuth client) and,
if you run the optional bot, to Discord. It has no server of its own and
sends no telemetry. Your sign-in and data files stay in your data directory,
written with owner-only (`0600`) permissions.
