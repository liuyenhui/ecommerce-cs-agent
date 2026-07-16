# Local Admin Test Credentials Design

**Date:** 2026-07-16

**Status:** Approved direction; pending implementation plan

## 1. Goal

Allow repeatable live Customer Admin and System Admin browser testing without pasting passwords into chat, storing credentials in the repository, printing credentials or cookies, or weakening the existing Customer/System authentication boundary.

The selected approach stores both Admin test accounts in one repository-external file on the developer's Mac:

```text
~/.config/ecommerce-cs-agent/admin-test-credentials.env
```

The file is local-only plaintext protected by owner-only filesystem permissions. It is not a replacement for Kubernetes Secrets, GitHub Secrets, or a production secret manager.

## 2. Credential File Contract

The file contains exactly these four keys:

```dotenv
CUSTOMER_ADMIN_EMAIL=
CUSTOMER_ADMIN_PASSWORD=
SYSTEM_ADMIN_EMAIL=
SYSTEM_ADMIN_PASSWORD=
```

Rules:

- all four values are required when the file is used;
- unknown or duplicate keys are rejected;
- blank values are rejected;
- values are parsed as data with Node's environment-file parser and are never evaluated by a shell;
- passwords may contain spaces and shell metacharacters without being executed;
- the file must not contain Cookie values, storageState JSON, Kubernetes credentials, API tokens, or unrelated secrets.

Existing process environment variables take precedence over values loaded from the file. This keeps one-command temporary overrides possible without editing the saved file.

## 3. Location and Permission Boundary

The default parent directory is:

```text
~/.config/ecommerce-cs-agent
```

The initializer creates the directory with mode `0700` and the credential file with mode `0600`. Loading refuses the file when any of these conditions is true:

- the path is inside the Git repository;
- the file or parent directory is a symbolic link;
- the file is not owned by the current user;
- the parent directory mode is not exactly `0700`;
- the file mode is not exactly `0600`;
- the file is not a regular file.

The loader reports only the path and the violated rule. It must never include a credential value or a source line in an error message.

## 4. CLI Behavior

Extend `scripts/admin_web_login_state.mjs` with:

```text
--credentials-file <path>
--init-credentials-file
```

Behavior:

- `--credentials-file` defaults to `~/.config/ecommerce-cs-agent/admin-test-credentials.env`;
- `--init-credentials-file` creates the secure parent directory and an empty four-key template, then exits without attempting login;
- initialization refuses to overwrite an existing file;
- normal login loads the credential file only when explicitly requested or when the default file already exists;
- `--skip-kubectl` plus a complete credential file performs both Customer and System Admin login without reading Kubernetes Secret values;
- without `--skip-kubectl`, current Kubernetes email/hash fallback behavior remains available;
- process environment variables remain the highest-precedence credential source.

The command continues to verify only:

- Customer Admin login plus `/v1/admin/auth/me`;
- System Admin login plus `/v1/system-admin/auth/me`;
- the expected isolated session Cookie name for each site.

It must not probe the other site's authentication endpoint.

## 5. Component Boundaries

Create `scripts/admin_web_credentials.mjs` for credential-file responsibilities:

- resolve and validate the configured path;
- create the secure template;
- validate ownership, file type, symlink, repository, and permission rules;
- parse and validate the four-key contract;
- merge file values below process environment values.

Keep `scripts/admin_web_login_state.mjs` responsible for:

- CLI argument parsing;
- optional Kubernetes Secret lookup;
- Customer/System login calls;
- isolated `/auth/me` verification;
- temporary storageState creation and redacted result output.

This separation keeps filesystem security tests independent from live login behavior.

## 6. Generated Session State

Successful login continues to create Playwright-compatible state under a new `/tmp/ecommerce-admin-auth-<timestamp>` directory:

- output directory mode: `0700`;
- state file mode: `0600`;
- Customer file contains only `agent_admin_session`;
- System file contains only `agent_system_admin_session`.

The command never prints Cookie contents. Browser tests delete the generated directory after use. Persisting storageState beside the credential file is not supported because session files expire and carry a larger accidental-sharing risk.

## 7. Tests

Deterministic tests cover:

- secure initialization produces `0700` / `0600`;
- initialization refuses overwrite;
- repository paths, symlinks, non-regular files, wrong owner, and broad permissions are rejected;
- exactly four allowed keys are accepted;
- missing, blank, unknown, and duplicate keys are rejected;
- quoted values and passwords containing shell metacharacters remain inert data;
- environment variables override file values;
- validation and login failures never include credential values;
- Customer and System values remain distinct;
- existing output directory, Cookie-name, and `/auth/me` isolation assertions continue to pass.

The repository's deployment/security tests must assert that:

- no default credential value is tracked;
- the documented path is outside the repository;
- no credential file is copied into Docker or Helm artifacts;
- the script does not log password, Cookie, or complete storageState content.

## 8. Operating Procedure

One-time initialization:

```bash
node scripts/admin_web_login_state.mjs --init-credentials-file
```

The user fills the four values directly on the local Mac. Passwords are never pasted into chat.

Create temporary authenticated browser state:

```bash
node scripts/admin_web_login_state.mjs \
  --credentials-file ~/.config/ecommerce-cs-agent/admin-test-credentials.env \
  --skip-kubectl
```

After desktop and mobile browser checks, delete the generated `/tmp/ecommerce-admin-auth-*` directory. The long-lived credential file remains owner-only and can be rotated independently for either account.

## 9. Non-Goals

- committing an encrypted or plaintext credential file;
- sharing the file between developers;
- synchronizing credentials through Git, cloud storage, or Codex memory;
- changing live Admin passwords or Kubernetes Secret values;
- persisting browser Cookies for long-term reuse;
- combining Customer and System sessions or authentication endpoints.

## 10. Acceptance Criteria

- both Admin accounts can be loaded from one owner-only file outside the repository;
- live login state can be generated without printing passwords or Cookies;
- Customer and System session/authentication boundaries remain isolated;
- insecure paths or permissions fail closed;
- no secret-bearing file or generated session state appears in Git status, commits, build context, logs, documentation, or chat.
